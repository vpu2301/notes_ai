"""IDX-A5 end to end: the real app, real pools, real Redis, real envelope.

The acceptance criteria this file exists to prove:

  * once MFA is on, **no** login path yields a session without a second
    factor;
  * a TOTP code is accepted at most once;
  * changing the email needs a code delivered to the NEW address, and the
    old one gets a link that restores it and ends every session;
  * an identity that is the only owner of a shared workspace cannot
    delete its account.

Requires ``RUN_DB_INTEGRATION=1``, ``make migrate-up``, the dev stack's
Postgres and Redis, and ``infra/dev/master.key``.
"""

from __future__ import annotations

import os
import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and the dev stack",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from auth_service import totp  # noqa: E402

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
DOMAIN = "a5e2e.example"
ORIGIN = {"Origin": "http://localhost:5173"}


def _email() -> str:
    return f"x{uuid.uuid4().hex[:12]}@{DOMAIN}"


@pytest_asyncio.fixture
async def app(monkeypatch: pytest.MonkeyPatch):
    from auth_service.config import settings
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "native")
    monkeypatch.setattr(settings, "auth_signing_keys_file", "infra/dev/auth-signing-dev.json")
    monkeypatch.setattr(settings, "email_provider", "mock")
    monkeypatch.setattr(settings, "auth_issuer_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "master_key_path", "infra/dev/master.key")
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "127.0.0.1/32")

    a = create_app()
    async with (
        httpx.AsyncClient(transport=ASGITransport(app=a), base_url="http://test"),
        a.router.lifespan_context(a),
    ):
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
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        like = f"%@{DOMAIN}"
        ids = "(SELECT id FROM identities WHERE email LIKE $1)"
        for table in (
            "identity_totp",
            "identity_recovery_codes",
            "auth_challenges",
            "auth_sessions",
        ):
            await conn.execute(f"DELETE FROM {table} WHERE identity_id IN {ids}", like)
        await conn.execute(
            f"DELETE FROM users WHERE tenant_id IN (SELECT tenant_id FROM tenant_memberships"
            f" WHERE user_sub IN {ids})",
            like,
        )
        await conn.execute(
            f"DELETE FROM tenants WHERE id IN (SELECT tenant_id FROM tenant_memberships"
            f" WHERE user_sub IN {ids})",
            like,
        )
        await conn.execute("DELETE FROM identities WHERE email LIKE $1", like)
        await conn.close()


# ── helpers ──────────────────────────────────────────────────────────────


def _code_for(app, address: str) -> str:
    for message in reversed(app.state.svc.email_provider.sent):
        if message.to_address == address:
            digits = "".join(ch for ch in message.text_body if ch.isdigit())
            return digits[:6]
    raise AssertionError(f"no mail captured for {address}")


def _kinds_sent(app, address: str) -> list[str]:
    return [m.subject for m in app.state.svc.email_provider.sent if m.to_address == address]


async def _clear_cooldown(email: str) -> None:
    import redis.asyncio as aioredis

    from auth_service.domain.email_code import email_subject_hash

    r = aioredis.from_url("redis://localhost:6379/0", decode_responses=False)
    try:
        keys = [k async for k in r.scan_iter(f"mdx:auth:rl:*:{email_subject_hash(email)}:*")]
        if keys:
            await r.delete(*keys)
    finally:
        await r.aclose()


async def _sign_up(client, app, su, email: str) -> dict:
    """Complete a first-factor sign-in and return the AuthResult body."""
    started = await client.post("/auth/email/start", json={"email": email})
    assert started.status_code == 202, started.text
    body = await client.post(
        "/auth/email/verify",
        json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, email)},
    )
    assert body.status_code == 200, body.text
    await su.execute(
        "UPDATE auth_challenges SET created_at = created_at - interval '5 minutes'"
        " WHERE email = $1",
        email,
    )
    await _clear_cooldown(email)
    return body.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _next_code(secret: str) -> str:
    """A code for the NEXT time step.

    The step that confirmed enrolment is already spent, and the drift
    window means "now" is often still that same step. Real users are
    minutes apart; a test is milliseconds, so it asks for tomorrow's code
    — which the ±1 drift accepts and which carries a higher step.
    """
    import time

    return totp.totp_at(secret, at_unix=time.time() + totp.TOTP_PERIOD_SECONDS)


