"""``tenant_connection``: the single sanctioned DB connection; sets ``app.tenant_id`` transaction-locally for RLS (ADR-0004)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# Detects nested tenant_connection on the same task (usually a caller bug).
_in_tenant_scope: ContextVar[UUID | None] = ContextVar("_in_tenant_scope", default=None)


def _coerce_tenant_id(tenant_id: UUID | str) -> UUID:
    if isinstance(tenant_id, UUID):
        return tenant_id
    if not isinstance(tenant_id, str):
        raise TypeError(f"tenant_id must be UUID or str, got {type(tenant_id).__name__}")
    try:
        return UUID(tenant_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"tenant_id is not a valid UUID: {tenant_id!r}") from exc


@asynccontextmanager
async def tenant_connection(
    pool: asyncpg.Pool, tenant_id: UUID | str
) -> AsyncIterator[asyncpg.Connection]:
    """Acquire a tenant-scoped connection in a transaction; ``app.tenant_id`` is transaction-local so it cannot
    leak into pool reuse. Commits on clean exit, rolls back on exception."""
    tid = _coerce_tenant_id(tenant_id)

    parent = _in_tenant_scope.get()
    if parent is not None:
        logger.warning(
            "Nested tenant_connection detected (parent=%s, child=%s). "
            "This is almost always a caller bug — flatten the call chain.",
            parent,
            tid,
        )

    token = _in_tenant_scope.set(tid)
    try:
        async with pool.acquire() as conn:
            tx = conn.transaction()
            await tx.start()
            try:
                # set_config(..., true) is transaction-local and parameterisable; SET LOCAL rejects parameters.
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, true)",
                    str(tid),
                )
                yield conn
            except Exception:
                await tx.rollback()
                raise
            else:
                await tx.commit()
    finally:
        _in_tenant_scope.reset(token)
