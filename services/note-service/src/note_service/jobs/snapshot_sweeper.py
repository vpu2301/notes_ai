"""Transcript snapshots that outlived their generation (a worker killed mid-run
never deleted its own): anything older than a day is debris. Hosted behind
``MDX_BACKGROUND_JOBS`` (ADR-0041) plus a ``python -m`` entry point.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import asyncpg

from audit import AuditWriter, Severity
from db import tenant_connection

from .. import audit_kinds
from ..domain import generation_repository as gen_repo

logger = logging.getLogger(__name__)

GLOBAL_TENANT = UUID("00000000-0000-0000-0000-000000000000")
DEFAULT_STALE_HOURS = 24


async def sweep_tenant(
    *,
    app_pool: asyncpg.Pool,
    store: Any,
    tenant_id: UUID,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> int:
    """Delete this tenant's orphaned snapshots, row first then object. Returns how many."""
    swept = 0
    async with tenant_connection(app_pool, tenant_id) as conn:
        stale = await gen_repo.stale_snapshots(conn, older_than_hours=stale_hours)
    for generation_id, _key in stale:
        try:
            async with tenant_connection(app_pool, tenant_id) as conn:
                cleared = await gen_repo.clear_snapshot(conn, generation_id=generation_id)
            if cleared:
                await store.delete(key=cleared)
                swept += 1
        except Exception:  # noqa: BLE001 — one bad object must not stop the sweep
            logger.warning("snapshot_sweeper.delete_failed", exc_info=True)
    return swept


async def run_for_all_tenants(
    *,
    app_pool: asyncpg.Pool,
    store: Any,
    audit_writer: AuditWriter,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> dict[str, int]:
    """One scheduler iteration. Idempotent — a swept snapshot has no row
    pointing at it any more."""
    async with app_pool.acquire() as conn:
        tenants = [r["id"] for r in await conn.fetch("SELECT public.active_tenant_ids() AS id")]

    swept = 0
    for tenant_id in tenants:
        swept += await sweep_tenant(
            app_pool=app_pool, store=store, tenant_id=tenant_id, stale_hours=stale_hours
        )

    summary = {"tenants_seen": len(tenants), "swept": swept}
    await audit_writer.write_event(
        tenant_id=GLOBAL_TENANT,
        kind=audit_kinds.SCHEDULER_JOB_COMPLETED,
        actor_sub=None,
        actor_role="scheduler",
        target_kind="job",
        target_id="snapshot_sweeper",
        payload=dict(summary),
        severity=Severity.INFO,
    )
    logger.info("snapshot_sweeper.run_completed", extra=dict(summary))
    return summary


def _main() -> None:  # pragma: no cover — manual/cron ops entrypoint
    """Manual run: uv run --project services/note-service \
    python -m note_service.jobs.snapshot_sweeper"""
    import asyncio

    from ..main_deps import build_state, teardown_state

    async def _run() -> None:
        # `build_state` is the one place that wires the envelope and pools.
        state = await build_state()
        try:
            summary = await run_for_all_tenants(
                app_pool=state.app_pool,
                store=state.transcripts_store,
                audit_writer=state.audit_writer,
            )
            print(f"snapshot_sweeper: {summary}")
        finally:
            await teardown_state(state)

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    _main()
