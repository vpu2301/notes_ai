"""IDX-M1 (carrying IDX-A2's session half) — /auth/refresh and /auth/logout.

The properties under test are the ones a stored refresh token stands on:

  * rotation actually retires the old token, and the new one works;
  * a token presented twice minutes apart ends the session and the
    account's live access tokens — a replay is the one auth event that is
    anomalous by definition;
  * a token presented twice *seconds* apart does not, because that is a
    dropped response, not an attacker, and signing people out for their
    network's mistakes is how a session store loses its users' trust;
  * roles come from the membership on every rotation, never from the
    token being replaced;
  * the transport split holds: a native client's token is in the body and
    never in a cookie, a browser's is in the cookie and never in the body.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from auth_service.domain.identity_repository import (
    Identity,
    Membership,
    MembershipLookup,
    RefreshMatch,
    SessionRow,
    hash_refresh_token,
)
from auth_service.domain.session_service import SessionService
from auth_service.domain.signing_keys import KeySet
from auth_service.domain.token_service import TokenService

DEV_KEYS = Path(__file__).resolve().parents[4] / "infra" / "dev" / "auth-signing-dev.json"
ORIGIN = {"Origin": "http://localhost:5173"}
MAC = {"X-Client-Type": "macos"}


# ── fakes ────────────────────────────────────────────────────────────────


class FakeSessions:
    """`auth_sessions`, in a dict, including the rotation columns."""

    def __init__(self) -> None:
        self.rows: dict[UUID, SessionRow] = {}
        self.current: dict[UUID, bytes] = {}
        self.previous: dict[UUID, bytes | None] = {}
        self.rotated_at: dict[UUID, datetime | None] = {}
        self.revoked_reasons: dict[UUID, str] = {}

    async def create(
        self,
        *,
        identity_id: UUID,
        tenant_id: UUID,
        refresh_token: str,
        ttl_seconds: int,
        client_type: str,
        ip: str = "",
        user_agent: str = "",
        mfa: bool = False,
        device_name: str = "",
    ) -> tuple[UUID, datetime]:
        sid = uuid4()
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        self.rows[sid] = SessionRow(
            id=sid,
            identity_id=identity_id,
            tenant_id=tenant_id,
            client_type=client_type,
            device_name=device_name,
            user_agent=user_agent,
            ip=ip,
            created_at=now,
            last_used_at=now,
            last_authenticated_at=now,
            expires_at=expires_at,
            revoked_at=None,
            mfa=mfa,
        )
        self.current[sid] = hash_refresh_token(refresh_token)
        self.previous[sid] = None
        self.rotated_at[sid] = None
        return sid, expires_at

    async def find_by_refresh_token(self, token: str) -> RefreshMatch | None:
        digest = hash_refresh_token(token)
        for sid, row in self.rows.items():
            if self.current.get(sid) == digest:
                return RefreshMatch(session=row, is_current=True, rotated_at=self.rotated_at[sid])
            if self.previous.get(sid) == digest:
                return RefreshMatch(session=row, is_current=False, rotated_at=self.rotated_at[sid])
        return None

    async def rotate(
        self,
        *,
        session_id: UUID,
        presented: str,
        new_token: str,
        expires_at: datetime,
        ip: str,
        presented_is_current: bool,
    ) -> bool:
        row = self.rows.get(session_id)
        if row is None or row.revoked_at is not None:
            return False
        digest = hash_refresh_token(presented)
        expected = self.current[session_id] if presented_is_current else self.previous[session_id]
        if expected != digest:
            return False
        # The replaced token is always the one remembered; only a rotation
        # of the *current* token moves the grace window.
        self.previous[session_id] = self.current[session_id]
        if presented_is_current:
            self.rotated_at[session_id] = datetime.now(UTC)
        self.current[session_id] = hash_refresh_token(new_token)
        self.rows[session_id] = replace(
            row, expires_at=expires_at, last_used_at=datetime.now(UTC), ip=ip or row.ip
        )
        return True

    async def get(self, session_id: UUID) -> SessionRow | None:
        return self.rows.get(session_id)

    async def set_tenant(self, session_id: UUID, *, tenant_id: UUID) -> bool:
        row = self.rows.get(session_id)
        if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
            return False
        self.rows[session_id] = replace(row, tenant_id=tenant_id)
        return True

    async def revoke(self, session_id: UUID, *, identity_id: UUID, reason: str) -> bool:
        row = self.rows.get(session_id)
        if row is None or row.revoked_at is not None or row.identity_id != identity_id:
            return False
        self.rows[session_id] = replace(row, revoked_at=datetime.now(UTC))
        self.revoked_reasons[session_id] = reason
        return True

    # -- test helpers --

    def age(self, session_id: UUID, *, by: timedelta) -> None:
        """Move one session's whole timeline backwards."""
        row = self.rows[session_id]
        self.rows[session_id] = replace(row, created_at=row.created_at - by)
        if self.rotated_at[session_id] is not None:
            self.rotated_at[session_id] = self.rotated_at[session_id] - by  # type: ignore[operator]

    def expire(self, session_id: UUID) -> None:
        row = self.rows[session_id]
        self.rows[session_id] = replace(row, expires_at=datetime.now(UTC) - timedelta(seconds=1))


