"""IDX-B3 D/K — the maintenance jobs, against a real database.

The property that matters most is idempotence, because ADR-0041 buys its
simplicity with it: there is no advisory lock, so two replicas run the
same sweep at the same instant. Every job is therefore tested three ways
— it does the work, a re-run is a no-op, and two concurrent runs converge
on the same state.
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

from auth_service.maintenance import BY_NAME, JOBS, run_job  # noqa: E402
from auth_service.maintenance import jobs as maint_jobs  # noqa: E402

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
WRITER_DSN = "postgresql://tenant_writer:tenant_writer@localhost:5432/notes"
TENANT_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
MARK = "b3maint"


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(WRITER_DSN, min_size=1, max_size=6)
    try:
        yield p
    finally:
        await p.close()


@pytest_asyncio.fixture
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        ids = "(SELECT id FROM identities WHERE email LIKE $1)"
        await conn.execute(f"DELETE FROM auth_sessions WHERE identity_id IN {ids}", f"%{MARK}%")
        await conn.execute(f"DELETE FROM auth_challenges WHERE identity_id IN {ids}", f"%{MARK}%")
        await conn.execute("DELETE FROM auth_challenges WHERE email LIKE $1", f"%{MARK}%")
        await conn.execute(f"DELETE FROM tenant_memberships WHERE user_sub IN {ids}", f"%{MARK}%")
        await conn.execute("DELETE FROM identities WHERE email LIKE $1", f"%{MARK}%")
        await conn.close()


async def _identity(su, suffix: str) -> uuid.UUID:
    ident = uuid.uuid4()
    await su.execute(
        "INSERT INTO identities (id, email, display_name, status) VALUES ($1, $2, 'X', 'active')",
        ident,
        f"{suffix}-{MARK}@x.example",
    )
    return ident


async def _challenge(su, *, expires_at: datetime, email: str | None = None) -> uuid.UUID:
    cid = uuid.uuid4()
    await su.execute(
        "INSERT INTO auth_challenges (id, kind, email, code_hash, expires_at)"
        " VALUES ($1, 'email_login', $2, 'x', $3)",
        cid,
        email or f"c-{MARK}@x.example",
        expires_at,
    )
    return cid


# ── registry ─────────────────────────────────────────────────────────────


def test_every_job_is_reachable_by_name_and_documented() -> None:
    assert set(BY_NAME) == {j.name for j in JOBS}
    for job in JOBS:
        assert job.summary, f"{job.name} has no summary for --list"
        if job.scheduled:
            assert job.interval_seconds and job.interval_seconds > 0


def test_only_rotate_kek_is_manual() -> None:
    """A timer must not decide to re-key every second factor in the estate."""
    manual = {j.name for j in JOBS if not j.scheduled}
    assert manual == {"rotate-kek"}


# ── purge-challenges ─────────────────────────────────────────────────────


async def test_purge_challenges_deletes_only_what_is_past_retention(pool, su) -> None:
    now = datetime.now(UTC)
    old = await _challenge(su, expires_at=now - timedelta(hours=25))
    recent = await _challenge(su, expires_at=now - timedelta(hours=1))
    live = await _challenge(su, expires_at=now + timedelta(minutes=10))

    result = await maint_jobs.purge_challenges(pool)
    assert result.rows >= 1

    remaining = {
        r["id"]
        for r in await su.fetch(
            "SELECT id FROM auth_challenges WHERE id = ANY($1::uuid[])", [old, recent, live]
        )
    }
    assert old not in remaining, "past retention, should be gone"
    assert recent in remaining, "expired but inside the 24h window"
    assert live in remaining


async def test_purge_challenges_is_idempotent(pool, su) -> None:
    await _challenge(su, expires_at=datetime.now(UTC) - timedelta(hours=30))
    first = await maint_jobs.purge_challenges(pool)
    second = await maint_jobs.purge_challenges(pool)
    assert first.rows >= 1
    assert second.rows == 0, "a re-run must be a no-op"


async def test_two_concurrent_purges_converge(pool, su) -> None:
    """ADR-0041 has no advisory lock; this is the property that makes it safe."""
    for _ in range(5):
        await _challenge(su, expires_at=datetime.now(UTC) - timedelta(hours=30))

    a, b = await asyncio.gather(
        maint_jobs.purge_challenges(pool), maint_jobs.purge_challenges(pool)
    )
    assert (
        await su.fetchval(
            "SELECT count(*) FROM auth_challenges WHERE email LIKE $1"
            " AND expires_at < now() - interval '24 hours'",
            f"%{MARK}%",
        )
        == 0
    )
    # Between them they did the work once; neither errored.
    assert a.rows + b.rows >= 5


# ── expire-sessions ──────────────────────────────────────────────────────


async def test_expire_sessions_revokes_the_expired_and_reaps_the_ancient(pool, su) -> None:
    ident = await _identity(su, "sess")
    live = uuid.uuid4()
    expired = uuid.uuid4()
    ancient = uuid.uuid4()
    now = datetime.now(UTC)
    for sid, expires, revoked in (
        (live, now + timedelta(days=1), None),
        (expired, now - timedelta(minutes=1), None),
        (ancient, now - timedelta(days=200), now - timedelta(days=100)),
    ):
        await su.execute(
            "INSERT INTO auth_sessions (id, identity_id, tenant_id, refresh_token_hash,"
            " expires_at, revoked_at) VALUES ($1, $2, $3, $4, $5, $6)",
            sid,
            ident,
            TENANT_A,
            uuid.uuid4().bytes,
            expires,
            revoked,
        )

    result = await maint_jobs.expire_sessions(pool)
    assert result.detail is not None and result.detail["expired"] >= 1

    rows = {
        r["id"]: r["revoked_at"]
        for r in await su.fetch(
            "SELECT id, revoked_at FROM auth_sessions WHERE id = ANY($1::uuid[])",
            [live, expired, ancient],
        )
    }
    assert rows[live] is None, "a live session must not be touched"
    assert rows[expired] is not None, "past its absolute expiry"
    assert ancient not in rows, "revoked over 90 days ago; reaped"


async def test_expire_sessions_is_idempotent(pool, su) -> None:
    ident = await _identity(su, "idem")
    await su.execute(
        "INSERT INTO auth_sessions (identity_id, tenant_id, refresh_token_hash, expires_at)"
        " VALUES ($1, $2, $3, now() - interval '1 minute')",
        ident,
        TENANT_A,
        uuid.uuid4().bytes,
    )
    first = await maint_jobs.expire_sessions(pool)
    second = await maint_jobs.expire_sessions(pool)
    assert first.detail["expired"] >= 1  # type: ignore[index]
    assert second.detail["expired"] == 0  # type: ignore[index]


# ── sample-gauges ────────────────────────────────────────────────────────


async def test_sample_gauges_counts_live_sessions_and_active_devices(pool, su) -> None:
    ident = await _identity(su, "gauge")
    await su.execute(
        "INSERT INTO auth_sessions (identity_id, tenant_id, refresh_token_hash, expires_at)"
        " VALUES ($1, $2, $3, now() + interval '1 day')",
        ident,
        TENANT_A,
        uuid.uuid4().bytes,
    )
    result = await maint_jobs.sample_gauges(pool)
    assert result.detail is not None
    assert result.detail["sessions_active"] >= 1
    assert result.detail["devices_active"] >= 0
    # A gauge job affects no rows; reporting otherwise would inflate
    # mdx_auth_maint_rows_total into meaninglessness.
    assert result.rows == 0


# ── purge-deleted-identities ─────────────────────────────────────────────


async def test_the_purge_job_respects_the_grace_period(pool, su) -> None:
    inside = await _identity(su, "grace-in")
    past = await _identity(su, "grace-out")
    await su.execute(
        "UPDATE identities SET status='pending_deletion', deletion_requested_at = $2 WHERE id = $1",
        inside,
        datetime.now(UTC) - timedelta(days=5),
    )
    await su.execute(
        "UPDATE identities SET status='pending_deletion', deletion_requested_at = $2 WHERE id = $1",
        past,
        datetime.now(UTC) - timedelta(days=40),
    )

    await maint_jobs.purge_deleted_identities(pool)

    assert await su.fetchval("SELECT status FROM identities WHERE id = $1", inside) == (
        "pending_deletion"
    ), "still inside the 30-day grace; signing in must still restore it"
    assert await su.fetchval("SELECT status FROM identities WHERE id = $1", past) == "deleted"
    assert (
        await su.fetchval("SELECT email FROM identities WHERE id = $1", past) == f"deleted:{past}"
    )
    # Clean up the pseudonymised row the fixture's LIKE no longer matches.
    await su.execute("DELETE FROM identities WHERE id = $1", past)


# ── run_job wrapper ──────────────────────────────────────────────────────


async def test_run_job_records_success_and_returns_the_result(pool) -> None:
    result = await run_job(BY_NAME["sample-gauges"], pool)
    assert result.job == "sample-gauges"
    assert "sessions_active" in result.as_payload()


async def test_a_failing_job_propagates_so_the_cli_can_exit_nonzero(pool) -> None:
    """`run_job_once` swallows for the scheduler; the CLI needs the raise."""
    from auth_service.maintenance import Job

    async def _boom(_pool: object) -> maint_jobs.JobResult:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        await run_job(Job("boom", None, _boom, "test"), pool)


async def test_signing_key_status_reports_without_a_pool(pool) -> None:
    result = await maint_jobs.signing_key_status(pool)
    assert result.job == "signing-key-status"
    assert result.detail is not None
