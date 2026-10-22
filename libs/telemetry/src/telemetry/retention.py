"""Retention (STORAGE.md §3): delete runs past ``retention_until`` (children cascade) and close
runs left ``queued``/``running`` with no activity — evidence kept, nothing invented. Telemetry
only; per tenant on a tenant-scoped connection; idempotent; counts only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from db import tenant_connection

BATCH = 1000
STALE_HOURS = 6

# Tenants that hold telemetry, through the ids-only SECURITY DEFINER function (0094): app_role
# sees no `tenants` row outside a tenant context (sprint 5: the job found none and deleted nothing).
_TENANTS = (
    "SELECT t AS tenant_id FROM telemetry_tenants('-infinity'::timestamptz,"
    " 'infinity'::timestamptz) AS t"
)
_DELETE = """
DELETE FROM telemetry_runs WHERE processing_run_id IN (
    SELECT processing_run_id FROM telemetry_runs
     WHERE retention_until < now() ORDER BY retention_until LIMIT $1)
"""
_CLOSE_STALE = """
UPDATE telemetry_runs r
   SET status = 'failed', error_category = 'unknown', finished_at = now()
 WHERE r.status IN ('queued', 'running')
   AND r.submitted_at < now() - make_interval(hours => $1)
   AND NOT EXISTS (
       SELECT 1 FROM telemetry_spans s
        WHERE s.processing_run_id = r.processing_run_id
          AND COALESCE(s.end_wall_utc, s.start_wall_utc) > now() - make_interval(hours => $1))
"""


@dataclass
class PurgeResult:
    tenants: int = 0
    deleted_runs: int = 0
    closed_stale_runs: int = 0


def _count(status: str | None) -> int:
    return int(status.split()[-1]) if status else 0


async def purge(pool: Any, *, batch: int = BATCH, stale_hours: int = STALE_HOURS) -> PurgeResult:
    result = PurgeResult()
    async with pool.acquire() as conn:
        tenant_ids: list[UUID] = [r["tenant_id"] for r in await conn.fetch(_TENANTS)]
    for tenant_id in tenant_ids:
        result.tenants += 1
        while True:
            async with tenant_connection(pool, tenant_id) as conn:
                n = _count(await conn.execute(_DELETE, batch))
            result.deleted_runs += n
            if n < batch:
                break
        async with tenant_connection(pool, tenant_id) as conn:
            result.closed_stale_runs += _count(await conn.execute(_CLOSE_STALE, stale_hours))
    return result
