"""SQL for `tenant_invitations` (W2, ADR-0070).

Everything runs on ``tenant_writer``: the invitee side reads across tenants by
the caller's own address, never by a client-supplied tenant id. Tokens are
stored as a sha256 hash only; the raw token exists in the mail and nowhere else.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

# A workspace invitation has no note; the live index coalesces NULL to this.
_NO_NOTE = "00000000-0000-0000-0000-000000000000"

_COLUMNS = """
    i.id, i.tenant_id, i.email, i.role, i.note_id, i.note_role, i.invited_by,
    i.message, i.lang, i.expires_at, i.sent_count, i.last_sent_at, i.accepted_at,
    i.accepted_by, i.revoked_at, i.revoked_by, i.created_at,
    CASE
        WHEN i.accepted_at IS NOT NULL THEN 'accepted'
        WHEN i.revoked_at IS NOT NULL THEN 'revoked'
        WHEN i.expires_at <= now() THEN 'expired'
        ELSE 'pending'
    END AS status,
    t.display_name AS workspace_name, t.kind AS workspace_kind,
    coalesce(nullif(inv.display_name, ''), split_part(inv.email, '@', 1)) AS invited_by_display
"""

_FROM = """
    FROM tenant_invitations i
    JOIN tenants t ON t.id = i.tenant_id
    JOIN identities inv ON inv.id = i.invited_by