async def _enrol_mfa(client, app, token: str) -> tuple[str, list[str]]:
    """Step up, enrol TOTP, confirm. Returns ``(secret, recovery_codes)``."""
    enrolled = await client.post("/auth/mfa/totp/enroll", headers=_auth(token))
    assert enrolled.status_code == 200, enrolled.text
    secret = enrolled.json()["secret"]
    confirmed = await client.post(
        "/auth/mfa/totp/confirm",
        json={"enrollment_id": enrolled.json()["enrollment_id"], "code": totp.totp_at(secret)},
        headers=_auth(token),
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


# ── enrolment and the login gate ─────────────────────────────────────────


async def test_enrolment_needs_recent_auth_and_returns_ten_recovery_codes(client, app, su) -> None:
    email = _email()
    session = await _sign_up(client, app, su, email)
    token = session["access_token"]

    secret, codes = await _enrol_mfa(client, app, token)
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(c) == 14 for c in codes)

    identity_id = uuid.UUID(session["identity"]["id"])
    assert await su.fetchval("SELECT mfa_enabled FROM identities WHERE id = $1", identity_id)
    assert "Two-factor" in "".join(_kinds_sent(app, email)) or "Zwei" in "".join(
        _kinds_sent(app, email)
    )
    del secret


async def test_a_stale_session_cannot_enrol(client, app, su) -> None:
    """The step-up gate, seen from the outside."""
    email = _email()
    session = await _sign_up(client, app, su, email)
    # Age the session past the five-minute window.
    await su.execute(
        "UPDATE auth_sessions SET last_authenticated_at = now() - interval '1 hour'"
        " WHERE identity_id = $1",
        uuid.UUID(session["identity"]["id"]),
    )
    refused = await client.post("/auth/mfa/totp/enroll", headers=_auth(session["access_token"]))
    assert refused.status_code == 403
    assert refused.json()["code"] == "reauth_required"


async def test_step_up_by_emailed_code_unlocks_the_gate(client, app, su) -> None:
    email = _email()
    session = await _sign_up(client, app, su, email)
    token = session["access_token"]
    await su.execute(
        "UPDATE auth_sessions SET last_authenticated_at = now() - interval '1 hour'"
        " WHERE identity_id = $1",
        uuid.UUID(session["identity"]["id"]),
    )

    started = await client.post("/auth/reauth/start", headers=_auth(token))
    assert started.status_code == 200
    assert started.json()["methods"] == ["email_code"]
    done = await client.post(
        "/auth/reauth",
        json={
            "method": "email_code",
            "code": _code_for(app, email),
            "challenge_id": started.json()["challenge_id"],
        },
        headers=_auth(token),
    )
    assert done.status_code == 204
    # The gate is open again.
    assert (await client.post("/auth/mfa/totp/enroll", headers=_auth(token))).status_code == 200


async def test_once_mfa_is_on_the_email_code_path_yields_no_session(client, app, su) -> None:
    """The sprint's headline acceptance criterion."""
    email = _email()
    session = await _sign_up(client, app, su, email)
    secret, codes = await _enrol_mfa(client, app, session["access_token"])

    started = await client.post("/auth/email/start", json={"email": email})
    assert started.status_code == 202
    result = await client.post(
        "/auth/email/verify",
        json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, email)},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "mfa_required"
    assert not body["access_token"], "a first factor alone must not mint a token"
    assert body["challenge_id"]
    assert set(body["methods"]) == {"totp", "recovery_code"}
    # And it discloses nothing about the account on the way.
    assert body["identity"] is None
    assert body["memberships"] == []

    finished = await client.post(
        "/auth/mfa/verify",
        json={
            "challenge_id": body["challenge_id"],
            "method": "totp",
            "code": _next_code(secret),
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "authenticated"
    assert finished.json()["access_token"]
    del codes


async def test_a_totp_code_is_accepted_at_most_once(client, app, su) -> None:
    email = _email()
    session = await _sign_up(client, app, su, email)
    secret, _ = await _enrol_mfa(client, app, session["access_token"])
    code = _next_code(secret)

    async def _challenge() -> str:
        started = await client.post("/auth/email/start", json={"email": email})
        assert started.status_code == 202, started.text
        verified = await client.post(
            "/auth/email/verify",
            json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, email)},
        )
        await su.execute(
            "UPDATE auth_challenges SET created_at = created_at - interval '5 minutes'"
            " WHERE email = $1",
            email,
        )
        await _clear_cooldown(email)
        return verified.json()["challenge_id"]

    first = await client.post(
        "/auth/mfa/verify",
        json={"challenge_id": await _challenge(), "method": "totp", "code": code},
    )
    assert first.status_code == 200

    second = await client.post(
        "/auth/mfa/verify",
        json={"challenge_id": await _challenge(), "method": "totp", "code": code},
    )
    assert second.status_code == 400
    assert second.json()["code"] == "code_invalid"


