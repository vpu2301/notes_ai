"""IDX-B1b end to end: the OAuth endpoint as a device actually speaks it.

Form-encoded, HTTP Basic, `Cache-Control: no-store`, RFC 6749 error
bodies — the wire details that decide whether a room device can be
re-pointed by changing one URL.

Includes the seeded dev device, whose secret is the same string the
Keycloak realm uses, so this proves the "dev configs need no change"
claim rather than asserting it.

Requires ``RUN_DB_INTEGRATION=1``, ``make migrate-up``, ``make seed``,
and the dev stack's Postgres and Redis.
"""

from __future__ import annotations

import os
import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and the dev stack",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
TENANT_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
DEV_DEVICE_ID = "0000000d-0000-0000-0000-00000000d0e1"
DEV_DEVICE_SECRET = "dev-room-device-secret"  # noqa: S105 — dev realm parity
MARK = "b1be2e"


@pytest_asyncio.fixture
async def app(monkeypatch: pytest.MonkeyPatch):
    from auth_service.config import settings
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "native")
    monkeypatch.setattr(settings, "auth_signing_keys_file", "infra/dev/auth-signing-dev.json")
    monkeypatch.setattr(settings, "email_provider", "mock")
    monkeypatch.setattr(settings, "auth_issuer_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "master_key_path", "infra/dev/master.key")

    a = create_app()
    async with (
        httpx.AsyncClient(transport=ASGITransport(app=a), base_url="http://test"),
        a.router.lifespan_context(a),
    ):
        yield a


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 5000)),
        base_url="http://test",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        await conn.execute("DELETE FROM service_credentials WHERE name LIKE $1", f"%{MARK}%")
        await conn.close()


@pytest_asyncio.fixture(autouse=True)
async def _clear_lock():
    import redis.asyncio as aioredis

    r = aioredis.from_url("redis://localhost:6379/0", decode_responses=False)
    try:
        keys = [k async for k in r.scan_iter("mdx:auth:*client*")]
        if keys:
            await r.delete(*keys)
        yield
    finally:
        await r.aclose()


async def _make_device(app, su, name: str) -> tuple[str, str]:
    """Create a device straight through the service, bypassing the routes."""
    svc = app.state.svc.account_services.credentials
    created = await svc.create(
        kind="device", tenant_id=TENANT_A, name=f"{MARK}-{name}", created_by=None
    )
    del su
    return str(created.credential.id), created.secret


# ── the wire format ──────────────────────────────────────────────────────


async def test_the_seeded_dev_device_gets_a_token_with_its_keycloak_secret(client, su) -> None:
    """The "dev configs need no change" claim, proven rather than asserted."""
    response = await client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": DEV_DEVICE_ID,
            "client_secret": DEV_DEVICE_SECRET,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    assert "refresh_token" not in body

    claims = jwt.get_unverified_claims(body["access_token"])
    assert claims["roles"] == ["device"]
    assert claims["tid"] == str(TENANT_A)
    assert claims["sub"] == DEV_DEVICE_ID
    assert claims["aud"] == "mdx-api"

    # RFC 6749 §5.1 — a token response must not be cached anywhere.
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


async def test_http_basic_works_because_that_is_what_keycloak_clients_send(client, app, su) -> None:
    client_id, secret = await _make_device(app, su, "basic")
    response = await client.post(
        "/auth/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, secret),
    )
    assert response.status_code == 200, response.text
    assert jwt.get_unverified_claims(response.json()["access_token"])["sub"] == client_id


async def test_a_wrong_secret_answers_rfc6749_invalid_client(client, app, su) -> None:
    client_id, _ = await _make_device(app, su, "wrong")
    response = await client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": "mdx_sk_deadbeef_" + "z" * 43,
        },
    )
    assert response.status_code == 401
    body = response.json()
    # Both vocabularies: `error` for a stock OAuth client library, `code`
    # for everything else in this API.
    assert body["error"] == "invalid_client"
    assert body["code"] == "invalid_client"
    assert "WWW-Authenticate" in response.headers


async def test_an_unknown_client_is_indistinguishable_from_a_wrong_secret(client, app, su) -> None:
    client_id, secret = await _make_device(app, su, "unknown")
    wrong_secret = await client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": "mdx_sk_deadbeef_" + "q" * 43,
        },
    )
    unknown_client = await client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": str(uuid.uuid4()),
            "client_secret": secret,
        },
    )
    assert wrong_secret.status_code == unknown_client.status_code == 401
    assert wrong_secret.json() | {"instance": ""} == unknown_client.json() | {"instance": ""}


async def test_another_grant_type_is_refused(client) -> None:
    response = await client.post(
        "/auth/oauth/token",
        data={"grant_type": "password", "client_id": "x", "client_secret": "y" * 20},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


async def test_missing_credentials_are_a_400_not_a_401(client) -> None:
    response = await client.post("/auth/oauth/token", data={"grant_type": "client_credentials"})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


# ── lock ─────────────────────────────────────────────────────────────────


async def test_ten_wrong_secrets_lock_the_client_over_http(client, app, su) -> None:
    client_id, secret = await _make_device(app, su, "lock")
    bad = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": "mdx_sk_deadbeef_" + "w" * 43,
    }
    for _ in range(10):
        assert (await client.post("/auth/oauth/token", data=bad)).status_code == 401

    locked = await client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
        },
    )
    assert locked.status_code == 423
    assert locked.json()["code"] == "client_locked"
    assert locked.headers["Retry-After"] == "900"


async def test_the_lock_is_per_client_not_global(client, app, su) -> None:
    """One noisy room must not take the whole estate offline."""
    locked_id, _ = await _make_device(app, su, "noisy")
    other_id, other_secret = await _make_device(app, su, "quiet")
    for _ in range(10):
        await client.post(
            "/auth/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": locked_id,
                "client_secret": "mdx_sk_deadbeef_" + "e" * 43,
            },
        )
    ok = await client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": other_id,
            "client_secret": other_secret,
        },
    )
    assert ok.status_code == 200


# ── revocation reaches a live token ──────────────────────────────────────


async def test_revoking_pushes_the_credential_onto_the_denylist(app, su) -> None:
    """The DB row stops the next grant; the denylist stops the token the
    device is already holding. Only both make revocation immediate."""
    pushed: list[str] = []

    class FakeDenylist:
        async def revoke_sub(self, sub: str, *, ttl_seconds: int) -> None:
            pushed.append(sub)

    svc = app.state.svc.account_services.credentials
    created = await svc.create(
        kind="device", tenant_id=TENANT_A, name=f"{MARK}-revoke", created_by=None
    )
    svc._denylist = FakeDenylist()  # noqa: SLF001 — asserting the wiring
    await svc.revoke(created.credential.id)
    assert pushed == [str(created.credential.id)]
    del su


# ── the endpoint does not exist under Keycloak ───────────────────────────


async def test_the_oauth_endpoint_is_native_mode_only(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    from auth_service.config import settings
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "keycloak")
    paths = {r.path for r in create_app().routes}  # type: ignore[attr-defined]
    assert "/auth/oauth/token" not in paths
    assert "/admin/credentials" not in paths