class FakeIdentities:
    def __init__(self) -> None:
        self.rows: dict[UUID, Identity] = {}
        self.memberships: dict[UUID, list[Membership]] = {}
        # Tenants that have not been closed; anything absent is live.
        self.live_tenants: dict[UUID, bool] = {}
        self.last_tenant: dict[UUID, UUID] = {}

    def seed(self, *, email: str = "olena@acme.example", status: str = "active") -> Identity:
        identity = Identity(
            id=uuid4(),
            email=email,
            email_verified_at=datetime.now(UTC),
            display_name="Olena",
            status=status,
            mfa_enabled=False,
            has_password=False,
            last_tenant_id=None,
            failed_login_count=0,
            lock_count=0,
            locked_until=None,
            lock_notified_at=None,
            deletion_requested_at=None,
        )
        self.rows[identity.id] = identity
        return identity

    async def get(self, identity_id: UUID) -> Identity | None:
        return self.rows.get(identity_id)

    async def list_memberships(self, identity_id: UUID) -> list[Membership]:
        return [m for m in self.memberships.get(identity_id, []) if m.status == "active"]

    async def membership_in(self, identity_id: UUID, tenant_id: UUID) -> MembershipLookup:
        for membership in self.memberships.get(identity_id, []):
            if membership.tenant_id == tenant_id:
                return MembershipLookup(
                    membership=membership,
                    tenant_active=self.live_tenants.get(tenant_id, True),
                )
        return MembershipLookup(membership=None, tenant_active=False)

    async def set_last_tenant(self, identity_id: UUID, *, tenant_id: UUID) -> None:
        self.last_tenant[identity_id] = tenant_id


class FakeDenylist:
    def __init__(self) -> None:
        self.subs: list[str] = []
        self.sids: list[str] = []

    async def revoke_sub(self, sub: str, *, ttl_seconds: int) -> None:
        self.subs.append(sub)

    async def revoke_sid(self, sid: str, *, ttl_seconds: int) -> None:
        self.sids.append(sid)


# ── harness ──────────────────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from auth_service import deps
    from auth_service.config import settings
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "native")
    monkeypatch.setattr(settings, "auth_refresh_grace_seconds", 30)

    sessions = FakeSessions()
    identities = FakeIdentities()
    denylist = FakeDenylist()
    audit_calls: list[dict[str, Any]] = []

    async def _write_event(**kwargs: Any) -> None:
        audit_calls.append(kwargs)

    token_service = TokenService(
        keys=KeySet.from_json(DEV_KEYS.read_text()),
        issuer="http://localhost:8000",
        audience="mdx-api",
        access_ttl_seconds=900,
    )
    service = SessionService(
        tokens=token_service,
        sessions=sessions,  # type: ignore[arg-type]
        identities=identities,  # type: ignore[arg-type]
        refresh_ttl_seconds=2592000,
        absolute_ttl_seconds=7776000,
        grace_seconds=settings.auth_refresh_grace_seconds,
    )
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            jwks_cache=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            session_service=service,
            denylist=denylist,
        )
    )

    identity = identities.seed()
    tenant_id = uuid4()
    identities.memberships[identity.id] = [
        Membership(tenant_id=tenant_id, name="acme", kind="team", role="admin", status="active")
    ]
    token = secrets.token_urlsafe(32)
    sid, _ = _run(
        sessions.create(
            identity_id=identity.id,
            tenant_id=tenant_id,
            refresh_token=token,
            ttl_seconds=2592000,
            client_type="macos",
        )
    )

    app = create_app()
    return SimpleNamespace(
        app=app,
        client=TestClient(app),
        sessions=sessions,
        identities=identities,
        denylist=denylist,
        audit=audit_calls,
        service=service,
        identity=identity,
        tenant_id=tenant_id,
        sid=sid,
        token=token,
    )


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _refresh(env: Any, token: str | None = None, *, native: bool = True, cookie: str | None = None):
    headers = dict(MAC) if native else dict(ORIGIN)
    cookies = {"mdx_rt": cookie} if cookie else None
    body: dict[str, Any] = {}
    if token is not None:
        body["refresh_token"] = token
    return env.client.post("/auth/refresh", json=body, headers=headers, cookies=cookies)


