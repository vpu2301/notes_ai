"""Stranded-job reaper: the out-of-process backstop for a worker that died mid-job.

``running`` past its grace window (dead worker) and ``queued`` past a longer one (lost
message) are failed conditionally. Cross-tenant enumeration goes through the
``asr_tenants_with_stale_jobs`` SECURITY DEFINER function; every row read and write
stays inside ``tenant_connection``. The grace windows are the only interlock (no
heartbeat): keep them above max_duration × inference multiplier plus a redelivery.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from asr_models import JobErrorKind
from audit import Severity
from db import tenant_connection

from .. import audit_kinds
from ..config import settings
from . import repository

logger = logging.getLogger(__name__)

# `running` = dead worker; `queued` = lost message.
_KIND_BY_STATUS = {
    "running": str(JobErrorKind.WORKER_LOST),
    "queued": str(JobErrorKind.QUEUE_LOST),
}


async def _tenants_with_stale_jobs(
    state: Any, *, running_grace_seconds: float, queued_grace_seconds: float
) -> list[UUID]:
    """Tenants with a stranded candidate; cross-tenant via SECURITY DEFINER, IDs only."""
    async with state.app_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tenant_id FROM asr_tenants_with_stale_jobs($1, $2)",
            float(running_grace_seconds),
            float(queued_grace_seconds),
        )
    return [r["tenant_id"] for r in rows]


async def reap_tenant(
    state: Any,
    tenant_id: UUID,
    *,
    running_grace_seconds: float,
    queued_grace_seconds: float,
) -> int:
    """Collect one tenant's stranded jobs. Returns how many were reaped."""
    reaped = 0
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        candidates = await repository.list_stale_jobs(
            conn,
            running_grace_seconds=running_grace_seconds,
            queued_grace_seconds=queued_grace_seconds,
            limit=settings.job_reaper_batch_limit,
        )
        for row in candidates:
            kind = _KIND_BY_STATUS.get(row.status)
            if kind is None:  # pragma: no cover — the query filters on status
                continue
            # Conditional on the status we saw: a job that finished meanwhile keeps its outcome.
            if not await repository.fail_job(
                conn,
                job_id=row.id,
                error_kind=kind,
                error_detail=(
                    f"reaped after {row.status} beyond the "
                    f"{running_grace_seconds if row.status == 'running' else queued_grace_seconds:.0f}s "
                    "grace window"
                ),
                only_if_status=(row.status,),
            ):
                continue

            reaped += 1
            logger.warning(
                "asr.job_reaped",
                extra={
                    "job_id": str(row.id),
                    "prior_status": row.status,
                    "error_kind": kind,
                },
            )
            try:
                await state.audit_writer.write_event(
                    tenant_id=tenant_id,
                    kind=audit_kinds.TRANSCRIPTION_FAILED,
                    actor_sub=row.requester_sub,
                    target_kind="asr_job",
                    target_id=str(row.id),
                    payload={
                        "error_kind": kind,
                        "prior_status": row.status,
                        "actor": "reaper",
                    },
                    severity=Severity.WARN,
                )
            except Exception as exc:  # noqa: BLE001 — audit must not block the sweep
                logger.warning(
                    "asr.job_reap_audit_failed",
                    extra={"job_id": str(row.id), "error": str(exc)},
                )
        reaped += await _reap_rediarize(
            state,
            conn,
            tenant_id,
            running_grace_seconds=running_grace_seconds,
            queued_grace_seconds=queued_grace_seconds,
        )
    return reaped


async def _reap_rediarize(
    state: Any,
    conn: Any,
    tenant_id: UUID,
    *,
    running_grace_seconds: float,
    queued_grace_seconds: float,
) -> int:
    """Stranded speaker re-runs: only the re-run fails; the job stays ``complete``."""
    reaped = 0
    for row in await repository.list_stale_rediarize(
        conn,
        running_grace_seconds=running_grace_seconds,
        queued_grace_seconds=queued_grace_seconds,
        limit=settings.job_reaper_batch_limit,
    ):
        grace = (
            running_grace_seconds if row.diarization_status == "running" else queued_grace_seconds
        )
        if not await repository.fail_rediarize(
            conn,
            job_id=row.id,
            error="stranded",
            only_if_status=row.diarization_status,
            older_than_seconds=grace,
        ):
            continue
        reaped += 1
        logger.warning(
            "asr.rediarize_reaped",
            extra={"job_id": str(row.id), "prior_status": row.diarization_status},
        )
        try:
            await state.audit_writer.write_event(
                tenant_id=tenant_id,
                kind=audit_kinds.REDIARIZE_FAILED,
                actor_sub=row.requester_sub,
                target_kind="asr_job",
                target_id=str(row.id),
                payload={"error_kind": "stranded", "actor": "reaper"},
                severity=Severity.WARN,
            )
        except Exception as exc:  # noqa: BLE001 — audit must not block the sweep
            logger.warning(
                "asr.job_reap_audit_failed",
                extra={"job_id": str(row.id), "error": str(exc)},
            )
    return reaped


async def sweep_once(state: Any) -> int:
    """One full pass across every tenant with candidates."""
    running_grace = float(settings.job_reaper_running_grace_s)
    queued_grace = float(settings.job_reaper_queued_grace_s)
    total = 0
    tenants = await _tenants_with_stale_jobs(
        state,
        running_grace_seconds=running_grace,
        queued_grace_seconds=queued_grace,
    )
    for tenant_id in tenants:
        try:
            total += await reap_tenant(
                state,
                tenant_id,
                running_grace_seconds=running_grace,
                queued_grace_seconds=queued_grace,
            )
        except Exception as exc:  # noqa: BLE001 — one bad tenant must not stop the rest
            logger.warning(
                "asr.job_reap_tenant_failed",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
    if total:
        logger.info("asr.job_reaper_swept", extra={"reaped": total})
    return total


async def reaper_loop(state: Any, stop: asyncio.Event) -> None:
    """Run :func:`sweep_once` on a timer until ``stop`` is set."""
    interval = float(settings.job_reaper_interval_s)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            await sweep_once(state)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "asr.job_reaper_failed",
                extra={"error": str(exc), "error_class": type(exc).__name__},
            )