async def test_the_code_that_confirmed_enrolment_cannot_also_sign_you_in(client, app, su) -> None:
    """Step accounting does not care that the two uses are different acts.

    A code proves possession of the device for one time step, and that
    step is spent by whatever used it first. Someone watching an enrolment
    over a shoulder cannot turn the code they saw into a session.
    """
    email = _email()
    session = await _sign_up(client, app, su, email)
    enrolled = await client.post("/auth/mfa/totp/enroll", headers=_auth(session["access_token"]))
    secret = enrolled.json()["secret"]
    confirm_code = totp.totp_at(secret)
    confirmed = await client.post(
        "/auth/mfa/totp/confirm",
        json={"enrollment_id": enrolled.json()["enrollment_id"], "code": confirm_code},
        headers=_auth(session["access_token"]),
    )
    assert confirmed.status_code == 200

    started = await client.post("/auth/email/start", json={"email": email})
    challenged = await client.post(
        "/auth/email/verify",
        json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, email)},
    )
    replayed = await client.post(
        "/auth/mfa/verify",
        json={
            "challenge_id": challenged.json()["challenge_id"],
            "method": "totp",
            "code": confirm_code,
        },
    )
    assert replayed.status_code == 400
    assert replayed.json()["code"] == "code_invalid"


async def test_a_recovery_code_works_once_and_reports_what_is_left(client, app, su) -> None:
    email = _email()
    session = await _sign_up(client, app, su, email)
    _, codes = await _enrol_mfa(client, app, session["access_token"])

    started = await client.post("/auth/email/start", json={"email": email})
    challenged = await client.post(
        "/auth/email/verify",
        json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, email)},
    )
    used = await client.post(
        "/auth/mfa/verify",
        json={
            "challenge_id": challenged.json()["challenge_id"],
            "method": "recovery_code",
            "code": codes[0],
        },
    )
    assert used.status_code == 200, used.text
    assert used.json()["recovery_codes_left"] == 9
    assert used.json()["recovery_codes_exhausted"] is False

    await su.execute(
        "UPDATE auth_challenges SET created_at = created_at - interval '5 minutes'"
        " WHERE email = $1",
        email,
    )
    await _clear_cooldown(email)
    started = await client.post("/auth/email/start", json={"email": email})
    challenged = await client.post(
        "/auth/email/verify",
        json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, email)},
    )
    reused = await client.post(
        "/auth/mfa/verify",
        json={
            "challenge_id": challenged.json()["challenge_id"],
            "method": "recovery_code",
            "code": codes[0],
        },
    )
    assert reused.status_code == 400
    assert reused.json()["code"] == "code_invalid"


# ── sessions ─────────────────────────────────────────────────────────────


async def test_the_sessions_list_masks_ips_and_marks_the_current_one(client, app, su) -> None:
    email = _email()
    session = await _sign_up(client, app, su, email)
    listed = await client.get("/auth/sessions", headers=_auth(session["access_token"]))
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["current"] is True
    assert rows[0]["ip_last"].endswith("/24")
    assert rows[0]["ip_last"].endswith(".0/24"), "the host octet is not shown"


async def test_deleting_someone_elses_session_is_a_404(client, app, su) -> None:
    mine = await _sign_up(client, app, su, _email())
    theirs = await _sign_up(client, app, su, _email())
    their_sid = (await client.get("/auth/sessions", headers=_auth(theirs["access_token"]))).json()[
        0
    ]["sid"]

    refused = await client.delete(
        f"/auth/sessions/{their_sid}", headers=_auth(mine["access_token"])
    )
    assert refused.status_code == 404
    still_there = await client.get("/auth/sessions", headers=_auth(theirs["access_token"]))
    assert len(still_there.json()) == 1


# ── email change ─────────────────────────────────────────────────────────


async def test_the_email_change_needs_a_code_sent_to_the_new_address(client, app, su) -> None:
    old = _email()
    new = _email()
    session = await _sign_up(client, app, su, old)
    token = session["access_token"]

    started = await client.post(
        "/auth/email/change/start", json={"new_email": new}, headers=_auth(token)
    )
    assert started.status_code == 202, started.text
    # The code went to the NEW address, and only there.
    assert _code_for(app, new)

    confirmed = await client.post(
        "/auth/email/change/confirm",
        json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, new)},
        headers=_auth(token),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["email"] == new
    assert (
        await su.fetchval(
            "SELECT email FROM identities WHERE id = $1", uuid.UUID(session["identity"]["id"])
        )
        == new
    )


