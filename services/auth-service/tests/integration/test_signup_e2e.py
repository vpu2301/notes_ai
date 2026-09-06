"""BE-0 end to end: the real Keycloak, the real pools, the real Redis.

Nothing is faked except the SMTP relay, and that is the ``mock`` provider
the service already ships — so the rendering and the address the mail is
bound for are the production path too.

What this proves that the unit suite cannot: that a Keycloak user created
with a password and **no required actions** can actually complete the
password grant. That single line in ``create_user_with_password`` is the
difference between a working signup and one where every new account is
told "Account is not fully set up" on its first sign-in, and it cannot be
tested against a fake — the fake does not implement Keycloak's rule.

Requires: ``RUN_DB_INTEGRATION=1``, ``RUN_KEYCLOAK_INTEGRATION=1``,
``make dev-up``, ``make migrate-up``.
"""

from __future__ import annotations

import contextlib
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1"
    or os.environ.get("RUN_KEYCLOAK_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 + RUN_KEYCLOAK_INTEGRATION=1 + the dev stack",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
DOMAIN = "be0e2e.example"
ORIGIN = {"Origin": "http://localhost:5173"}
PASSWORD = "correct-horse-battery-staple-9"


def _email() -> str:
    return f"e{uuid.uuid4().hex[:12]}@{DOMAIN}"


@pytest_asyncio.fixture
async def app(monkeypatch: pytest.MonkeyPatch):
    from auth_service.config import settings
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "keycloak")
    monkeypatch.setattr(settings, "signup_enabled", True)
    monkeypatch.setattr(settings, "email_provider", "mock")
    # Each test presents its own client address so the per-IP cap (5/h) is
    # per test rather than shared with every other run against this Redis.
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "127.0.0.1/32")

    a = create_app()
    async with a.router.lifespan_context(a):
        yield a


@pytest_asyncio.fixture
async def client(app):
    caller = f"198.51.100.{uuid.uuid4().int % 254 + 1}"
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 5000)),
        base_url="http://test",
        headers={**ORIGIN, "X-Forwarded-For": caller},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def su(app):
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        like = f"%@{DOMAIN}"
        # Keycloak first, while we can still read the subs out of Postgres.
        subs = [
            r["sub"] for r in await conn.fetch("SELECT sub FROM users WHERE email LIKE $1", like)
        ]
        for sub in subs:
            with contextlib.suppress(Exception):  # cleanup is best effort
                await app.state.svc.keycloak.delete_user(sub)
        for statement in (
            "DELETE FROM auth_challenges WHERE email LIKE $1",
            "DELETE FROM users WHERE email LIKE $1",
            "DELETE FROM tenant_memberships WHERE user_sub IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            "DELETE FROM tenants WHERE id IN (SELECT last_tenant_id FROM identities"
            " WHERE email LIKE $1 AND last_tenant_id IS NOT NULL)",
            "DELETE FROM identities WHERE email LIKE $1",
        ):
            await conn.execute(statement, like)
        await conn.close()


def _code(app, to: str) -> str:
    for message in reversed(app.state.svc.email_provider.sent):
        if message.to_address == to:
            digits = "".join(ch for ch in message.text_body if ch.isdigit())
            assert len(digits) >= 6, "the mail carried no code"
            return digits[:6]
    raise AssertionError(f"no mail captured for {to}")


async def test_signup_verify_then_login_returns_a_usable_token(app, client, su) -> None:
    """The whole point of BE-0, in one test.

    The `roles` assertion is not decoration. `tenant_admin` alone holds no
    content permission at all (S14), so an account with only that role
    signs in successfully and then gets 403 on the first note it tries to
    write — a failure that looks like a note-service bug and is not.
    """
    email = _email()

    started = await client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "display_name": "Ada Lovelace"},
    )
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "verification_sent"

    # Before confirmation the account is disabled in Keycloak, so no grant
    # of any kind can produce a token.
    early = await client.post(
        "/auth/login", json={"username": email, "password": PASSWORD}
    )
    assert early.status_code == 403, early.text
    assert early.json()["code"] == "email_not_verified"

    verified = await client.post(
        "/auth/signup/verify", json={"email": email, "code": _code(app, email)}
    )
    assert verified.status_code == 200, verified.text

    logged_in = await client.post(
        "/auth/login", json={"username": email, "password": PASSWORD}
    )
    assert logged_in.status_code == 200, logged_in.text
    body = logged_in.json()
    assert body["access_token"]

    from jose import jwt

    claims = jwt.get_unverified_claims(body["access_token"])
    # A superset: Keycloak also puts its own realm defaults in the claim
    # (`default-roles-notes`, `offline_access`, `uma_authorization`), and
    # those are not ours to assert on.
    assert {"tenant_admin", "member"} <= set(claims["roles"]), (
        "a new account must be able to write in its own workspace; "
        "tenant_admin alone holds no content permission (docs/auth/roles.md)"
    )
    # `tid` is the claim every service filters rows by. It reaches the
    # token through the `tenant_id` user attribute, which Keycloak's
    # declarative user profile drops unless the realm declares it — see
    # the userProfile component in infra/keycloak/realm-export.json.
    assert claims.get("tid"), "no tid claim: is `tenant_id` declared on the realm user profile?"

    tenant_id = await su.fetchval("SELECT tenant_id FROM users WHERE email = $1", email)
    assert claims["tid"] == str(tenant_id)
    assert await su.fetchval("SELECT status FROM users WHERE email = $1", email) == "active"
    assert await su.fetchval(
        "SELECT kind FROM tenants WHERE id = $1", tenant_id
    ) == "personal"
    # The bridge row and the identity go together: without the identity
    # `/auth/me` cannot describe the person, and BE-3's code login later
    # cannot find them.
    assert await su.fetchval("SELECT count(*) FROM identities WHERE email = $1", email) == 1


