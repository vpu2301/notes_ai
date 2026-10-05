"""The account purge, shared by the scheduled job and the operator CLI.

Credentials are destroyed; the address becomes ``deleted:<id>``; notes keep
their author id; the hash-chained audit trail survives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

GRACE_DAYS = 30
PLATFORM_TENANT = UUID("00000000-0000-0000-0000-0000000000f1")


async def due_identities(
    conn: asyncpg.Connection, *, grace_days: int = GRACE_DAYS
) -> list[asyncpg.Record]:
    cutoff = datetime.now(UTC) - timedelta(days=grace_days)
    return list(
        await conn.fetch(
            """
            SELECT id, deletion_requested_at
            FROM identities
            WHERE status = 'pending_deletion' AND deletion_requested_at < $1
            ORDER BY deletion_requested_at
            """,
            cutoff,
        )
    )


async def purge_one(conn: asyncpg.Connection, identity_id: UUID) -> None:
    """Everything for one identity, in one transaction (a re-run is a no-op for ones already done)."""
    async with conn.transaction():
        # Credentials first: a partial failure leaves the account unusable, not loggable-in.
        await conn.execute("DELETE FROM identity_totp WHERE identity_id = $1", identity_id)
        await conn.execute(
            "DELETE FROM identity_recovery_codes WHERE identity_id = $1", identity_id
        )
        await conn.execute(
            "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, now()),"
            " revoked_reason = COALESCE(revoked_reason, 'account_deleted')"
            " WHERE identity_id = $1",
            identity_id,
        )
        await conn.execute("DELETE FROM auth_challenges WHERE identity_id = $1", identity_id)
        await conn.execute(
            "UPDATE tenant_memberships SET status = 'suspended' WHERE user_sub = $1",
            identity_id,
        )
        # The address goes last: it keeps the row findable for a re-run.
        await conn.execute(
            """
            UPDATE identities
            SET email = 'deleted:' || id::text,
                display_name = '',
                password_hash = NULL,
                mfa_enabled = false,
                last_tenant_id = NULL,
                status = 'deleted'
            WHERE id = $1
            """,
            identity_id,
        )
