"""``JobQueue`` — the only writer of the ``jobs`` table.

Claims go through ``jobs_claim()`` (SECURITY DEFINER, cross-tenant, FOR
UPDATE SKIP LOCKED); every other transition runs under
``tenant_connection`` for the job's tenant so RLS stays the guard.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from db import tenant_connection

from . import metrics
from .models import Job, JobStatus
from .policy import next_run_at, utcnow, warming_decision

logger = logging.getLogger("jobs.queue")


class JobQueue:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── enqueue ─────────────────────────────────────────────────────────
    async def enqueue(
        self,
        tenant_id: UUID,
        kind: str,
        payload: dict[str, Any],
        *,
        run_at: datetime | None = None,
        priority: int = 0,
        max_attempts: int = 5,
        idempotency_key: str | None = None,
        conn: asyncpg.Connection | None = None,
    ) -> Job:
        """Insert a job. With an ``idempotency_key`` the existing row wins (replay-safe POST)."""
        sql = """
            INSERT INTO jobs (tenant_id, kind, payload, run_at, priority, max_attempts, idempotency_key)
            VALUES ($1, $2, $3::jsonb, COALESCE($4, now()), $5, $6, $7)
            ON CONFLICT (tenant_id, kind, idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
            RETURNING *
        """
        args = (
            tenant_id,
            kind,
            json.dumps(payload),
            run_at,
            priority,
            max_attempts,
            idempotency_key,
        )
        if conn is not None:
            row = await conn.fetchrow(sql, *args)
            if row is None and idempotency_key:
                row = await conn.fetchrow(
                    "SELECT * FROM jobs WHERE tenant_id = $1 AND kind = $2 AND idempotency_key = $3",
                    tenant_id,
                    kind,
                    idempotency_key,
                )
        else:
            async with tenant_connection(self._pool, tenant_id) as c:
                row = await c.fetchrow(sql, *args)
                if row is None and idempotency_key:
                    row = await c.fetchrow(
                        "SELECT * FROM jobs WHERE tenant_id = $1 AND kind = $2 AND idempotency_key = $3",
                        tenant_id,
                        kind,
                        idempotency_key,
                    )
        assert row is not None
        job = Job.from_row(row)
        logger.info("jobs.enqueued", extra=job.log_fields())
        return job

    async def get(self, tenant_id: UUID, job_id: UUID) -> Job | None:
        async with tenant_connection(self._pool, tenant_id) as c:
            row = await c.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        return Job.from_row(row) if row else None

    # ── claim / lease ───────────────────────────────────────────────────
    async def claim(
        self, kinds: list[str], *, worker: str, lease_seconds: int = 60, limit: int = 1
    ) -> list[Job]:
        async with self._pool.acquire() as c:
            rows = await c.fetch(
                "SELECT * FROM jobs_claim($1::text[], $2, $3, $4)",
                kinds,
                worker,
                lease_seconds,
                limit,
            )
        jobs = [Job.from_row(r) for r in rows]
        now = utcnow()
        for job in jobs:
            metrics.jobs_claimed_total.add(1, {"kind": job.kind})
            metrics.jobs_queued_age_seconds.record(
                max(0.0, (now - job.run_at).total_seconds()), {"kind": job.kind}
            )
        return jobs

    async def heartbeat(self, job: Job, *, lease_seconds: int = 60) -> bool:
        async with tenant_connection(self._pool, job.tenant_id) as c:
            tag = await c.execute(
                """UPDATE jobs SET heartbeat_at = now(), lease_expires_at = now() + make_interval(secs => $2)
                   WHERE id = $1 AND status = 'running' AND leased_by = $3""",
                job.id,
                float(lease_seconds),
                job.leased_by,
            )
        return bool(str(tag).endswith("1"))

    # ── outcomes ────────────────────────────────────────────────────────
    async def complete(
        self,
        job: Job,
        result: dict[str, Any] | None = None,
        *,
        conn: asyncpg.Connection | None = None,
    ) -> None:
        sql = """UPDATE jobs SET status = 'complete', result = $2::jsonb, finished_at = now(), leased_by = NULL,
                        lease_expires_at = NULL, waiting_backend = NULL, waiting_since = NULL
                 WHERE id = $1 AND status = 'running'"""
        await self._exec(
            job, sql, job.id, json.dumps(result) if result is not None else None, conn=conn
        )
        metrics.jobs_finished_total.add(1, {"kind": job.kind, "outcome": "complete"})

    async def fail(
        self,
        job: Job,
        *,
        error_kind: str,
        message: str,
        retryable: bool,
        conn: asyncpg.Connection | None = None,
    ) -> JobStatus:
        """Retryable + attempts left → back to `queued` with backoff; else `failed`/`dead`."""
        message = message[:500]
        if retryable and job.attempts < job.max_attempts:
            run_at = next_run_at(utcnow(), job.attempts)
            sql = """UPDATE jobs SET status = 'queued', run_at = $2, error_kind = $3, last_error = $4, leased_by = NULL,
                            lease_expires_at = NULL, waiting_backend = NULL, waiting_since = NULL
                     WHERE id = $1 AND status = 'running'"""
            await self._exec(job, sql, job.id, run_at, error_kind, message, conn=conn)
            metrics.jobs_finished_total.add(1, {"kind": job.kind, "outcome": "retry"})
            return JobStatus.QUEUED
        status = JobStatus.DEAD if retryable else JobStatus.FAILED
        sql = """UPDATE jobs SET status = $2, error_kind = $3, last_error = $4, finished_at = now(), leased_by = NULL,
                        lease_expires_at = NULL
                 WHERE id = $1 AND status = 'running'"""
        await self._exec(job, sql, job.id, str(status), error_kind, message, conn=conn)
        metrics.jobs_finished_total.add(1, {"kind": job.kind, "outcome": str(status)})
        return status

    async def wait_on_model(
        self, job: Job, *, backend: str, cold_start_seconds: int, retry_after_s: float | None = None
    ) -> JobStatus:
        """Park the job while a scale-to-zero backend wakes up — no attempt consumed."""
        decision = warming_decision(
            now=utcnow(),
            waiting_since=job.waiting_since,
            cold_start_seconds=cold_start_seconds,
            retry_after_s=retry_after_s,
        )
        if not decision.wait:
            logger.warning(
                "jobs.warming_budget_exhausted",
                extra={
                    **job.log_fields(),
                    "backend": backend,
                    "waited_s": round(decision.waited_seconds),
                },
            )
            return await self.fail(
                job,
                error_kind="warming",
                message=f"{backend} still warming after {decision.waited_seconds:.0f}s (budget {decision.budget_seconds:.0f}s)",
                retryable=True,
            )
        first = job.waiting_since is None
        sql = """UPDATE jobs SET status = 'waiting_on_model', run_at = $2, waiting_backend = $3,
                        waiting_since = COALESCE(waiting_since, now()), leased_by = NULL, lease_expires_at = NULL,
                        error_kind = 'warming', last_error = ''
                 WHERE id = $1 AND status = 'running'"""
        await self._exec(job, sql, job.id, decision.run_at, backend)
        if first:
            metrics.model_cold_starts_total.add(1, {"backend": backend})
        metrics.jobs_finished_total.add(1, {"kind": job.kind, "outcome": "waiting_on_model"})
        logger.info(
            "jobs.waiting_on_model",
            extra={
                **job.log_fields(),
                "backend": backend,
                "waited_s": round(decision.waited_seconds),
            },
        )
        return JobStatus.WAITING_ON_MODEL

    async def cancel(self, job: Job, *, reason: str = "cancelled") -> None:
        sql = """UPDATE jobs SET status = 'cancelled', last_error = $2, finished_at = now(), leased_by = NULL, lease_expires_at = NULL
                 WHERE id = $1 AND status IN ('queued', 'running', 'waiting_on_model')"""
        await self._exec(job, sql, job.id, reason)
        metrics.jobs_finished_total.add(1, {"kind": job.kind, "outcome": "cancelled"})

    # ── housekeeping (cross-tenant, SECURITY DEFINER) ───────────────────
    async def reap_stale_leases(self, *, grace_seconds: float = 30.0) -> int:
        async with self._pool.acquire() as c:
            n = int(await c.fetchval("SELECT jobs_reap_stale_leases($1)", float(grace_seconds)))
        if n:
            metrics.jobs_reaped_total.add(n)
            logger.warning("jobs.reaped_stale_leases", extra={"count": n})
        return n

    async def refresh_waiting_gauges(self) -> dict[str, int]:
        async with self._pool.acquire() as c:
            rows = await c.fetch(
                "SELECT backend, waiting, oldest_seconds FROM jobs_waiting_by_backend()"
            )
        seen: dict[str, int] = {}
        for r in rows:
            seen[r["backend"]] = int(r["waiting"])
            metrics.model_waiting_jobs.set(int(r["waiting"]), {"backend": r["backend"]})
            metrics.model_waiting_oldest_seconds.set(
                float(r["oldest_seconds"] or 0), {"backend": r["backend"]}
            )
        return seen

    async def _exec(
        self, job: Job, sql: str, *args: Any, conn: asyncpg.Connection | None = None
    ) -> None:
        if conn is not None:
            await conn.execute(sql, *args)
            return
        async with tenant_connection(self._pool, job.tenant_id) as c:
            await c.execute(sql, *args)
