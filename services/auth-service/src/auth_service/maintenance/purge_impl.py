"""The account purge, in one place (IDX-A5 F6 / IDX-B3 D).

Imported by both callers — the scheduled job in :mod:`.jobs` and the
operator CLI `scripts/ops/idx-purge-deleted-identities.py`. An account
deletion that behaved differently depending on whether a timer or a
person triggered it is the worst kind of bug to find out about from a
subject-access request.

What "purge" means, and does not:

* Credentials are destroyed — TOTP secret, recovery codes, password hash.
* The address is rewritten to ``deleted:<id>``, so it can never match a
  login lookup again and the real address is free for reuse.
* Notes keep their author id. A note written in a shared workspace is
  that workspace's history; deleting the person must not silently rewrite
  what colleagues can still see. The author renders as unknown because
  ``profile_of_subs`` returns no row for a ``deleted`` identity.
* The audit trail survives. It is hash-chained, so a deletion inside it
  would break verification for every event after — and by this point it
  refers to nothing but an opaque UUID.
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
    """Everything for one identity, in one transaction.

    Per-identity rather than one big transaction so a crash leaves
    earlier identities purged and later ones untouched, and a re-run is a
    no-op for the ones already done.
    """
    async with conn.transaction():
        # Credentials first: if anything later fails, the account is
        # already unusable rather than half-shredded but still loggable-in.
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
        # The address goes last, because it is what makes the row findable
        # if any of the above needs re-running.
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
