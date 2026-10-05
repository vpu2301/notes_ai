"""SQL for the password-recovery flow.

The ``*_unscoped`` functions run with no ``app.tenant_id`` and go through
SECURITY DEFINER functions, the narrow hole in RLS.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

# ── Account resolution (tenant-blind) ────────────────────────────────


async def resolve_account_by_email(
    conn: asyncpg.Connection, *, email: str
) -> asyncpg.Record | None:
    """Email → (tenant_id, subject_sub, email, display_name, status); tenant-blind by necessity."""
    return await conn.fetchrow("SELECT * FROM public.resolve_account_for_password_reset($1)", email)


async def peek_token(
    conn: asyncpg.Connection, *, token_hash: bytes, purpose: str
) -> asyncpg.Record | None:
    """Resolve a token to (tenant, subject) WITHOUT spending it, so the password can be judged first."""
    return await conn.fetchrow(
        "SELECT * FROM public.peek_password_reset_token($1, $2)",
        token_hash,
        purpose,
    )


async def consume_token(
    conn: asyncpg.Connection, *, token_hash: bytes, purpose: str
) -> asyncpg.Record | None:
    """Atomically claim a token; ``None`` for unknown, spent or expired alike."""
    return await conn.fetchrow(
        "SELECT * FROM public.consume_password_reset_token($1, $2)",
        token_hash,
        purpose,
    )


# ── Token issuance (tenant-scoped) ───────────────────────────────────


async def insert_token(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    subject_sub: UUID,
    token_hash: bytes,
    purpose: str,
    expires_at: datetime,
    requested_ip_hash: str,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO auth_password_reset_tokens
            (tenant_id, subject_sub, token_hash, purpose,
             expires_at, requested_ip_hash)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        tenant_id,
        subject_sub,
        token_hash,
        purpose,
        expires_at,
        requested_ip_hash,
    )
    return UUID(str(row["id"]))


async def spend_all_tokens(conn: asyncpg.Connection, *, subject_sub: UUID) -> int:
    """Spend every live token for a user (after a reset or lockdown); returns how many."""
    result = await conn.execute(
        """
        UPDATE auth_password_reset_tokens
           SET consumed_at = now()
         WHERE subject_sub = $1 AND consumed_at IS NULL
        """,
        subject_sub,
    )
    try:
        return int(str(result).rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


async def sweep_dead_tokens(conn: asyncpg.Connection) -> None:
    """Opportunistic cleanup of this tenant's spent/expired tokens, folded into issuance (no cron)."""
    await conn.execute(
        """
        DELETE FROM auth_password_reset_tokens
         WHERE expires_at < now() - INTERVAL '1 day'
            OR (consumed_at IS NOT NULL
                AND consumed_at < now() - INTERVAL '1 day')
        """
    )


# ── Outbox ───────────────────────────────────────────────────────────


async def enqueue_mail(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    subject_sub: UUID,
    kind: str,
    lang: str,
    to_address: str,
    render_fields: dict[str, Any],
    secret_fields: dict[str, Any],
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO auth_mail_outbox
            (tenant_id, subject_sub, kind, lang, to_address,
             render_fields, secret_fields)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
        RETURNING id
        """,
        tenant_id,
        subject_sub,
        kind,
        lang,
        to_address,
        json.dumps(render_fields),
        json.dumps(secret_fields),
    )
    return UUID(str(row["id"]))


async def claim_due_mail(conn: asyncpg.Connection) -> asyncpg.Record | None:
    """Take one due row with ``SKIP LOCKED``; one row per transaction (a batch per transaction loses mail)."""
    return await conn.fetchrow(
        """
        SELECT id, tenant_id, subject_sub, kind, lang, to_address,
               render_fields, secret_fields, attempt_count
          FROM auth_mail_outbox
         WHERE status = 'pending' AND next_attempt_at <= now()
         ORDER BY next_attempt_at
         FOR UPDATE SKIP LOCKED
         LIMIT 1
        """
    )


async def mark_sent(conn: asyncpg.Connection, *, mail_id: UUID, provider_message_id: str) -> None:
    """Record the send AND clear ``secret_fields`` in one statement (a CHECK constraint enforces it)."""
    await conn.execute(
        """
        UPDATE auth_mail_outbox
           SET status = 'sent',
               sent_at = now(),
               secret_fields = NULL,
               provider_message_id = $2,
               last_error = ''
         WHERE id = $1
        """,
        mail_id,
        provider_message_id,
    )


async def mark_dead(conn: asyncpg.Connection, *, mail_id: UUID, error: str) -> None:
    await conn.execute(
        """
        UPDATE auth_mail_outbox
           SET status = 'dead',
               secret_fields = NULL,
               last_error = $2
         WHERE id = $1
        """,
        mail_id,
        error[:1000],
    )


async def mark_retry(
    conn: asyncpg.Connection, *, mail_id: UUID, error: str, delay_seconds: float
) -> None:
    await conn.execute(
        """
        UPDATE auth_mail_outbox
           SET attempt_count = attempt_count + 1,
               next_attempt_at = now() + make_interval(secs => $3),
               last_error = $2
         WHERE id = $1
        """,
        mail_id,
        error[:1000],
        float(delay_seconds),
    )


async def tenants_with_due_mail(conn: asyncpg.Connection) -> list[UUID]:
    """Tenants with deliverable mail, via the SECURITY DEFINER function: an unscoped
    ``app_role`` SELECT sees zero rows through RLS and no mail would ever be sent."""
    rows = await conn.fetch("SELECT * FROM public.tenants_with_due_auth_mail($1)", 100)
    return [UUID(str(r["tenant_id"])) for r in rows]


# ── Security-activity projection ─────────────────────────────────────


async def record_password_event(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    subject_sub: UUID,
    kind: str,
    via: str,
    ip_hash: str,
    client_label: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO auth_password_events
            (tenant_id, subject_sub, kind, via, ip_hash, client_label)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        tenant_id,
        subject_sub,
        kind,
        via,
        ip_hash,
        client_label,
    )


async def recent_password_events(
    conn: asyncpg.Connection, *, subject_sub: UUID, limit: int = 20
) -> list[asyncpg.Record]:
    return list(
        await conn.fetch(
            """
            SELECT kind, via, client_label, created_at
              FROM auth_password_events
             WHERE subject_sub = $1
             ORDER BY created_at DESC
             LIMIT $2
            """,
            subject_sub,
            limit,
        )
    )
