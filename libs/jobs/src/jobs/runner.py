"""``JobRunner`` — claim → run handler → outcome, with lease heartbeat.

Warming policy (DEP-S1-03): before a handler runs, the runner calls the
handler's ``probe`` (if it has one) on the routed backend; a
``ProviderError(kind=warming)`` from the probe *or* the handler parks the
job as ``waiting_on_model`` without consuming an attempt. Other
``ProviderError`` kinds map through ``retryable``; ``auth`` is never
retried (no retry storm on a revoked token).

Usage records emitted while the handler runs are flushed into the
``model_usage`` table inside the job's completion transaction.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from db import tenant_connection
from models import ErrorKind, ProviderError, TranscriptionCancelledError

from . import metrics
from .ledger import UsageLedger
from .models import Job, JobStatus
from .queue import JobQueue

logger = logging.getLogger("jobs.runner")


@dataclass(slots=True)
class JobContext:
    job: Job
    worker_id: str


class Handler(Protocol):
    """One job kind. ``probe`` is optional: a cheap liveness call on the routed backend."""

    async def __call__(self, ctx: JobContext) -> dict[str, Any] | None: ...


ProbeFn = Callable[[JobContext], Awaitable[None]]
BackendFn = Callable[[JobContext], tuple[str, int]]  # → (backend name, cold_start_seconds)


@dataclass(slots=True)
class HandlerSpec:
    run: Handler
    backend: BackendFn | None = (
        None  # which model backend this job talks to (for warming state + metrics)
    )
    probe: ProbeFn | None = None


class JobRunner:
    def __init__(
        self,
        queue: JobQueue,
        handlers: dict[str, HandlerSpec],
        *,
        worker_id: str,
        ledger: UsageLedger | None = None,
        lease_seconds: int = 60,
        poll_interval_s: float = 1.0,
        batch: int = 1,
    ) -> None:
        self._queue = queue
        self._handlers = handlers
        self._worker_id = worker_id
        self._ledger = ledger
        self._lease = lease_seconds
        self._poll = poll_interval_s
        self._batch = batch
        self._stop = asyncio.Event()

    @property
    def kinds(self) -> list[str]:
        return list(self._handlers)

    def stop(self) -> None:
        self._stop.set()

    # ── loop ────────────────────────────────────────────────────────────
    async def run_forever(self) -> None:
        while not self._stop.is_set():
            jobs = await self._queue.claim(
                self.kinds, worker=self._worker_id, lease_seconds=self._lease, limit=self._batch
            )
            if not jobs:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll)
                continue
            for job in jobs:
                await self.run_one(job)

    async def run_once(self) -> int:
        """Claim and run up to ``batch`` jobs; returns how many ran (tests, cron twins)."""
        jobs = await self._queue.claim(
            self.kinds, worker=self._worker_id, lease_seconds=self._lease, limit=self._batch
        )
        for job in jobs:
            await self.run_one(job)
        return len(jobs)

    # ── one job ─────────────────────────────────────────────────────────
    async def run_one(self, job: Job) -> JobStatus:
        spec = self._handlers[job.kind]
        ctx = JobContext(job=job, worker_id=self._worker_id)
        started = time.monotonic()
        hb = asyncio.create_task(self._heartbeat(job))
        if self._ledger:
            self._ledger.begin()
        try:
            if spec.probe is not None:
                await spec.probe(ctx)  # ProviderError(warming) → parked below, attempt not consumed
            result = await spec.run(ctx)
            status = await self._complete(job, result)
        except ProviderError as exc:
            status = await self._on_provider_error(job, spec, ctx, exc)
        except TranscriptionCancelledError:
            await self._queue.cancel(job, reason="cancel requested")
            status = JobStatus.CANCELLED
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # handler bug or infra: retryable, classified as unhandled
            logger.exception("jobs.unhandled", extra=job.log_fields())
            status = await self._queue.fail(
                job, error_kind="unhandled", message=f"{type(exc).__name__}: {exc}", retryable=True
            )
        finally:
            hb.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb
            if self._ledger:
                leftover = self._ledger.drain()
                if leftover:
                    # The completion path flushes inside its transaction; anything
                    # left here belongs to a failed/parked job and is still a cost.
                    await self._flush_standalone(job, leftover)
        metrics.jobs_processing_seconds.record(
            time.monotonic() - started, {"kind": job.kind, "outcome": str(status)}
        )
        return status

    async def _complete(self, job: Job, result: dict[str, Any] | None) -> JobStatus:
        records = self._ledger.drain() if self._ledger else []
        async with tenant_connection(self._queue._pool, job.tenant_id) as conn:  # noqa: SLF001 — same package
            if self._ledger and records:
                await self._ledger.flush(
                    conn, tenant_id=job.tenant_id, job_id=job.id, records=records
                )
            await self._queue.complete(job, result, conn=conn)
        return JobStatus.COMPLETE

    async def _flush_standalone(self, job: Job, records: list[Any]) -> None:
        if not self._ledger:
            return
        try:
            async with tenant_connection(self._queue._pool, job.tenant_id) as conn:  # noqa: SLF001
                await self._ledger.flush(
                    conn, tenant_id=job.tenant_id, job_id=job.id, records=records
                )
        except Exception:
            logger.exception(
                "jobs.usage_flush_failed", extra={**job.log_fields(), "records": len(records)}
            )

    async def _on_provider_error(
        self, job: Job, spec: HandlerSpec, ctx: JobContext, exc: ProviderError
    ) -> JobStatus:
        backend, cold_start = spec.backend(ctx) if spec.backend else (exc.backend, 0)
        fields = {**job.log_fields(), "backend": backend, "error_kind": str(exc.kind)}
        if exc.kind is ErrorKind.WARMING:
            return await self._queue.wait_on_model(
                job, backend=backend, cold_start_seconds=cold_start, retry_after_s=exc.retry_after_s
            )
        if exc.kind is ErrorKind.AUTH:
            logger.error("jobs.model_backend_auth", extra=fields)
            return await self._queue.fail(
                job, error_kind="auth", message=exc.message, retryable=False
            )
        logger.warning("jobs.model_backend_error", extra=fields)
        return await self._queue.fail(
            job, error_kind=str(exc.kind), message=exc.message, retryable=exc.retryable
        )

    async def _heartbeat(self, job: Job) -> None:
        interval = max(1.0, self._lease / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                ok = await self._queue.heartbeat(job, lease_seconds=self._lease)
                if not ok:
                    logger.warning("jobs.heartbeat_lost", extra=job.log_fields())
            except Exception:
                logger.exception("jobs.heartbeat_failed", extra=job.log_fields())
