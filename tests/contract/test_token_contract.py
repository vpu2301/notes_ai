"""IDX-A2 acceptance: a token auth-service mints is accepted by every service's
own ``current_user`` dependency, with zero changes to ``libs/auth``.

Each service's ``deps.current_user`` builds ``libs/auth``'s dependency from
``state.jwks_cache`` + ``settings.auth_audience/auth_issuer``. Here the state
is a stub whose JWKS cache is served in-memory from the *auth-service key
set*, so the whole path — header parsing, RS256 verification, ``Claims``
parsing, denylist hook — runs for real against a real auth-service token.

Run from the repo root (`uv run pytest tests/contract/`), where every
service is importable.
"""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from auth import JwksCache, build_current_user
from auth_service.domain.signing_keys import KeySet
from auth_service.domain.token_service import TokenService
from auth_service.routers import wellknown

ISSUER = "https://auth.contract.test"
AUDIENCE = "mdx-api"

SERVICES = [
    ("note_service", "note_service.deps", "note_service.config"),
    ("asr_service", "asr_service.deps", "asr_service.config"),
    ("nlp_service", "nlp_service.deps", "nlp_service.config"),
    ("dictation_service", "dictation_service.deps", "dictation_service.config"),
    ("notification_service", "notification_service.deps", "notification_service.config"),
]


@pytest.fixture(scope="module")
def issuer() -> tuple[KeySet, TokenService]:
    raw = json.loads(
        __import__("subprocess")
        .run(
            [
                "python",
                "scripts/ops/gen-signing-key.py",
                "--list",
                "--bits",
                "2048",
                "--days",
                "30",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout
    )
    keys = KeySet.from_json(json.dumps(raw))
    return keys, TokenService(keys=keys, issuer=ISSUER, audience=AUDIENCE, access_ttl_seconds=900)


def _jwks_cache_from(keys: KeySet) -> JwksCache:
    """The JWKS exactly as auth-service's route would serve it, over MockTransport."""
    doc = keys.jwks(access_ttl_seconds=900)
    for key in doc["keys"]:
        assert not (wellknown.PRIVATE_JWK_MEMBERS & set(key))

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{ISSUER}/.well-known/jwks.json"
        return httpx.Response(200, json=doc)

    return JwksCache(
        issuer_to_url={ISSUER: f"{ISSUER}/.well-known/jwks.json"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _request(token: str | None) -> Request:
    headers = [(b"host", b"svc.test")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""}
    )


@pytest.fixture(params=SERVICES, ids=[s[0] for s in SERVICES])
def service_current_user(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, issuer):  # noqa: ANN001, ANN201
    _, deps_path, config_path = request.param
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    deps = importlib.import_module(deps_path)
    config = importlib.import_module(config_path)
    monkeypatch.setattr(config.settings, "auth_issuer", ISSUER)
    monkeypatch.setattr(config.settings, "auth_audience", AUDIENCE)
    if hasattr(config.settings, "session_revocation_enabled"):
        monkeypatch.setattr(config.settings, "session_revocation_enabled", False)
    keys, _ = issuer
    cache = _jwks_cache_from(keys)
    state = SimpleNamespace(jwks_cache=cache, app_pool=object(), audit_writer=None)
    # notification-service builds its dependency once in build_state
    # (the others build lazily from state.jwks_cache); mirror that wiring.
    state.current_user_dep = build_current_user(
        jwks_cache=cache, expected_audience=AUDIENCE, expected_issuer=ISSUER
    )
    deps.install_state(state)
    return deps.current_user


@pytest.mark.asyncio
async def test_service_accepts_auth_service_token(service_current_user, issuer) -> None:  # noqa: ANN001
    _, token_service = issuer
    sub, tid = uuid4(), uuid4()
    minted = token_service.mint(
        identity_id=sub, session_id="sid-1", tenant_id=tid, roles=["member"]
    )
    claims = await service_current_user(_request(minted.token), f"Bearer {minted.token}")
    assert (claims.sub, claims.tid, claims.sid, claims.roles) == (sub, tid, "sid-1", ["member"])


@pytest.mark.asyncio
async def test_service_rejects_wrong_audience_and_issuer(service_current_user, issuer) -> None:  # noqa: ANN001
    keys, _ = issuer
    for bad_issuer, bad_aud in ((ISSUER, "someone-else"), ("https://not.our.issuer", AUDIENCE)):
        svc = TokenService(keys=keys, issuer=bad_issuer, audience=bad_aud, access_ttl_seconds=900)
        token = svc.mint(
            identity_id=uuid4(), session_id="s", tenant_id=uuid4(), roles=["member"]
        ).token
        with pytest.raises(HTTPException) as exc:
            await service_current_user(_request(token), f"Bearer {token}")
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_service_rejects_expired_token(service_current_user, issuer) -> None:  # noqa: ANN001
    keys, _ = issuer
    past = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
    svc = TokenService(
        keys=keys, issuer=ISSUER, audience=AUDIENCE, access_ttl_seconds=60, clock=lambda: past
    )
    token = svc.mint(identity_id=uuid4(), session_id="s", tenant_id=uuid4(), roles=["member"]).token
    with pytest.raises(HTTPException) as exc:
        await service_current_user(_request(token), f"Bearer {token}")
    assert exc.value.status_code == 401
