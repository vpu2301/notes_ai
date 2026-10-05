"""Reclaim captures whose client never came back: ``recording``/``uploading``
older than the cutoff become ``no_audio``. Never deletes anything. Hosted behind
``MDX_BACKGROUND_JOBS`` (ADR-0041) plus a ``python -m`` entry point.
"""

from __future__ import annotations

import logging
from uuid import UUID

import asyncpg

from audit import AuditWriter, Severity
from db import tenant_connection

from .. import audit_kinds, meeting_metrics
from ..domain import meetings_repository as meetings

logger = logging.getLogger(__name__)

GLOBAL_TENANT = UUID("00000000-0000-0000-0000-000000000000")
DEFAULT_STALE_HOURS = 12


async def sweep_tenant(
    *, app_pool: asyncpg.Pool, tenant_id: UUID, stale_hours: int = DEFAULT_STALE_HOURS
) -> list[UUID]:
    async with tenant_connection(app_pool, tenant_id) as conn:
        return await meetings.sweep_stale(conn, older_than_hours=stale_hours)


async def run_for_all_tenants(
    *,
    app_pool: asyncpg.Pool,
    audit_writer: AuditWriter,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> dict[str, int]:
    """One scheduler iteration. Idempotent: a swept capture no longer
    matches ``recording|uploading``."""
    async with app_pool.acquire() as conn:
        tenant_rows = await conn.fetch("SELECT public.active_tenant_ids() AS id")
    tenants = [r["id"] for r in tenant_rows]

    swept_total = 0
    for tenant_id in tenants:
        swept = await sweep_tenant(app_pool=app_pool, tenant_id=tenant_id, stale_hours=stale_hours)
        swept_total += len(swept)

    if swept_total:
        meeting_metrics.states_swept.add(swept_total)
    summary = {"tenants_seen": len(tenants), "swept": swept_total}
    await audit_writer.write_event(
        tenant_id=GLOBAL_TENANT,
        kind=audit_kinds.SCHEDULER_JOB_COMPLETED,
        actor_sub=None,
        actor_role="scheduler",
        target_kind="job",
        target_id="meeting_state_sweeper",
        payload=dict(summary),
        severity=Severity.INFO,
    )
    logger.info("meeting_state_sweeper.run_completed", extra=dict(summary))
    return summary


def _main() -> None:  # pragma: no cover — manual/cron ops entrypoint
    """Manual run: uv run --project services/note-service \
    python -m note_service.jobs.meeting_state_sweeper"""
    import asyncio

    from db import create_pool

    from ..config import settings

    async def _run() -> None:
        app_pool = await create_pool(
            settings.db_app_role_dsn,
            application_name="note-service/meeting-state-sweeper",
            min_size=1,
            max_size=2,
        )
        audit_pool = await create_pool(
            settings.db_audit_writer_dsn,
            application_name="note-service/meeting-state-sweeper-audit",
            min_size=1,
            max_size=2,
        )
        try:
            summary = await run_for_all_tenants(
                app_pool=app_pool, audit_writer=AuditWriter(audit_pool)
            )
            print(f"meeting_state_sweeper: {summary}")
        finally:
            await app_pool.close()
            await audit_pool.close()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    _main()