"""

_LIVE = "i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now()"

STATUSES: frozenset[str] = frozenset({"pending", "accepted", "revoked", "expired"})


def new_token() -> tuple[str, bytes]:
    """32 random bytes, urlsafe; only the hash is stored."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class InvitationRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── management (one workspace) ───────────────────────────────────

    async def upsert_live(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: str,
        invited_by: UUID,
        message: str,
        lang: str,
        token_hash: bytes,
        expires_at: datetime,
        note_id: UUID | None = None,
        note_role: str | None = None,
    ) -> tuple[asyncpg.Record, bool]:
        """Create the live invitation, or re-arm the existing one with a fresh token; (row, created).

        One live row per (workspace, address, note): a W3 note invitation is its own row.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchval(
                """
                SELECT id FROM tenant_invitations
                 WHERE tenant_id = $1 AND email = $2 AND note_id IS NOT DISTINCT FROM $3
                   AND accepted_at IS NULL AND revoked_at IS NULL
                 FOR UPDATE
                """,
                tenant_id,
                email,
                note_id,
            )
            if existing is not None:
                # Re-inviting re-arms: a new token (the old link stops working), a new window, the newest role.
                await conn.execute(
                    """
                    UPDATE tenant_invitations
                       SET token_hash = $2, expires_at = $3, role = $4, message = $5, lang = $6,
                           note_role = $7
                     WHERE id = $1
                    """,
                    existing,
                    token_hash,
                    expires_at,
                    role,
                    message,
                    lang,
                    note_role,
                )
                row = await self._get(conn, existing)
                return row, False
            new_id = await conn.fetchval(
                """
                INSERT INTO tenant_invitations
                    (tenant_id, email, role, invited_by, token_hash, message, lang, expires_at,
                     note_id, note_role)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                tenant_id,
                email,
                role,
                invited_by,
                token_hash,
                message,
                lang,
                expires_at,
                note_id,
                note_role,
            )
            row = await self._get(conn, new_id)
            return row, True

    async def rearm(
        self, *, tenant_id: UUID, invitation_id: UUID, token_hash: bytes, expires_at: datetime
    ) -> asyncpg.Record | None:
        """A new token and window for a pending invitation (resend); None when it is not pending."""
        async with self._pool.acquire() as conn:
            updated = await conn.fetchval(
                """
                UPDATE tenant_invitations i SET token_hash = $3, expires_at = $4
                 WHERE i.id = $1 AND i.tenant_id = $2 AND i.note_id IS NULL
                   AND i.accepted_at IS NULL AND i.revoked_at IS NULL
                RETURNING i.id
                """,
                invitation_id,
                tenant_id,
                token_hash,
                expires_at,
            )
            return await self._get(conn, updated) if updated is not None else None

    async def mark_sent(self, invitation_id: UUID) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tenant_invitations
                   SET sent_count = sent_count + 1, last_sent_at = now()
                 WHERE id = $1
                """,
                invitation_id,
            )
            return await self._get(conn, invitation_id)

    async def get(self, *, tenant_id: UUID, invitation_id: UUID) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            row = await self._get(conn, invitation_id)
        return row if row is not None and row["tenant_id"] == tenant_id else None

    async def list_for_tenant(self, *, tenant_id: UUID, status: str) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_COLUMNS} {_FROM} WHERE i.tenant_id = $1 AND i.note_id IS NULL "
                "ORDER BY i.created_at DESC LIMIT 500",
                tenant_id,
            )
        return [r for r in rows if r["status"] == status]

    async def revoke(
        self, *, tenant_id: UUID, invitation_id: UUID, revoked_by: UUID
    ) -> asyncpg.Record | None:
        """Revoke a not-yet-accepted invitation; None when it is accepted/revoked already."""
        async with self._pool.acquire() as conn:
            done = await conn.fetchval(
                """
                UPDATE tenant_invitations SET revoked_at = now(), revoked_by = $3
                 WHERE id = $1 AND tenant_id = $2 AND accepted_at IS NULL AND revoked_at IS NULL
                RETURNING id
                """,
                invitation_id,
                tenant_id,
                revoked_by,
            )
            return await self._get(conn, done) if done is not None else None

    async def revoke_all_for_tenant(self, tenant_id: UUID, *, revoked_by: UUID) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tenant_invitations SET revoked_at = now(), revoked_by = $2
                 WHERE tenant_id = $1 AND accepted_at IS NULL AND revoked_at IS NULL
                """,
                tenant_id,
                revoked_by,
            )
        return int(result.split()[-1])

    async def revoke_sent_by(self, identity_id: UUID) -> int:
        """Account deletion: open invitations the person sent stop working."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tenant_invitations SET revoked_at = now(), revoked_by = $1
                 WHERE invited_by = $1 AND accepted_at IS NULL AND revoked_at IS NULL
                """,
                identity_id,
            )
        return int(result.split()[-1])

    async def is_active_member(self, *, tenant_id: UUID, email: str) -> bool:
        async with self._pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM tenant_memberships m
                          JOIN identities i ON i.id = m.user_sub
                         WHERE m.tenant_id = $1 AND i.email = $2 AND m.status = 'active')
                    """,
                    tenant_id,
                    email,
                )
            )

    async def identity_id_for(self, email: str) -> UUID | None:
        async with self._pool.acquire() as conn:
            value = await conn.fetchval(
                "SELECT id FROM identities WHERE email = $1 AND status <> 'deleted'", email
            )
        return value if isinstance(value, UUID) else None

    async def personal_tenant_of(self, identity_id: UUID) -> UUID | None:
        async with self._pool.acquire() as conn:
            value = await conn.fetchval(
                """
                SELECT m.tenant_id FROM tenant_memberships m
                  JOIN tenants t ON t.id = m.tenant_id
                 WHERE m.user_sub = $1 AND t.kind = 'personal' AND m.status = 'active'
                 LIMIT 1
                """,
                identity_id,
            )
        return value if isinstance(value, UUID) else None

    # ── the invitee side (by token or by the caller's own address) ───

    async def find_live_by_token(self, token: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT {_COLUMNS} {_FROM} WHERE i.token_hash = $1 AND {_LIVE} "
                "AND t.status = 'active'",
                hash_token(token),
            )

    async def list_live_for_email(self, email: str) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return list(
                await conn.fetch(
                    f"SELECT {_COLUMNS} {_FROM} WHERE i.email = $1 "
                    f"AND {_LIVE} AND t.status = 'active' ORDER BY i.created_at",
                    email,
                )
            )

    async def get_live_for_email(self, invitation_id: UUID, email: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT {_COLUMNS} {_FROM} WHERE i.id = $1 AND i.email = $2 AND {_LIVE} "
                "AND t.status = 'active'",
                invitation_id,
                email,
            )

    async def accept(
        self, *, invitation_id: UUID, identity_id: UUID
    ) -> tuple[asyncpg.Record, str] | None:
        """Mark accepted and grant the membership in one transaction; (membership, outcome) or None.

        The conditional UPDATE decides races with a revoke. An active member keeps their role
        (joining twice is not an error); a suspended/left row is reactivated with the invited role.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            inv = await conn.fetchrow(
                """
                UPDATE tenant_invitations SET accepted_at = now(), accepted_by = $2
                 WHERE id = $1 AND accepted_at IS NULL AND revoked_at IS NULL
                   AND expires_at > now()
                   AND EXISTS (SELECT 1 FROM tenants t
                                WHERE t.id = tenant_invitations.tenant_id AND t.status = 'active')
                RETURNING tenant_id, role, invited_by, note_id
                """,
                invitation_id,
                identity_id,
            )
            if inv is None:
                return None
            existing = await conn.fetchrow(
                "SELECT status FROM tenant_memberships WHERE tenant_id = $1 AND user_sub = $2",
                inv["tenant_id"],
                identity_id,
            )
            outcome = (
                "already_member"
                if existing is not None and existing["status"] == "active"
                else "rejoined"
                if existing is not None
                else "joined"
            )
            membership = await conn.fetchrow(
                """
                INSERT INTO tenant_memberships (tenant_id, user_sub, role, status, invited_by)
                VALUES ($1, $2, $3, 'active', $4)
                ON CONFLICT (tenant_id, user_sub) DO UPDATE
                   SET role = CASE WHEN tenant_memberships.status = 'active'
                                   THEN tenant_memberships.role ELSE EXCLUDED.role END,
                       status = 'active',
                       left_at = NULL,
                       invited_by = CASE WHEN tenant_memberships.status = 'active'
                                         THEN tenant_memberships.invited_by
                                         ELSE EXCLUDED.invited_by END
                RETURNING tenant_id, user_sub, role, status
                """,
                inv["tenant_id"],
                identity_id,
                inv["role"],
                inv["invited_by"],
            )
            if inv["note_id"] is not None:
                # W3: the note grant, through note-service's one sanctioned cross-service
                # write; it re-checks the accepted row and that the note still exists.
                await conn.fetchval(
                    "SELECT public.grant_note_collaborator($1, $2)", invitation_id, identity_id
                )
            return membership, outcome

    async def can_manage_note(self, *, tenant_id: UUID, note_id: UUID, sub: UUID) -> bool:
        async with self._pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    "SELECT public.can_manage_note($1, $2, $3)", tenant_id, note_id, sub
                )
            )

    async def decline(self, *, invitation_id: UUID, email: str, identity_id: UUID) -> bool:
        async with self._pool.acquire() as conn:
            done = await conn.fetchval(
                """
                UPDATE tenant_invitations SET revoked_at = now(), revoked_by = $3
                 WHERE id = $1 AND email = $2 AND accepted_at IS NULL AND revoked_at IS NULL
                RETURNING id
                """,
                invitation_id,
                email,
                identity_id,
            )
        return done is not None

    # ── housekeeping ─────────────────────────────────────────────────

    async def sweep(self, *, older_than_days: int = 90) -> int:
        """Delete revoked and expired-unaccepted rows past the retention window (the address is PII)."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM tenant_invitations
                 WHERE accepted_at IS NULL
                   AND coalesce(revoked_at, expires_at) < now() - ($1::int * interval '1 day')
                """,
                older_than_days,
            )
        return int(result.split()[-1])

    @staticmethod
    async def _get(conn: Any, invitation_id: UUID) -> asyncpg.Record | None:
        return await conn.fetchrow(f"SELECT {_COLUMNS} {_FROM} WHERE i.id = $1", invitation_id)