async def test_a_second_signup_with_the_same_address_creates_nothing(app, client, su) -> None:
    email = _email()
    first = await client.post(
        "/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Ada"}
    )
    assert first.status_code == 202

    before = len(app.state.svc.email_provider.sent)
    second = await client.post(
        "/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Ada"}
    )
    assert second.status_code == first.status_code
    assert second.json() == first.json()

    assert await su.fetchval("SELECT count(*) FROM users WHERE email = $1", email) == 1
    # One mail either way — the branches differ only in what it says.
    assert len(app.state.svc.email_provider.sent) == before + 1
    latest = app.state.svc.email_provider.sent[-1]
    assert "already" in latest.text_body.lower() or "bereits" in latest.text_body.lower()


async def test_the_created_keycloak_user_has_no_pending_required_actions(
    app, client, su
) -> None:
    """The single line this whole flow rests on.

    ``create_user`` (the admin-invite path) sets
    ``requiredActions: ["UPDATE_PASSWORD"]``, and a pending required
    action makes the password grant refuse with "Account is not fully set
    up". A signup that inherited it would create accounts nobody could
    ever sign in to, and the error would point at the password.
    """
    email = _email()
    await client.post(
        "/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Ada"}
    )
    sub = await su.fetchval("SELECT sub FROM users WHERE email = $1", email)
    user = await app.state.svc.keycloak.get_user(sub)
    assert user.get("requiredActions") in ([], None)
    assert user["enabled"] is False
    assert user["emailVerified"] is False


async def test_verification_enables_the_account_in_keycloak(app, client, su) -> None:
    email = _email()
    await client.post(
        "/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Ada"}
    )
    await client.post("/auth/signup/verify", json={"email": email, "code": _code(app, email)})

    sub = await su.fetchval("SELECT sub FROM users WHERE email = $1", email)
    user = await app.state.svc.keycloak.get_user(sub)
    assert user["enabled"] is True
    assert user["emailVerified"] is True


async def test_a_wrong_code_five_times_then_a_resend_works(app, client, su) -> None:
    email = _email()
    await client.post(
        "/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Ada"}
    )
    real = _code(app, email)
    wrong = "000000" if real != "000000" else "111111"

    for _ in range(4):
        assert (
            await client.post("/auth/signup/verify", json={"email": email, "code": wrong})
        ).status_code == 400
    fifth = await client.post("/auth/signup/verify", json={"email": email, "code": wrong})
    assert fifth.status_code == 429
    assert fifth.json()["code"] == "too_many_attempts"

    assert (
        await client.post("/auth/signup/resend", json={"email": email})
    ).status_code == 202
    assert (
        await client.post(
            "/auth/signup/verify", json={"email": email, "code": _code(app, email)}
        )
    ).status_code == 200


async def test_the_api_refuses_what_the_realm_would_refuse(client) -> None:
    response = await client.post(
        "/auth/signup",
        json={"email": _email(), "password": "short", "display_name": "Ada"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "password_policy"
    assert response.json()["min_length"] == 12


async def test_the_concierge_path_onboards_without_a_code(app, su) -> None:
    """OPS-0's CLI, exercised through the service the CLI calls.

    The account is active immediately and login works — no confirmation
    mail is sent, because the operator vouched for the address.
    """
    from auth_service.domain.onboarding_service import generate_password

    email = _email()
    password = generate_password()
    service = app.state.svc.onboarding_service
    account = await service.create_account(
        email=email,
        password=password,
        display_name="Ada Lovelace",
        source="concierge",
        verified=True,
    )

    assert await su.fetchval("SELECT status FROM users WHERE sub = $1", account.sub) == "active"
    user = await app.state.svc.keycloak.get_user(account.sub)
    assert user["enabled"] is True

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 5000)),
        base_url="http://test",
        headers={**ORIGIN, "X-Forwarded-For": "198.51.100.7"},
    ) as c:
        logged_in = await c.post(
            "/auth/login", json={"username": email, "password": password}
        )
    assert logged_in.status_code == 200, logged_in.text
