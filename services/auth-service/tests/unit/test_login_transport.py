"""Keycloak-mode `/auth/login`, `/auth/refresh`, `/auth/logout` — transport.

`session_native` has held the transport split since IDX-M1; this router,
which serves the same three paths while the issuer is still Keycloak, did
not — and a Mac signing in here was handed an HttpOnly cookie it has no
jar for. The app read a 200 with nothing to keep and said so ("this
server cannot keep this Mac signed in"), which is why these tests exist.

The properties under test:

  * a native client's refresh token is in the body and never in a cookie,
    a browser's is in the cookie and never in the body — on the way in
    (`/auth/login`), on every rotation, and on the way out;
  * an *expired* refresh token is an expiry. Keycloak reports it with the
    same `invalid_grant` as a replay, and charging a shut laptop lid as
    one would raise a `sec` audit event, end every other session the
    person has and denylist their account;
  * a live token Keycloak refuses is still a replay, with all of that.
"""

from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from auth import Claims

TENANT = UUID("00000000-0000-0000-0000-00000000000a")
USER = UUID("0a000000-0000-0000-0000-0000000000aa")
MAC = {"X-Client-Type": "macos"}


def _token(*, exp_offset: int) -> str:
    """A refresh-token-shaped JWT. Only its payload is ever read, and only
    to answer "did this expire?" — the signature is Keycloak's business."""

    def seg(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    head = seg({"alg": "HS512", "typ": "JWT"})
    body = seg(
        {
            "exp": int(time.time()) + exp_offset,
            "sub": str(USER),
            "tid": str(TENANT),
            "typ": "Refresh",
        }
    )
    return f"{head}.{body}.notasignature"


LIVE = _token(exp_offset=1800)
EXPIRED = _token(exp_offset=-60)


class FakeKeycloak:
    """Answers the three token calls; records what it was asked to revoke."""

    def __init__(self) -> None:
        self.refusals: dict[str, dict[str, str]] = {}
        self.logged_out_users: list[UUID] = []
        self.revoked_tokens: list[str] = []

    async def password_grant(self, *, username: str, password: str) -> Any:
        from auth_service.keycloak_client import TokenResponse

        return TokenResponse(
            access_token="access-1",
            refresh_token=LIVE,
            expires_in=900,
            refresh_expires_in=1800,
            token_type="Bearer",
        )

    async def refresh(self, *, refresh_token: str) -> Any:
        from auth_service.keycloak_client import KeycloakError, TokenResponse

        refusal = self.refusals.get(refresh_token)
        if refusal is not None:
            raise KeycloakError(status=400, body=refusal)
        return TokenResponse(
            access_token="access-2",
            refresh_token="rotated",
            expires_in=900,
            refresh_expires_in=1800,
            token_type="Bearer",
        )

    async def logout(self, *, refresh_token: str) -> None:
        self.revoked_tokens.append(refresh_token)

    async def logout_user(self, sub: UUID) -> None:
        self.logged_out_users.append(sub)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from auth_service import deps
    from auth_service.main import create_app
    from auth_service.routers import login as login_router

    kc = FakeKeycloak()
    audit: list[dict[str, Any]] = []
    denylisted: list[str] = []

    async def _write_event(**kwargs: Any) -> None:
        audit.append(kwargs)

    async def _revoke_sub(sub: str, *, ttl_seconds: int) -> None:
        denylisted.append(sub)

    async def _revoke_sid(sid: str, *, ttl_seconds: int) -> None:
        return None

    state = SimpleNamespace(
        keycloak=kc,
        jwks_cache=object(),
        audit_writer=SimpleNamespace(write_event=_write_event),
        app_pool=object(),
        denylist=SimpleNamespace(revoke_sub=_revoke_sub, revoke_sid=_revoke_sid),
    )
    deps.install_state(state)  # type: ignore[arg-type]

    async def _fake_verify(token: str, **kwargs: Any) -> Claims:
        return Claims(
            sub=USER,
            tid=TENANT,
            roles=["member"],
            scope="",
            mfa=False,
            mfa_enrolled=False,
            sid="sid-1",
            iss="https://test/issuer",
            aud="mdx",
            exp=9_999_999_999,
            iat=1_700_000_000,
        )

    monkeypatch.setattr(login_router, "verify_token", _fake_verify)
    return SimpleNamespace(
        client=TestClient(create_app()),
        kc=kc,
        audit=audit,
        denylisted=denylisted,
    )


def _kinds(audit: list[dict[str, Any]]) -> list[str]:
    return [call["kind"] for call in audit]


# ── the transport split ──────────────────────────────────────────────────


def test_native_login_puts_the_refresh_token_in_the_body(env: Any) -> None:
    r = env.client.post("/auth/login", json={"email": "a@b.c", "password": "pw"}, headers=MAC)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"] == LIVE
    assert body["refresh_expires_in"] == 1800
    # Workspace and roles too: a native client has no other source for them.
    assert body["tenant_id"] == str(TENANT)
    assert body["roles"] == ["member"]
    assert "set-cookie" not in {k.lower() for k in r.headers}


def test_web_login_puts_it_in_a_cookie_and_not_the_body(env: Any) -> None:
    r = env.client.post("/auth/login", json={"email": "a@b.c", "password": "pw"})
    assert r.status_code == 200, r.text
    assert r.json()["refresh_token"] is None
    assert r.cookies["mdx_rt"] == LIVE


def test_native_refresh_reads_the_body_and_rotates_in_the_body(env: Any) -> None:
    r = env.client.post("/auth/refresh", json={"refresh_token": LIVE}, headers=MAC)
    assert r.status_code == 200, r.text
    assert r.json()["refresh_token"] == "rotated"
    assert "set-cookie" not in {k.lower() for k in r.headers}


def test_web_refresh_reads_the_cookie_and_rotates_the_cookie(env: Any) -> None:
    r = env.client.post("/auth/refresh", cookies={"mdx_rt": LIVE})
    assert r.status_code == 200, r.text
    assert r.json()["refresh_token"] is None
    assert r.cookies["mdx_rt"] == "rotated"


def test_refresh_with_nothing_presented_says_so(env: Any) -> None:
    r = env.client.post("/auth/refresh", headers=MAC)
    assert r.status_code == 401
    assert r.json()["code"] == "no_refresh_token"


def test_native_logout_revokes_the_token_from_the_body(env: Any) -> None:
    r = env.client.post("/auth/logout", json={"refresh_token": LIVE}, headers=MAC)
    assert r.status_code == 204
    assert env.kc.revoked_tokens == [LIVE]


# ── an expiry is not a replay ────────────────────────────────────────────


def test_an_expired_refresh_is_an_expiry_not_a_replay(env: Any) -> None:
    env.kc.refusals[EXPIRED] = {
        "error": "invalid_grant",
        "error_description": "Token is not active",
    }
    r = env.client.post("/auth/refresh", json={"refresh_token": EXPIRED}, headers=MAC)
    assert r.status_code == 401
    assert r.json()["code"] == "session_expired"
    # Nobody's other sessions were ended over a laptop that slept.
    assert env.kc.logged_out_users == []
    assert env.denylisted == []
    assert "auth.refresh_replay_detected" not in _kinds(env.audit)


def test_a_live_token_keycloak_refuses_is_still_a_replay(env: Any) -> None:
    env.kc.refusals[LIVE] = {
        "error": "invalid_grant",
        "error_description": "Token is not active",
    }
    r = env.client.post("/auth/refresh", json={"refresh_token": LIVE}, headers=MAC)
    assert r.status_code == 401
    assert r.json()["code"] == "auth_refresh_replay"
    assert env.kc.logged_out_users == [USER]
    assert env.denylisted == [str(USER)]
    assert "auth.refresh_replay_detected" in _kinds(env.audit)
