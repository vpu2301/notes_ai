"""Step 8 — per-tenant monthly quota check, in the same transaction as the row insert."""

from __future__ import annotations

from uuid import UUID

import asyncpg

from .result import ValidationCode, ValidationResult, ok, reject


async def validate_quota(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    incoming_size_bytes: int,
    monthly_quota_bytes: int,
) -> ValidationResult:
    """Sum the tenant's current-month uploads and reject on overflow.

    Caller holds an RLS-scoped transaction. Advisory, not serialized (Postgres rejects
    FOR UPDATE with aggregates): parallel uploads may overshoot by their in-flight
    sizes; the cap is a billing guard, not a security boundary.
    """
    row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(size_bytes), 0)::BIGINT AS used_bytes
        FROM audio_files
        WHERE created_at >= date_trunc('month', now())
          AND status <> 'deleted'
        """,
    )
    used = int(row["used_bytes"]) if row is not None else 0
    if used + incoming_size_bytes > monthly_quota_bytes:
        return reject(
            ValidationCode.QUOTA_EXCEEDED,
            f"tenant {tenant_id} has used {used} of {monthly_quota_bytes} "
            f"bytes this month; adding {incoming_size_bytes} would exceed.",
        )
    return ok()
