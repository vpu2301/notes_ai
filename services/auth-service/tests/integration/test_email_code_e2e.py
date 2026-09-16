"""IDX-A3 end to end: the real app, the real pools, the real Redis.

Nothing is faked except the SMTP relay — and that is the `mock` provider
the service already ships, so even the rendering and the address the mail
is bound for are the production path. What this proves that the other two
suites cannot: the wiring. Config → pools → repositories → limiter →
mailer → router, in native mode, exactly as a deployment builds it.

Requires: ``RUN_DB_INTEGRATION=1``, ``make migrate-up``, and the dev
stack's Postgres and Redis.
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
    reason="needs RUN_DB_INTEGRATION=1 and the dev stack (Postgres + Redis)",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
DOMAIN = "a3e2e.example"
ORIGIN = {"Origin": "http://localhost:5173"}


def _email() -> str:
    return f"e{uuid.uuid4().hex[:12]}@{DOMAIN}"


@pytest_asyncio.fixture
async def app(monkeypatch: pytest.MonkeyPatch):
    from auth_service.config import settings
    from auth_service.main import create_app

    # A deployment in native mode with the dev signing key and the
    # in-memory mail provider — the compose defaults for everything else.
    monkeypatch.setattr(settings, "idp_mode", "native")
    monkeypatch.setattr(settings, "auth_signing_keys_file", "infra/dev/auth-signing-dev.json")
    monkeypatch.setattr(settings, "email_provider", "mock")
    monkeypatch.setattr(settings, "auth_issuer_url", "http://localhost:8000")
    # Believe X-Forwarded-For from the ASGI transport's loopback peer, so
    # each test can present its own client address. Without this every
    # test shares one per-IP bucket in the dev Redis — which is the
    # correct production behaviour and a guaranteed flake here, since the
    # 20/hour cap outlives any single run.
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "127.0.0.1/32")

    a = create_app()
    async with (
        httpx.AsyncClient(transport=ASGITransport(app=a), base_url="http://test"),
        a.router.lifespan_context(a),
    ):
        yield a


@pytest_asyncio.fixture
async def client(app):
    """A client with its own address, so per-IP caps are per-test."""
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    caller = f"198.51.100.{uuid.uuid4().int % 254 + 1}"
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={**ORIGIN, "X-Forwarded-For": caller},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        like = f"%@{DOMAIN}"
        await conn.execute("DELETE FROM auth_challenges WHERE email LIKE $1", like)
        await conn.execute(
            "DELETE FROM auth_sessions WHERE identity_id IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            like,
        )
        await conn.execute(
            "DELETE FROM users WHERE tenant_id IN (SELECT tenant_id FROM tenant_memberships"
            " WHERE user_sub IN (SELECT id FROM identities WHERE email LIKE $1))",
            like,
        )
        await conn.execute(
            "DELETE FROM tenants WHERE id IN (SELECT tenant_id FROM tenant_memberships"
            " WHERE user_sub IN (SELECT id FROM identities WHERE email LIKE $1))",
            like,
        )
        await conn.execute("DELETE FROM identities WHERE email LIKE $1", like)
        await conn.close()


def _captured_code(app, to_address: str) -> str:
    """Pull the six digits out of the mail the mock provider captured."""
    provider = app.state.svc.email_provider
    for message in reversed(provider.sent):
        if message.to_address == to_address:
            digits = "".join(ch for ch in message.text_body if ch.isdigit())
            assert len(digits) >= 6, "the mail carried no code"
            return digits[:6]
    raise AssertionError(f"no mail was captured for {to_address}")


async def test_a_brand_new_address_signs_up_and_gets_a_workspace_token(app, client, su) -> None:
    email = _email()
    personal_before = await su.fetchval("SELECT count(*) FROM tenants WHERE kind = 'personal'")

    started = await client.post("/auth/email/start", json={"email": email}, headers=ORIGIN)
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["expires_in"] == 600
    assert body["resend_after"] == 60

    code = _captured_code(app, email)
    verified = await client.post(
        "/auth/email/verify",
        json={"challenge_id": body["challenge_id"], "code": code},
        headers=ORIGIN,
    )
    assert verified.status_code == 200, verified.text
    result = verified.json()

    assert result["status"] == "authenticated"
    assert result["is_new_identity"] is True
    assert result["identity"]["email"] == email
    assert result["memberships"][0]["kind"] == "personal"
    assert result["memberships"][0]["role"] == "owner"
    # Web client: the refresh token rides the cookie, not the body.
    assert result["refresh_token"] is None
    assert "mdx_rt" in verified.cookies

    claims = jwt.get_unverified_claims(result["access_token"])
    assert claims["tid"] == result["tenant_id"]
    assert claims["iss"] == "http://localhost:8000"
    assert claims["aud"] == "mdx-api"
    # `tenant_admin` AND `member`, because whoever owns a workspace also
    # works in it. S14's admin/content separation gives `tenant_admin` no
    # content permission at all, so the first token of every self-serve
    # account used to be one that could not write a note, submit an ASR
    # job or dictate — `403 deny: roles=['tenant_admin'] cannot
    # 'asr.write'` on the first thing the person tried
    # (docs/auth/roles.md § "a person who administers a workspace and
    # takes notes holds both").
    assert claims["roles"] == ["tenant_admin", "member"]
    assert claims["email"] == email

    # Exactly one personal workspace was created, and the session is real.
    personal_after = await su.fetchval("SELECT count(*) FROM tenants WHERE kind = 'personal'")
    assert personal_after == personal_before + 1
    assert await su.fetchval(
        "SELECT count(*) FROM auth_sessions WHERE id = $1 AND tenant_id = $2",
        uuid.UUID(claims["sid"]),
        uuid.UUID(result["tenant_id"]),
    )
    # The challenge is spent.
    assert await su.fetchval(
        "SELECT consumed_at IS NOT NULL FROM auth_challenges WHERE id = $1",
        uuid.UUID(body["challenge_id"]),
    )


async def test_the_second_sign_in_reuses_the_workspace_and_makes_no_new_one(
    app, client, su
) -> None:
    email = _email()
    first = await client.post("/auth/email/start", json={"email": email}, headers=ORIGIN)
    first_result = await client.post(
        "/auth/email/verify",
        json={
            "challenge_id": first.json()["challenge_id"],
            "code": _captured_code(app, email),
        },
        headers=ORIGIN,
    )
    tenant_id = first_result.json()["tenant_id"]

    # The 60-second resend cooldown is real, so age the row rather than wait.
    await su.execute(
        "UPDATE auth_challenges SET created_at = created_at - interval '5 minutes'"
        " WHERE email = $1",
        email,
    )
    await _clear_cooldown(email)

    second = await client.post("/auth/email/start", json={"email": email}, headers=ORIGIN)
    assert second.status_code == 202
    second_result = await client.post(
        "/auth/email/verify",
        json={
            "challenge_id": second.json()["challenge_id"],
            "code": _captured_code(app, email),
        },
        headers=ORIGIN,
    )
    assert second_result.status_code == 200
    assert second_result.json()["is_new_identity"] is False
    assert second_result.json()["tenant_id"] == tenant_id
    assert (
        await su.fetchval("SELECT count(*) FROM tenants WHERE id = $1", uuid.UUID(tenant_id)) == 1
    )
    # A new session every time — the sid is never reused.
    claims_1 = jwt.get_unverified_claims(first_result.json()["access_token"])
    claims_2 = jwt.get_unverified_claims(second_result.json()["access_token"])
    assert claims_1["sid"] != claims_2["sid"]


async def test_start_looks_the_same_for_a_known_and_an_unknown_address(app, client, su) -> None:
    known = _email()
    first = await client.post("/auth/email/start", json={"email": known}, headers=ORIGIN)
    await client.post(
        "/auth/email/verify",
        json={
            "challenge_id": first.json()["challenge_id"],
            "code": _captured_code(app, known),
        },
        headers=ORIGIN,
    )
    await su.execute(
        "UPDATE auth_challenges SET created_at = created_at - interval '5 minutes'"
        " WHERE email = $1",
        known,
    )
    await _clear_cooldown(known)

    unknown = _email()
    a = await client.post("/auth/email/start", json={"email": known}, headers=ORIGIN)
    b = await client.post("/auth/email/start", json={"email": unknown}, headers=ORIGIN)

    assert a.status_code == b.status_code == 202
    assert set(a.json()) == set(b.json())
    assert a.json()["expires_in"] == b.json()["expires_in"]
    assert a.json()["resend_after"] == b.json()["resend_after"]
    # Both addresses received a code — the unknown one because that is
    # how it signs up.
    assert _captured_code(app, known)
    assert _captured_code(app, unknown)


async def test_a_wrong_code_reports_the_attempts_left(app, client) -> None:
    email = _email()
    started = await client.post("/auth/email/start", json={"email": email}, headers=ORIGIN)
    real = _captured_code(app, email)
    wrong = "000000" if real != "000000" else "111111"
    response = await client.post(
        "/auth/email/verify",
        json={"challenge_id": started.json()["challenge_id"], "code": wrong},
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "code_invalid"
    assert response.json()["attempts_left"] == 4


async def _clear_cooldown(email: str) -> None:
    """Drop the Redis half of the resend cooldown for one address."""
    import redis.asyncio as aioredis

    from auth_service.domain.email_code import email_subject_hash

    client = aioredis.from_url("redis://localhost:6379/0", decode_responses=False)
    try:
        subject = email_subject_hash(email)
        keys = [k async for k in client.scan_iter(f"mdx:auth:rl:otp_cooldown:{subject}:*")]
        if keys:
            await client.delete(*keys)
    finally:
        await client.aclose()
