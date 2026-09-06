"""Live-DB tests for migrations 0022/0023 (RUN_DB_INTEGRATION=1; needs
`make dev-up && make migrate-up`). Covers: claim with SKIP LOCKED, the
warming re-claim not consuming an attempt, the stale-lease reaper, and
tenant isolation for jobs and model_usage (A cannot read B)."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from db import create_pool, tenant_connection
from jobs import CostTable, JobQueue, JobStatus, UsageLedger
from models import UsageRecord

KIND = f"understand-{uuid4().hex[:8]}"
KIND_EMBED = f"embed-{uuid4().hex[:8]}"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1 to run; needs `make dev-up && make migrate-up`",
)

HOST = os.environ.get("POSTGRES_HOST", "localhost")
PORT = os.environ.get("POSTGRES_PORT", "5432")
DB = os.environ.get("POSTGRES_DB", "notes")
APP_DSN = f"postgresql://app_role:app_role@{HOST}:{PORT}/{DB}"
SUPER_DSN = f"postgresql://postgres:postgres@{HOST}:{PORT}/{DB}"


@pytest.fixture
async def tenants() -> tuple[UUID, UUID]:
    """Two fresh tenants; their jobs/usage rows are removed afterwards (superuser)."""
    a, b = uuid4(), uuid4()
    conn = await asyncpg.connect(SUPER_DSN)
    try:
        for t in (a, b):
            await conn.execute(
                "INSERT INTO tenants (id, name, display_name) VALUES ($1, $2, $2) ON CONFLICT DO NOTHING",
                t,
                f"t-{t}",
            )
    finally:
        await conn.close()
    yield a, b
    conn = await asyncpg.connect(SUPER_DSN)
    try:
        await conn.execute("DELETE FROM model_usage WHERE tenant_id = ANY($1::uuid[])", [a, b])
        await conn.execute("DELETE FROM jobs WHERE tenant_id = ANY($1::uuid[])", [a, b])
        await conn.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [a, b])
    finally:
        await conn.close()


@pytest.fixture
async def pool() -> asyncpg.Pool:
    p = await create_pool(APP_DSN, application_name="jobs-test", max_size=4)
    yield p
    await p.close()


async def test_claim_runs_and_completes(pool: asyncpg.Pool, tenants: tuple[UUID, UUID]) -> None:
    a, _ = tenants
    q = JobQueue(pool)
    job = await q.enqueue(a, KIND, {"x": 1}, idempotency_key="k1")
    again = await q.enqueue(a, KIND, {"x": 1}, idempotency_key="k1")
    assert again.id == job.id  # idempotent
    claimed = await q.claim([KIND], worker="w1")
    assert [j.id for j in claimed] == [job.id] and claimed[0].attempts == 1
    assert await q.claim([KIND], worker="w2") == []  # SKIP LOCKED / not claimable twice
    assert await q.heartbeat(claimed[0]) is True
    await q.complete(claimed[0], {"done": True})
    got = await q.get(a, job.id)
    assert got is not None and got.status is JobStatus.COMPLETE and got.result == {"done": True}


async def test_warming_reclaim_does_not_consume_an_attempt(
    pool: asyncpg.Pool, tenants: tuple[UUID, UUID]
) -> None:
    a, _ = tenants
    q = JobQueue(pool)
    job = await q.enqueue(a, KIND, {})
    [claimed] = await q.claim([KIND], worker="w1")
    assert claimed.attempts == 1
    assert (
        await q.wait_on_model(claimed, backend="hf_eu", cold_start_seconds=300)
        is JobStatus.WAITING_ON_MODEL
    )
    parked = await q.get(a, job.id)
    assert (
        parked is not None
        and parked.status is JobStatus.WAITING_ON_MODEL
        and parked.waiting_backend == "hf_eu"
    )
    assert await q.claim([KIND], worker="w1") == []  # run_at is 30 s out
    waiting_before = (await q.refresh_waiting_gauges()).get("hf_eu", 0)
    assert waiting_before >= 1
    async with tenant_connection(pool, a) as c:
        await c.execute("UPDATE jobs SET run_at = now() WHERE id = $1", job.id)
    [reclaimed] = await q.claim([KIND], worker="w1")
    assert reclaimed.attempts == 1  # NOT incremented
    assert (await q.refresh_waiting_gauges()).get("hf_eu", 0) == waiting_before - 1
    await q.complete(reclaimed)


async def test_reaper_requeues_expired_leases(
    pool: asyncpg.Pool, tenants: tuple[UUID, UUID]
) -> None:
    a, _ = tenants
    q = JobQueue(pool)
    job = await q.enqueue(a, KIND_EMBED, {})
    [claimed] = await q.claim([KIND_EMBED], worker="w1", lease_seconds=1)
    async with tenant_connection(pool, a) as c:
        await c.execute(
            "UPDATE jobs SET lease_expires_at = now() - interval '5 minutes' WHERE id = $1", job.id
        )
    assert await q.reap_stale_leases(grace_seconds=1) >= 1
    got = await q.get(a, claimed.id)
    assert got is not None and got.status is JobStatus.QUEUED and got.error_kind == "worker_lost"


async def test_tenant_isolation_jobs_and_usage(
    pool: asyncpg.Pool, tenants: tuple[UUID, UUID]
) -> None:
    a, b = tenants
    q = JobQueue(pool)
    job = await q.enqueue(a, KIND, {})
    assert await q.get(b, job.id) is None  # B cannot read A's job
    ledger = UsageLedger(CostTable.empty())
    rec = UsageRecord(
        backend="hf_eu",
        model_id="m",
        operation="chat.complete",
        ok=True,
        latency_ms=10,
        input_tokens=1,
        output_tokens=1,
    )
    async with tenant_connection(pool, a) as c:
        await ledger.flush(c, tenant_id=a, job_id=job.id, records=[rec])
    async with tenant_connection(pool, b) as c:
        assert await c.fetchval("SELECT count(*) FROM model_usage WHERE job_id = $1", job.id) == 0
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.execute(
                "INSERT INTO model_usage (tenant_id, backend, model_id, operation, ok, latency_ms) VALUES ($1, 'x', 'm', 'o', true, 1)",
                a,
            )
    async with tenant_connection(pool, a) as c:
        assert await c.fetchval("SELECT count(*) FROM model_usage WHERE job_id = $1", job.id) == 1
        daily = await c.fetch(
            "SELECT backend, calls FROM model_usage_daily WHERE tenant_id = $1", a
        )
        assert any(r["backend"] == "hf_eu" for r in daily)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.execute("DELETE FROM model_usage WHERE job_id = $1", job.id)