def _claims(access_token: str) -> dict[str, Any]:
    return jwt.get_unverified_claims(access_token)


# ── rotation ─────────────────────────────────────────────────────────────


def test_refresh_rotates_and_the_old_token_stops_working(env: Any) -> None:
    first = _refresh(env, env.token)
    assert first.status_code == 200
    body = first.json()
    new_token = body["refresh_token"]
    assert new_token and new_token != env.token
    assert body["access_token"]
    assert body["tenant_id"] == str(env.tenant_id)

    # The new one works.
    assert _refresh(env, new_token).status_code == 200

    # The original is now two generations old. One generation is kept —
    # the row has one slot for the retired hash — so a token this old is
    # not *attributable* to the session any more and is answered
    # `session_expired` rather than `auth_refresh_replay`. The session it
    # once belonged to is untouched, which is the honest outcome: nothing
    # here proves the token was stolen rather than simply forgotten.
    env.sessions.age(env.sid, by=timedelta(minutes=5))
    stale = _refresh(env, env.token)
    assert stale.status_code == 401
    assert stale.json()["code"] == "session_expired"
    assert env.sessions.rows[env.sid].revoked_at is None


def test_native_response_carries_the_token_and_no_cookie(env: Any) -> None:
    resp = _refresh(env, env.token)
    assert resp.json()["refresh_token"]
    assert "set-cookie" not in {k.lower() for k in resp.headers}


