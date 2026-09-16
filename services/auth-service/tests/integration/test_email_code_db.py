"""IDX-A3 against a real Postgres — the half the fakes cannot prove.

The unit suite exercises the decision logic with in-memory stores. What
only a database can answer:

  * the signup transaction is genuinely atomic, and genuinely writes all
    four rows (identity, tenant, membership, user);
  * ``consume`` is a conditional UPDATE, so two concurrent verifies of
    the same code produce one winner;
  * ``app_role`` — the role every other service in the fleet connects as —
    cannot read ``identities`` at all;
  * a new identity's tenant is invisible from another tenant's scope.

Requires: ``RUN_DB_INTEGRATION=1`` and ``make migrate-up``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and a migrated dev database",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from auth_service.domain import email_code as ec  # noqa: E402
from auth_service.domain.identity_repository import (  # noqa: E402
    IdentityRepository,
    PgChallengeStore,
    SessionRepository,
)

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
WRITER_DSN = "postgresql://tenant_writer:tenant_writer@localhost:5432/notes"
APP_DSN = "postgresql://app_role:app_role@localhost:5432/notes"
TENANT_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
PLATFORM = uuid.UUID("00000000-0000-0000-0000-0000000000f1")

DOMAIN = "a3.example"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@{DOMAIN}"


@pytest_asyncio.fixture
async def writer_pool():
    pool = await asyncpg.create_pool(WRITER_DSN, min_size=1, max_size=6)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        # Everything this module creates hangs off one throwaway domain.
        await conn.execute("DELETE FROM auth_challenges WHERE email LIKE $1", f"%@{DOMAIN}")
        await conn.execute(
            """
            DELETE FROM auth_sessions WHERE identity_id IN
                (SELECT id FROM identities WHERE email LIKE $1)
            """,
            f"%@{DOMAIN}",
        )
        await conn.execute(
            """
            DELETE FROM users WHERE tenant_id IN
                (SELECT tenant_id FROM tenant_memberships WHERE user_sub IN
                    (SELECT id FROM identities WHERE email LIKE $1))
            """,
            f"%@{DOMAIN}",
        )
        await conn.execute(
            """
            DELETE FROM tenants WHERE id IN
                (SELECT tenant_id FROM tenant_memberships WHERE user_sub IN
                    (SELECT id FROM identities WHERE email LIKE $1))
            """,
            f"%@{DOMAIN}",
        )
        await conn.execute("DELETE FROM identities WHERE email LIKE $1", f"%@{DOMAIN}")
        await conn.close()


# ── the signup transaction ───────────────────────────────────────────────


async def test_signup_writes_identity_tenant_membership_and_user(writer_pool, su) -> None:
    repo = IdentityRepository(writer_pool)
    email = _email()
    before = await su.fetchval("SELECT count(*) FROM tenants WHERE kind = 'personal'")

    identity, membership = await repo.create_with_personal_workspace(email)

    assert membership.role == "owner"
    assert membership.kind == "personal"

    after = await su.fetchval("SELECT count(*) FROM tenants WHERE kind = 'personal'")
    assert after == before + 1, "exactly one personal workspace"

    tenant = await su.fetchrow(
        "SELECT name, display_name, slug, kind, status FROM tenants WHERE id = $1",
        membership.tenant_id,
    )
    assert tenant["kind"] == "personal"
    assert tenant["status"] == "active"
    assert tenant["slug"].startswith("ws-")
    assert tenant["display_name"].endswith("'s workspace")

    assert await su.fetchval(
        "SELECT count(*) FROM tenant_memberships WHERE tenant_id = $1 AND user_sub = $2"
        " AND role = 'owner' AND status = 'active'",
        membership.tenant_id,
        identity.id,
    )
    # The `users` row the rest of the estate resolves a sub through.
    user = await su.fetchrow(
        "SELECT tenant_id, email, status FROM users WHERE sub = $1", identity.id
    )
    assert user["tenant_id"] == membership.tenant_id
    assert user["email"] == email
    assert user["status"] == "active"

    assert identity.last_tenant_id == membership.tenant_id
    assert identity.email_verified_at is not None


async def test_a_second_signup_for_the_same_local_part_gets_its_own_workspace(
    writer_pool, su
) -> None:
    """`ada@one.test` and `ada@two.test` both want the workspace name "ada"."""
    repo = IdentityRepository(writer_pool)
    local = f"ada{uuid.uuid4().hex[:8]}"
    first, m1 = await repo.create_with_personal_workspace(f"{local}@{DOMAIN}")
    second, m2 = await repo.create_with_personal_workspace(f"{local}@other-{DOMAIN}")

    assert first.id != second.id
    assert m1.tenant_id != m2.tenant_id
    names = await su.fetch(
        "SELECT name FROM tenants WHERE id = ANY($1::uuid[])", [m1.tenant_id, m2.tenant_id]
    )
    assert len({r["name"] for r in names}) == 2, "the name collision was resolved, not swallowed"


async def test_a_duplicate_address_is_refused_rather_than_retried(writer_pool) -> None:
    repo = IdentityRepository(writer_pool)
    email = _email()
    await repo.create_with_personal_workspace(email)
    with pytest.raises(asyncpg.UniqueViolationError):
        await repo.create_with_personal_workspace(email)


# ── challenges ───────────────────────────────────────────────────────────


async def test_only_one_of_two_concurrent_consumes_wins(writer_pool) -> None:
    store = PgChallengeStore(writer_pool)
    cid = uuid.uuid4()
    await store.open(
        challenge_id=cid,
        kind=ec.KIND_EMAIL_LOGIN,
        email=_email(),
        identity_id=None,
        code_hash=ec.code_hash("482913", cid),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        max_attempts=5,
        client_type="web",
        ip="203.0.113.7",
    )
    results = await asyncio.gather(store.consume(cid), store.consume(cid))
    assert sorted(results) == [False, True], "a double submit logs in exactly once"


async def test_starting_again_supersedes_the_open_challenge(writer_pool) -> None:
    store = PgChallengeStore(writer_pool)
    email = _email()
    first = uuid.uuid4()
    await store.open(
        challenge_id=first,
        kind=ec.KIND_EMAIL_LOGIN,
        email=email,
        identity_id=None,
        code_hash=ec.code_hash("111111", first),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        max_attempts=5,
        client_type="web",
        ip="",
    )
    assert await store.latest_open_for_email(kind=ec.KIND_EMAIL_LOGIN, email=email) is not None
    assert await store.consume_open_for_email(kind=ec.KIND_EMAIL_LOGIN, email=email) == 1

    stale = await store.get(first)
    assert stale is not None and stale.consumed_at is not None
    assert await store.latest_open_for_email(kind=ec.KIND_EMAIL_LOGIN, email=email) is None


# ── lockout ──────────────────────────────────────────────────────────────


async def test_the_tenth_failure_locks_and_the_notice_is_claimed_once(writer_pool) -> None:
    repo = IdentityRepository(writer_pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    policy = ec.LockoutPolicy()

    for _ in range(9):
        state = await repo.register_failure(identity.id, policy=policy)
        assert state.locked_until is None

    state = await repo.register_failure(identity.id, policy=policy)
    assert state.newly_locked is True
    assert state.locked_until is not None

    # Exactly one lock notice per lock, however many requests race for it.
    claims = await asyncio.gather(*(repo.claim_lock_notice(identity.id) for _ in range(5)))
    assert sum(claims) == 1

    # A successful sign-in clears the counters (but not the lock history,
    # which is what makes the next lock longer).
    fresh = await repo.get(identity.id)
    assert fresh is not None and fresh.lock_count == 1
    await repo.note_successful_login(identity.id, tenant_id=identity.last_tenant_id)
    cleared = await repo.get(identity.id)
    assert cleared is not None
    assert cleared.failed_login_count == 0
    assert cleared.locked_until is None
    assert cleared.lock_count == 1


async def test_concurrent_failures_cannot_skip_past_the_threshold(writer_pool) -> None:
    """Ten simultaneous wrong codes must still produce a lock.

    Without ``FOR UPDATE`` each would read the same count and the account
    would sit at 1 failure, unlocked, having just absorbed ten guesses.
    """
    repo = IdentityRepository(writer_pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    policy = ec.LockoutPolicy()
    states = await asyncio.gather(
        *(repo.register_failure(identity.id, policy=policy) for _ in range(10))
    )
    assert sum(1 for s in states if s.newly_locked) == 1
    row = await repo.get(identity.id)
    assert row is not None and row.locked_until is not None


# ── sessions ─────────────────────────────────────────────────────────────


async def test_a_session_stores_only_the_hash_of_its_refresh_token(writer_pool, su) -> None:
    repo = IdentityRepository(writer_pool)
    identity, membership = await repo.create_with_personal_workspace(_email())
    sessions = SessionRepository(writer_pool)

    sid, expires_at = await sessions.create(
        identity_id=identity.id,
        tenant_id=membership.tenant_id,
        refresh_token="the-plaintext-refresh-token",
        ttl_seconds=3600,
        client_type="ios",
        ip="203.0.113.7",
        user_agent="Notes AI/1.0",
    )
    assert expires_at > datetime.now(UTC)
    row = await su.fetchrow(
        "SELECT refresh_token_hash, tenant_id, client_type FROM auth_sessions WHERE id = $1", sid
    )
    assert row["tenant_id"] == membership.tenant_id
    assert row["client_type"] == "ios"
    assert b"the-plaintext-refresh-token" not in bytes(row["refresh_token_hash"])


# ── isolation ────────────────────────────────────────────────────────────


async def test_app_role_cannot_read_the_identity_tables() -> None:
    """The rest of the fleet connects as ``app_role``. It gets nothing here.

    These tables carry every registered address in the system and the
    live one-time-code hashes; the grant is the boundary, and RLS with no
    app_role policy is the second one behind it.
    """
    conn = await asyncpg.connect(APP_DSN)
    try:
        for table in ("identities", "auth_challenges", "auth_sessions"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.fetch(f"SELECT * FROM {table} LIMIT 1")
    finally:
        await conn.close()


async def test_a_new_workspace_is_invisible_from_another_tenants_scope(writer_pool) -> None:
    repo = IdentityRepository(writer_pool)
    _, membership = await repo.create_with_personal_workspace(_email())

    conn = await asyncpg.connect(APP_DSN)
    try:
        # Scoped to the seeded dev tenant, exactly as a note-service
        # request would be.
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(TENANT_A))
        assert (
            await conn.fetchval("SELECT count(*) FROM tenants WHERE id = $1", membership.tenant_id)
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM tenant_memberships WHERE tenant_id = $1", membership.tenant_id
            )
            == 0
        )
    finally:
        await conn.close()


async def test_the_platform_tenant_exists_for_pre_account_audit_events(su) -> None:
    row = await su.fetchrow("SELECT name, kind, status FROM tenants WHERE id = $1", PLATFORM)
    assert row is not None, "migration 0024 seeds the tenant auth.otp_requested is written to"
    assert row["kind"] == "platform"
    assert row["status"] == "active"