async def test_the_old_address_can_undo_the_change_and_everything_is_revoked(
    client, app, su
) -> None:
    old = _email()
    new = _email()
    session = await _sign_up(client, app, su, old)
    token = session["access_token"]
    identity_id = uuid.UUID(session["identity"]["id"])

    started = await client.post(
        "/auth/email/change/start", json={"new_email": new}, headers=_auth(token)
    )
    await client.post(
        "/auth/email/change/confirm",
        json={"challenge_id": started.json()["challenge_id"], "code": _code_for(app, new)},
        headers=_auth(token),
    )

    # The notice to the OLD address carries the revert link, and does not
    # spell out where the account went.
    notice = [m for m in app.state.svc.email_provider.sent if m.to_address == old][-1]
    assert "/auth/email/revert/" in notice.text_body
    assert new not in notice.text_body
    link = [w for w in notice.text_body.split() if "/auth/email/revert/" in w][0]
    token_part = link.rsplit("/", 1)[1]

    reverted = await client.get(f"/auth/email/revert/{token_part}")
    assert reverted.status_code == 200
    assert "text/html" in reverted.headers["content-type"]
    assert await su.fetchval("SELECT email FROM identities WHERE id = $1", identity_id) == old
    # Every session is gone, including the one that made the change.
    assert (
        await su.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE identity_id = $1 AND revoked_at IS NULL",
            identity_id,
        )
        == 0
    )

    # The link is single use.
    again = await client.get(f"/auth/email/revert/{token_part}")
    assert again.status_code == 404


async def test_changing_to_an_address_already_in_use_is_refused(client, app, su) -> None:
    taken = _email()
    await _sign_up(client, app, su, taken)
    session = await _sign_up(client, app, su, _email())
    refused = await client.post(
        "/auth/email/change/start",
        json={"new_email": taken},
        headers=_auth(session["access_token"]),
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "email_in_use"


# ── deletion ─────────────────────────────────────────────────────────────


async def test_deleting_needs_the_confirm_word_and_schedules_a_purge(client, app, su) -> None:
    email = _email()
    session = await _sign_up(client, app, su, email)
    token = session["access_token"]

    typo = await client.post(
        "/auth/account/delete", json={"confirm": "delete"}, headers=_auth(token)
    )
    assert typo.status_code == 400
    assert typo.json()["code"] == "confirm_required"

    done = await client.post(
        "/auth/account/delete", json={"confirm": "DELETE"}, headers=_auth(token)
    )
    assert done.status_code == 202, done.text
    assert done.json()["workspaces_dissolved"] == 1

    identity_id = uuid.UUID(session["identity"]["id"])
    assert (
        await su.fetchval("SELECT status FROM identities WHERE id = $1", identity_id)
        == "pending_deletion"
    )
    # Signed out everywhere, the caller included.
    assert (
        await su.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE identity_id = $1 AND revoked_at IS NULL",
            identity_id,
        )
        == 0
    )


async def test_signing_in_during_the_grace_period_undoes_the_deletion(client, app, su) -> None:
    email = _email()
    session = await _sign_up(client, app, su, email)
    await client.post(
        "/auth/account/delete",
        json={"confirm": "DELETE"},
        headers=_auth(session["access_token"]),
    )
    identity_id = uuid.UUID(session["identity"]["id"])

    back = await _sign_up(client, app, su, email)
    assert back["status"] == "authenticated"
    assert await su.fetchval("SELECT status FROM identities WHERE id = $1", identity_id) == "active"
    assert (
        await su.fetchval("SELECT deletion_requested_at FROM identities WHERE id = $1", identity_id)
        is None
    )


async def test_the_sole_owner_of_a_shared_workspace_cannot_delete(client, app, su) -> None:
    owner = await _sign_up(client, app, su, _email())
    colleague = await _sign_up(client, app, su, _email())
    await su.execute(
        "INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)"
        " VALUES ($1, $2, 'member', 'active')",
        uuid.UUID(owner["tenant_id"]),
        uuid.UUID(colleague["identity"]["id"]),
    )

    refused = await client.post(
        "/auth/account/delete",
        json={"confirm": "DELETE"},
        headers=_auth(owner["access_token"]),
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "sole_owner_with_members"
    assert refused.json()["tenants"][0]["tenant_id"] == owner["tenant_id"]


# ── profile ──────────────────────────────────────────────────────────────


async def test_the_profile_can_be_patched_without_a_step_up(client, app, su) -> None:
    session = await _sign_up(client, app, su, _email())
    await su.execute(
        "UPDATE auth_sessions SET last_authenticated_at = now() - interval '1 hour'"
        " WHERE identity_id = $1",
        uuid.UUID(session["identity"]["id"]),
    )
    patched = await client.patch(
        "/auth/me",
        json={"display_name": "Ada Lovelace", "locale": "de"},
        headers=_auth(session["access_token"]),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "Ada Lovelace"
    assert (
        await su.fetchval(
            "SELECT locale FROM identities WHERE id = $1", uuid.UUID(session["identity"]["id"])
        )
        == "de"
    )