def test_web_response_carries_the_cookie_and_no_token(env: Any) -> None:
    resp = _refresh(env, None, native=False, cookie=env.token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["refresh_token"] is None
    assert body["refresh_expires_in"] is None
    assert "mdx_rt=" in resp.headers["set-cookie"]


def test_roles_are_re_read_from_the_membership(env: Any) -> None:
    """A session must not out-live the rights it was opened with."""
    first = _refresh(env, env.token).json()
    assert _claims(first["access_token"])["roles"] == ["tenant_admin", "member"]

    env.identities.memberships[env.identity.id] = [
        Membership(
            tenant_id=env.tenant_id, name="acme", kind="team", role="viewer", status="active"
        )
    ]
    second = _refresh(env, first["refresh_token"]).json()
    assert _claims(second["access_token"])["roles"] == ["viewer"]
    assert second["roles"] == ["viewer"]


def test_the_session_id_survives_rotation(env: Any) -> None:
    """`sid` is the session, not the token: rotating must not re-key it."""
    body = _refresh(env, env.token).json()
    assert _claims(body["access_token"])["sid"] == str(env.sid)


# ── the grace window ─────────────────────────────────────────────────────


def test_a_retried_token_inside_the_grace_window_is_answered(env: Any) -> None:
    """The dropped-response case: same token twice, seconds apart."""
    first = _refresh(env, env.token).json()
    again = _refresh(env, env.token)
    assert again.status_code == 200
    assert again.json()["refresh_token"] not in {env.token, first["refresh_token"]}
    assert env.sessions.rows[env.sid].revoked_at is None


def test_a_grace_retry_does_not_extend_its_own_window(env: Any) -> None:
    """Otherwise a stolen token could renew its grace indefinitely."""
    _refresh(env, env.token)
    rotated_at = env.sessions.rotated_at[env.sid]
    _refresh(env, env.token)
    assert env.sessions.rotated_at[env.sid] == rotated_at


def test_concurrent_refreshes_with_one_token_both_succeed(env: Any) -> None:
    """Two callers, one token, no ordering between them.

    The loser of the rotation race re-reads and comes out through the
    grace path rather than being told its perfectly good token is gone.
    """
    first = _refresh(env, env.token)
    second = _refresh(env, env.token)
    assert first.status_code == second.status_code == 200
    assert first.json()["refresh_token"] != second.json()["refresh_token"]


# ── replay ───────────────────────────────────────────────────────────────


def test_the_winner_of_a_race_keeps_a_working_token(env: Any) -> None:
    """Two callers, one token, and neither is signed out for it.

    The second caller comes through the grace path and is given a token of
    its own; the first caller's token becomes the retired one, so it still
    works inside the window rather than being orphaned by a race it never
    knew about.
    """
    first = _refresh(env, env.token).json()["refresh_token"]
    second = _refresh(env, env.token).json()["refresh_token"]

    assert _refresh(env, first).status_code == 200
    assert _refresh(env, second).status_code == 200
    assert env.sessions.rows[env.sid].revoked_at is None


def test_replay_revokes_the_session_and_denylists_the_identity(env: Any) -> None:
    _refresh(env, env.token)
    env.sessions.age(env.sid, by=timedelta(minutes=5))

    resp = _refresh(env, env.token)
    assert resp.status_code == 401
    assert resp.json()["code"] == "auth_refresh_replay"
    assert resp.headers["content-type"].startswith("application/problem+json")

    assert env.sessions.rows[env.sid].revoked_at is not None
    assert env.sessions.revoked_reasons[env.sid] == "replay"
    assert env.denylist.subs == [str(env.identity.id)]
    kinds = [c["kind"] for c in env.audit]
    assert "auth.refresh_replay_detected" in kinds
    assert any(
        c["kind"] == "auth.refresh_replay_detected" and c["severity"].value == "sec"
        for c in env.audit
    )


def test_a_revoked_session_cannot_be_refreshed(env: Any) -> None:
    _run(env.sessions.revoke(env.sid, identity_id=env.identity.id, reason="user_revoked"))
    resp = _refresh(env, env.token)
    assert resp.status_code == 401
    assert resp.json()["code"] == "session_expired"


# ── lifetimes ────────────────────────────────────────────────────────────


def test_an_idle_session_past_its_expiry_is_over(env: Any) -> None:
    env.sessions.expire(env.sid)
    assert _refresh(env, env.token).json()["code"] == "session_expired"


def test_the_absolute_cap_ends_a_session_that_keeps_being_used(env: Any) -> None:
    """Sliding the idle window forward must not make a session immortal."""
    env.sessions.age(env.sid, by=timedelta(days=91))
    # Still inside its (sliding) idle window — only the cap can end it.
    assert env.sessions.rows[env.sid].expires_at > datetime.now(UTC)
    assert _refresh(env, env.token).json()["code"] == "session_expired"


def test_the_idle_window_slides_on_every_rotation(env: Any) -> None:
    before = env.sessions.rows[env.sid].expires_at
    env.sessions.age(env.sid, by=timedelta(days=10))
    _refresh(env, env.token)
    assert env.sessions.rows[env.sid].expires_at > before


# ── the account behind the session ───────────────────────────────────────


def test_a_disabled_account_cannot_refresh(env: Any) -> None:
    env.identities.rows[env.identity.id] = replace(env.identity, status="disabled")
    resp = _refresh(env, env.token)
    assert resp.status_code == 403
    assert resp.json()["code"] == "account_disabled"
    assert env.sessions.rows[env.sid].revoked_at is not None


def test_losing_the_membership_ends_the_session(env: Any) -> None:
    """Removed from this workspace, still a member of another one."""
    env.identities.memberships[env.identity.id] = [
        Membership(tenant_id=uuid4(), name="other", kind="team", role="member", status="active")
    ]
    assert _refresh(env, env.token).json()["code"] == "session_expired"
    assert env.sessions.revoked_reasons[env.sid] == "membership_lost"


def test_no_membership_anywhere_is_no_workspace(env: Any) -> None:
    """Signing in again cannot fix this one, so it does not say "expired"."""
    env.identities.memberships[env.identity.id] = []
    resp = _refresh(env, env.token)
    assert resp.status_code == 409
    assert resp.json()["code"] == "no_workspace"


# ── missing / unknown tokens ─────────────────────────────────────────────


def test_no_token_at_all_has_its_own_code(env: Any) -> None:
    resp = _refresh(env, None)
    assert resp.status_code == 401
    assert resp.json()["code"] == "no_refresh_token"


def test_an_unknown_token_says_nothing_more(env: Any) -> None:
    resp = _refresh(env, secrets.token_urlsafe(32))
    assert resp.status_code == 401
    assert resp.json()["code"] == "session_expired"


# ── logout ───────────────────────────────────────────────────────────────


def test_logout_revokes_the_session_and_clears_the_cookie(env: Any) -> None:
    resp = env.client.post("/auth/logout", json={"refresh_token": env.token}, headers=MAC)
    assert resp.status_code == 204
    assert "mdx_rt=" in resp.headers["set-cookie"]
    assert env.sessions.rows[env.sid].revoked_at is not None
    assert env.sessions.revoked_reasons[env.sid] == "logout"
    assert _refresh(env, env.token).json()["code"] == "session_expired"


def test_logout_is_idempotent(env: Any) -> None:
    for _ in range(2):
        assert (
            env.client.post(
                "/auth/logout", json={"refresh_token": env.token}, headers=MAC
            ).status_code
            == 204
        )


def test_logout_without_a_token_still_answers_204(env: Any) -> None:
    assert env.client.post("/auth/logout", json={}, headers=MAC).status_code == 204


def test_logout_denylists_the_session_it_ended(env: Any) -> None:
    env.client.post("/auth/logout", json={"refresh_token": env.token}, headers=MAC)
    assert env.denylist.sids == [str(env.sid)]


# ── a Keycloak-shaped token is refused, never 422'd ──────────────────────


# A realistic Keycloak refresh token: a signed JWT carrying a realm's worth
# of claims, comfortably past the ~50 chars a native `nrt_` handle needs.
KEYCLOAK_SHAPED = "eyJhbGciOiJIUzI1NiJ9." + "A" * 900 + ".signature"


def test_a_keycloak_shaped_token_is_refused_not_rejected_as_malformed(env: Any) -> None:
    """Length must not be what answers this request.

    In `dual` this router owns `/auth/refresh` for both issuers and hands
    JWT-shaped tokens to `login.py`; a body cap below a real Keycloak
    token 422s that client before the delegation can happen. Here in
    `native` the token is a stale credential and 401 is the right answer —
    either way the client learns its session is over and signs in again,
    which a 422 never tells it.
    """
    resp = _refresh(env, KEYCLOAK_SHAPED)
    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == "session_expired"


def test_logout_accepts_a_keycloak_shaped_token(env: Any) -> None:
    """Same cap, same delegation — a client that cannot log out is stuck."""
    resp = env.client.post("/auth/logout", json={"refresh_token": KEYCLOAK_SHAPED}, headers=MAC)
    assert resp.status_code == 204, resp.text


def test_a_token_past_the_cap_is_still_rejected(env: Any) -> None:
    """The guard is loosened, not removed."""
    assert _refresh(env, "x" * 5000).status_code == 422


# ── the origin check still applies ───────────────────────────────────────


def test_a_browser_without_an_allowed_origin_is_refused(env: Any) -> None:
    resp = env.client.post("/auth/refresh", json={}, cookies={"mdx_rt": env.token})
    assert resp.status_code == 403
    assert resp.json()["code"] == "origin_not_allowed"


# ── POST /auth/token — switching workspace (IDX-A2 F3, carried by M2) ─────


def _claims_for(env: Any, *, sid: UUID | None = None, tid: UUID | None = None) -> Any:
    """The bearer the switcher would be holding."""
    from auth import Claims

    now = int(datetime.now(UTC).timestamp())
    return Claims(
        sub=env.identity.id,
        tid=tid or env.tenant_id,
        sid=str(sid or env.sid),
        roles=["tenant_admin"],
        iss="http://localhost:8000",
        aud="mdx-api",
        exp=now + 900,
        iat=now,
    )


def _switch(env: Any, tenant_id: UUID, *, activate: bool = True, claims: Any = None):
    from auth_service import deps

    env.app.dependency_overrides[deps.current_user] = lambda: claims or _claims_for(env)
    try:
        return env.client.post(
            "/auth/token",
            json={"tenant_id": str(tenant_id), "activate": activate},
            headers=MAC,
        )
    finally:
        env.app.dependency_overrides.clear()


def _second_workspace(env: Any, *, status: str = "active", live: bool = True) -> UUID:
    tenant_id = uuid4()
    env.identities.memberships[env.identity.id].append(
        Membership(tenant_id=tenant_id, name="other", kind="team", role="member", status=status)
    )
    env.identities.live_tenants[tenant_id] = live
    return tenant_id


def test_switching_mints_a_token_for_the_other_workspace(env: Any) -> None:
    other = _second_workspace(env)

    resp = _switch(env, other)

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == str(other)
    assert body["roles"] == ["member"], "roles come from the membership being switched to"
    claims = _claims(body["access_token"])
    assert claims["tid"] == str(other)
    assert claims["sid"] == str(env.sid), "same session, pointed somewhere else"


def test_switching_returns_no_refresh_token(env: Any) -> None:
    """Nothing rotated, so there is no second credential to hand out."""
    other = _second_workspace(env)

    body = _switch(env, other).json()

    assert body["refresh_token"] is None
    assert body["refresh_expires_in"] is None


def test_activating_moves_the_session_so_a_refresh_comes_back_to_it(env: Any) -> None:
    other = _second_workspace(env)

    _switch(env, other, activate=True)

    assert env.sessions.rows[env.sid].tenant_id == other
    assert env.identities.last_tenant[env.identity.id] == other
    # And the proof that matters: the next refresh mints for the new one.
    refreshed = _refresh(env, env.token).json()
    assert refreshed["tenant_id"] == str(other)
    assert refreshed["roles"] == ["member"]


def test_borrowing_a_token_does_not_move_the_session(env: Any) -> None:
    """An upload finishing in the workspace it started in must not move
    somebody's session out from under them."""
    other = _second_workspace(env)

    borrowed = _switch(env, other, activate=False)

    assert borrowed.status_code == 200
    assert _claims(borrowed.json()["access_token"])["tid"] == str(other)
    assert env.sessions.rows[env.sid].tenant_id == env.tenant_id
    assert env.identity.id not in env.identities.last_tenant


def test_a_workspace_i_am_not_in_is_answered_like_one_that_does_not_exist(env: Any) -> None:
    stranger = _switch(env, uuid4())
    assert stranger.status_code == 403
    assert stranger.json()["code"] == "not_a_member"


def test_a_suspended_membership_says_so(env: Any) -> None:
    other = _second_workspace(env, status="suspended")

    resp = _switch(env, other)

    assert resp.status_code == 403
    assert resp.json()["code"] == "membership_suspended"
    assert env.sessions.rows[env.sid].tenant_id == env.tenant_id


def test_a_closed_workspace_says_so(env: Any) -> None:
    other = _second_workspace(env, live=False)

    resp = _switch(env, other)

    assert resp.status_code == 403
    assert resp.json()["code"] == "tenant_dissolved"


def test_a_revoked_session_cannot_switch(env: Any) -> None:
    other = _second_workspace(env)
    _run(env.sessions.revoke(env.sid, identity_id=env.identity.id, reason="user_revoked"))

    resp = _switch(env, other)

    assert resp.status_code == 401
    assert resp.json()["code"] == "session_revoked"


def test_a_keycloak_era_sid_cannot_switch(env: Any) -> None:
    other = _second_workspace(env)
    claims = _claims_for(env)
    claims = claims.model_copy(update={"sid": "not-a-uuid"})

    resp = _switch(env, other, claims=claims)

    assert resp.status_code == 401
    assert resp.json()["code"] == "session_revoked"


def test_a_disabled_account_cannot_switch(env: Any) -> None:
    other = _second_workspace(env)
    env.identities.rows[env.identity.id] = replace(env.identity, status="disabled")

    resp = _switch(env, other)

    assert resp.status_code == 403
    assert resp.json()["code"] == "account_disabled"


def test_the_switch_is_audited_once_and_only_when_it_moved(env: Any) -> None:
    other = _second_workspace(env)

    _switch(env, other, activate=False)
    assert not [c for c in env.audit if c["kind"] == "auth.tenant_switched"]

    _switch(env, other, activate=True)
    switched = [c for c in env.audit if c["kind"] == "auth.tenant_switched"]
    assert len(switched) == 1
    assert switched[0]["payload"]["from_tenant_id"] == str(env.tenant_id)
    assert switched[0]["payload"]["to_tenant_id"] == str(other)
