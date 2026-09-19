"""Notes + note_versions repository (sprint-08).

All queries run on a tenant-scoped connection (``app.tenant_id`` set
by ``db.tenant_connection``). RLS does the rest.

The repository is deliberately a thin SQL wrapper — domain rules
(state machine, finalize validation, optimistic check) live in
sibling modules. This makes the property test in
``tests/property/test_amendment_chain.py`` straightforward.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from note_models import (
    NoteAmendmentType,
    NoteContent,
    NoteStatus,
    canonical_content_bytes,
    rendered_text_from_content,
)

logger = logging.getLogger(__name__)


def body_hash_for(content: NoteContent) -> str:
    """sha256 of the canonical body — used for autosave idempotency."""
    return hashlib.sha256(canonical_content_bytes(content)).hexdigest()


@dataclass(slots=True)
class NoteRow:
    id: UUID
    tenant_id: UUID
    code: str
    status: NoteStatus
    current_version_id: UUID
    current_version_number: int
    primary_author_id: UUID
    co_author_ids: list[UUID]
    title: str
    created_at: datetime
    updated_at: datetime
    finalized_at: datetime | None
    cancelled_at: datetime | None
    source_session_id: UUID | None = None
    # The transcription job this note was made from, when it was.
    source_asr_job_id: UUID | None = None
    # 0016 — who may read it beyond the author team, and whether it is
    # in the bin. Defaults keep older call sites and fixtures valid.
    visibility: str = "workspace"
    shared_with_ids: list[UUID] = field(default_factory=list)
    deleted_at: datetime | None = None


@dataclass(slots=True)
class VersionRow:
    id: UUID
    note_id: UUID
    version_number: int
    parent_version_id: UUID | None
    created_by: UUID
    created_at: datetime
    content: NoteContent
    rendered_text: str
    body_hash: str | None
    is_amendment: bool
    amendment_type: NoteAmendmentType | None
    amendment_reason: str | None


# ── Read ────────────────────────────────────────────────────────────


async def fetch_note(
    conn: asyncpg.Connection, *, note_id: UUID, include_deleted: bool = False
) -> NoteRow | None:
    """The note, or ``None`` when it does not exist — or has been deleted.

    Every reader and writer goes through here (directly or via
    :func:`lock_note_for_update`), so excluding the bin at this one
    point is what makes a deleted note vanish from every endpoint at
    once. ``include_deleted`` is for the few callers that need to see
    it (an admin restore, an audit read).
    """
    row = await conn.fetchrow(
        """
        SELECT n.id, n.tenant_id, n.code, n.status,
               n.current_version_id, v.version_number AS current_version_number,
               n.primary_author_id, n.co_author_ids,
               n.title, n.created_at, n.updated_at, n.finalized_at,
               n.cancelled_at, n.source_session_id, n.source_asr_job_id,
               n.visibility, n.shared_with_ids, n.deleted_at
        FROM notes n
        LEFT JOIN note_versions v ON v.id = n.current_version_id
        WHERE n.id = $1
        """,
        note_id,
    )
    if row is None:
        return None
    if row["deleted_at"] is not None and not include_deleted:
        return None
    return NoteRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        code=row["code"],
        status=NoteStatus(row["status"]),
        current_version_id=row["current_version_id"],
        current_version_number=int(row["current_version_number"] or 0),
        primary_author_id=row["primary_author_id"],
        co_author_ids=list(row["co_author_ids"] or []),
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        finalized_at=row["finalized_at"],
        cancelled_at=row["cancelled_at"],
        source_session_id=row["source_session_id"],
        source_asr_job_id=row["source_asr_job_id"],
        visibility=str(row["visibility"]),
        shared_with_ids=list(row["shared_with_ids"] or []),
        deleted_at=row["deleted_at"],
    )


# ── 0016: visibility, sharing, delete ────────────────────────────────


async def set_visibility(conn: asyncpg.Connection, *, note_id: UUID, visibility: str) -> None:
    await conn.execute(
        "UPDATE notes SET visibility = $2::note_visibility, updated_at = now() WHERE id = $1",
        note_id,
        visibility,
    )


async def add_shared_with(conn: asyncpg.Connection, *, note_id: UUID, user_sub: UUID) -> None:
    """Idempotent: sharing twice with the same person is one grant."""
    await conn.execute(
        """
        UPDATE notes
        SET shared_with_ids = array_append(shared_with_ids, $2), updated_at = now()
        WHERE id = $1 AND NOT ($2 = ANY(shared_with_ids))
        """,
        note_id,
        user_sub,
    )


async def remove_shared_with(conn: asyncpg.Connection, *, note_id: UUID, user_sub: UUID) -> None:
    await conn.execute(
        """
        UPDATE notes
        SET shared_with_ids = array_remove(shared_with_ids, $2), updated_at = now()
        WHERE id = $1
        """,
        note_id,
        user_sub,
    )


async def soft_delete_note(conn: asyncpg.Connection, *, note_id: UUID, actor_sub: UUID) -> None:
    """Move the note to the bin and kill its public links in one go."""
    await conn.execute(
        """
        UPDATE notes SET deleted_at = now(), deleted_by = $2, updated_at = now()
        WHERE id = $1 AND deleted_at IS NULL
        """,
        note_id,
        actor_sub,
    )
    await conn.execute(
        """
        UPDATE note_share_links
        SET revoked_at = now(), revoked_by = $2, recipient_email = NULL
        WHERE note_id = $1 AND revoked_at IS NULL
        """,
        note_id,
        actor_sub,
    )
    # Sprint 20: recipient responses go unreachable with the note. The
    # rows stay for audit; every read path filters on cleared_at.
    await conn.execute(
        """
        UPDATE share_link_responses SET cleared_at = now(), cleared_by = $2
        WHERE note_id = $1 AND cleared_at IS NULL
        """,
        note_id,
        actor_sub,
    )


async def fetch_tenant_locale(conn: asyncpg.Connection, *, tenant_id: UUID) -> str:
    value = await conn.fetchval("SELECT locale FROM tenants WHERE id = $1", tenant_id)
    return str(value or "en")


async def fetch_tenant_timezone(conn: asyncpg.Connection, *, tenant_id: UUID) -> str:
    value = await conn.fetchval("SELECT timezone FROM tenants WHERE id = $1", tenant_id)
    return str(value or "UTC")


@dataclass(slots=True)
class MemberRow:
    sub: UUID
    email: str
    display_name: str


async def find_member_by_email(conn: asyncpg.Connection, *, email: str) -> MemberRow | None:
    """A workspace member by e-mail, scoped to the caller's tenant.

    Reads `identities` through `profile_of_subs` (IDX-B2) rather than the
    per-tenant `users` table. The difference that matters: `users` has one
    row per principal in its HOME tenant, so a colleague invited into this
    workspace from another one was simply not found here — sharing a note
    with them failed with "no such member". The helper resolves anyone
    with an active membership in this tenant, wherever they came from.

    The candidate subs come from `tenant_memberships`, which `app_role`
    can already read within its own tenant, so the address comparison
    happens over this workspace's members and nobody else's.
    """
    rows = await conn.fetch(
        """
        SELECT p.sub, p.display_name, p.email
        FROM profile_of_subs(
                 ARRAY(SELECT user_sub FROM tenant_memberships WHERE status = 'active')
             ) p
        WHERE lower(p.email) = lower($1) AND p.status = 'active'
        LIMIT 1
        """,
        email.strip(),
    )
    if not rows:
        return None
    row = rows[0]
    return MemberRow(sub=row["sub"], email=row["email"], display_name=row["display_name"])


async def fetch_members(conn: asyncpg.Connection, *, subs: list[UUID]) -> list[MemberRow]:
    """Profiles for a page of subs — one query, no N+1 (IDX-B2 F2).

    Same change as `find_member_by_email`: a co-author who lives in
    another workspace used to render blank here, because the LEFT JOIN
    onto per-tenant `users` found nothing for them.
    """
    if not subs:
        return []
    rows = await conn.fetch(
        "SELECT sub, display_name, email FROM profile_of_subs($1::uuid[]) ORDER BY display_name",
        subs,
    )
    return [MemberRow(sub=r["sub"], email=r["email"], display_name=r["display_name"]) for r in rows]


@dataclass(slots=True)
class ShareLinkRow:
    id: UUID
    note_id: UUID
    created_by: UUID
    created_at: datetime
    expires_at: datetime | None
    last_viewed_at: datetime | None
    view_count: int
    # 0035 — per-recipient links. Defaults keep older fixtures valid.
    kind: str = "public"
    label: str = ""
    recipient_email: str | None = None
    draft_acknowledged: bool = False
    first_viewed_at: datetime | None = None
    cta_clicked_at: datetime | None = None
    ref_code: str | None = None
    # 0039 — the product mailed the link.
    delivery_status: str = "not_sent"
    sent_at: datetime | None = None
    send_count: int = 0
    last_send_error: str = ""
    revoked_at: datetime | None = None
    # 0041 — verified recipient, and the version they last looked at.
    verified_at: datetime | None = None
    last_seen_version_id: UUID | None = None


_LINK_COLUMNS = (
    "id, note_id, created_by, created_at, expires_at, last_viewed_at, view_count, "
    "kind, label, recipient_email, draft_acknowledged, first_viewed_at, cta_clicked_at, ref_code, "
    "delivery_status::text AS delivery_status, sent_at, send_count, last_send_error, revoked_at, "
    "verified_at, last_seen_version_id"
)


def _link_row(row: asyncpg.Record) -> ShareLinkRow:
    return ShareLinkRow(
        id=row["id"],
        note_id=row["note_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        last_viewed_at=row["last_viewed_at"],
        view_count=int(row["view_count"]),
        kind=str(row["kind"]),
        label=row["label"],
        recipient_email=row["recipient_email"],
        draft_acknowledged=bool(row["draft_acknowledged"]),
        first_viewed_at=row["first_viewed_at"],
        cta_clicked_at=row["cta_clicked_at"],
        ref_code=row["ref_code"],
        delivery_status=str(row["delivery_status"]),
        sent_at=row["sent_at"],
        send_count=int(row["send_count"]),
        last_send_error=row["last_send_error"] or "",
        revoked_at=row["revoked_at"],
        verified_at=row["verified_at"],
        last_seen_version_id=row["last_seen_version_id"],
    )


async def fetch_live_share_link(conn: asyncpg.Connection, *, note_id: UUID) -> ShareLinkRow | None:
    """The note's live PUBLIC ("anyone with the link") link, if any."""
    row = await conn.fetchrow(
        f"""
        SELECT {_LINK_COLUMNS}
        FROM note_share_links
        WHERE note_id = $1 AND revoked_at IS NULL AND kind = 'public'
          AND (expires_at IS NULL OR expires_at > now())
        """,
        note_id,
    )
    return _link_row(row) if row is not None else None


async def fetch_share_link(conn: asyncpg.Connection, *, link_id: UUID) -> ShareLinkRow | None:
    row = await conn.fetchrow(
        f"SELECT {_LINK_COLUMNS} FROM note_share_links WHERE id = $1", link_id
    )
    return _link_row(row) if row is not None else None


async def list_live_share_links(conn: asyncpg.Connection, *, note_id: UUID) -> list[ShareLinkRow]:
    """Every live link on the note, newest first — public and recipient."""
    rows = await conn.fetch(
        f"""
        SELECT {_LINK_COLUMNS}
        FROM note_share_links
        WHERE note_id = $1 AND revoked_at IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        ORDER BY created_at DESC
        """,
        note_id,
    )
    return [_link_row(r) for r in rows]


async def find_live_recipient_link(
    conn: asyncpg.Connection, *, note_id: UUID, recipient_email: str
) -> ShareLinkRow | None:
    """The live recipient link already minted for this address, if any."""
    row = await conn.fetchrow(
        f"""
        SELECT {_LINK_COLUMNS}
        FROM note_share_links
        WHERE note_id = $1 AND revoked_at IS NULL AND kind = 'recipient'
          AND lower(recipient_email) = lower($2)
          AND (expires_at IS NULL OR expires_at > now())
        ORDER BY created_at DESC
        LIMIT 1
        """,
        note_id,
        recipient_email,
    )
    return _link_row(row) if row is not None else None


async def create_share_link(
    conn: asyncpg.Connection,
    *,
    link_id: UUID,
    tenant_id: UUID,
    note_id: UUID,
    token_hash: str,
    created_by: UUID,
    expires_at: datetime | None,
    kind: str = "public",
    label: str = "",
    recipient_email: str | None = None,
    draft_acknowledged: bool = False,
    ref_code: str | None = None,
) -> ShareLinkRow:
    row = await conn.fetchrow(
        f"""
        INSERT INTO note_share_links
            (id, tenant_id, note_id, token_hash, created_by, expires_at,
             kind, label, recipient_email, draft_acknowledged, ref_code)
        VALUES ($1, $2, $3, $4, $5, $6, $7::share_link_kind, $8, $9, $10, $11)
        RETURNING {_LINK_COLUMNS}
        """,
        link_id,
        tenant_id,
        note_id,
        token_hash,
        created_by,
        expires_at,
        kind,
        label,
        recipient_email,
        draft_acknowledged,
        ref_code,
    )
    assert row is not None
    return _link_row(row)


async def revoke_share_links(conn: asyncpg.Connection, *, note_id: UUID, actor_sub: UUID) -> int:
    """Revoke every live link on the note. The recipient address is
    dropped with the link: once nobody can open it, there is nothing
    left to label."""
    result = await conn.execute(
        """
        UPDATE note_share_links
        SET revoked_at = now(), revoked_by = $2, recipient_email = NULL
        WHERE note_id = $1 AND revoked_at IS NULL
        """,
        note_id,
        actor_sub,
    )
    # asyncpg returns "UPDATE n".
    return int(result.split()[-1]) if result else 0


async def revoke_share_link(
    conn: asyncpg.Connection, *, note_id: UUID, link_id: UUID, actor_sub: UUID
) -> bool:
    """Revoke one link. Queried with both ids so a link id from another
    note (or another tenant, which RLS already hides) is a no-op."""
    result = await conn.execute(
        """
        UPDATE note_share_links
        SET revoked_at = now(), revoked_by = $3, recipient_email = NULL
        WHERE note_id = $1 AND id = $2 AND revoked_at IS NULL
        """,
        note_id,
        link_id,
        actor_sub,
    )
    return bool(result) and result.split()[-1] == "1"


async def resolve_share_link(
    conn: asyncpg.Connection, *, token_hash: str
) -> tuple[UUID, UUID, UUID] | None:
    """(tenant_id, note_id, link_id) for a live token, without a tenant
    context — the SECURITY DEFINER function from migration 0016."""
    row = await conn.fetchrow("SELECT * FROM public.resolve_note_share_link($1)", token_hash)
    if row is None:
        return None
    return row["tenant_id"], row["note_id"], row["link_id"]


async def record_share_link_view(conn: asyncpg.Connection, *, link_id: UUID) -> bool:
    """Count a read. Returns True on the FIRST open of the link — the
    "reached the recipient" signal the loop funnel starts from."""
    row = await conn.fetchrow(
        """
        UPDATE note_share_links
        SET view_count = view_count + 1,
            last_viewed_at = now(),
            first_viewed_at = COALESCE(first_viewed_at, now())
        WHERE id = $1
        RETURNING view_count
        """,
        link_id,
    )
    return row is not None and int(row["view_count"]) == 1


async def record_cta_click(conn: asyncpg.Connection, *, link_id: UUID) -> bool:
    """Stamp the first CTA click; later clicks change nothing. Returns
    True when this call set it."""
    result = await conn.execute(
        "UPDATE note_share_links SET cta_clicked_at = now() WHERE id = $1 AND cta_clicked_at IS NULL",
        link_id,
    )
    return bool(result) and result.split()[-1] == "1"


async def record_send_outcome(
    conn: asyncpg.Connection, *, link_id: UUID, status: str, error_class: str = ""
) -> ShareLinkRow | None:
    """Sprint 22: the product tried to mail the link. `status` is
    ``sent`` | ``failed``; the error class (never the message) is kept
    for the sender's "Retry" chip."""
    row = await conn.fetchrow(
        f"""
        UPDATE note_share_links
        SET delivery_status = $2::share_delivery_status,
            sent_at = CASE WHEN $2 = 'sent' THEN now() ELSE sent_at END,
            send_count = send_count + 1,
            last_send_error = $3
        WHERE id = $1
        RETURNING {_LINK_COLUMNS}
        """,
        link_id,
        status,
        error_class,
    )
    return _link_row(row) if row else None


async def is_share_mail_suppressed(conn: asyncpg.Connection, *, email_hash: bytes) -> bool:
    return bool(await conn.fetchval("SELECT public.is_share_mail_suppressed($1)", email_hash))


async def add_share_mail_suppression(
    conn: asyncpg.Connection, *, email_hash: bytes, reason: str
) -> None:
    await conn.execute("SELECT public.add_share_mail_suppression($1, $2)", email_hash, reason)


async def suppress_links_for_email(conn: asyncpg.Connection, *, tenant_id: UUID, email: str) -> int:
    """Every live link in the tenant addressed to this recipient stops
    being mailable. The links themselves keep working until they expire."""
    result = await conn.execute(
        """
        UPDATE note_share_links
        SET delivery_status = 'suppressed'
        WHERE tenant_id = $1 AND revoked_at IS NULL AND lower(recipient_email) = lower($2)
        """,
        tenant_id,
        email,
    )
    return int(result.split()[-1]) if result else 0


async def tenant_of_share_link(conn: asyncpg.Connection, *, link_id: UUID) -> UUID | None:
    """SECURITY DEFINER lookup for the unsubscribe route, which arrives
    with a link id and no tenant context (0039)."""
    value = await conn.fetchval("SELECT public.tenant_of_share_link($1)", link_id)
    return UUID(str(value)) if value else None


async def sharing_stats(conn: asyncpg.Connection, *, days: int) -> dict[str, object]:
    """PII-free aggregates over the tenant's recipient links (Sprint 22).
    Counts only; the sender leaderboard carries subs for the router to
    resolve to display names."""
    row = await conn.fetchrow(
        """
        WITH links AS (
            SELECT * FROM note_share_links
            WHERE kind = 'recipient' AND created_at >= now() - ($1 || ' days')::interval
        ),
        resp AS (
            SELECT r.link_id, r.kind::text AS kind FROM share_link_responses r
            JOIN links l ON l.id = r.link_id WHERE r.cleared_at IS NULL
        )
        SELECT
            (SELECT count(*) FROM links)                                            AS links_created,
            (SELECT count(*) FROM links WHERE delivery_status = 'sent')             AS links_sent,
            (SELECT count(*) FROM links WHERE first_viewed_at IS NOT NULL)          AS links_opened,
            (SELECT count(DISTINCT link_id) FROM resp)                              AS links_responded,
            (SELECT count(*) FROM links WHERE cta_clicked_at IS NOT NULL)           AS cta_clicks,
            (SELECT count(*) FROM resp WHERE kind = 'dispute')                      AS disputes,
            (SELECT count(*) FROM resp WHERE kind IN ('confirm', 'done', 'dispute')) AS item_responses,
            (SELECT count(*) FROM links WHERE delivery_status = 'suppressed')       AS opted_out
        """,
        str(int(days)),
    )
    senders = await conn.fetch(
        """
        SELECT created_by, count(*) AS n FROM note_share_links
        WHERE kind = 'recipient' AND created_at >= now() - ($1 || ' days')::interval
        GROUP BY created_by ORDER BY n DESC LIMIT 5
        """,
        str(int(days)),
    )
    assert row is not None
    return {
        # asyncpg iterates a Record's VALUES; `.keys()` is the only way to the names.
        **{k: int(row[k] or 0) for k in row.keys()},  # noqa: SIM118
        "top_senders": [(r["created_by"], int(r["n"])) for r in senders],
    }


async def mark_link_seen(conn: asyncpg.Connection, *, link_id: UUID, version_id: UUID) -> None:
    await conn.execute(
        "UPDATE note_share_links SET last_seen_version_id = $2 WHERE id = $1", link_id, version_id
    )


async def mark_link_verified(conn: asyncpg.Connection, *, link_id: UUID) -> None:
    await conn.execute(
        "UPDATE note_share_links SET verified_at = COALESCE(verified_at, now()) WHERE id = $1",
        link_id,
    )


async def put_link_otp(
    conn: asyncpg.Connection, *, tenant_id: UUID, link_id: UUID, code_hash: bytes, ttl_seconds: int
) -> None:
    """One live code per link; a new request replaces the old code."""
    await conn.execute(
        """
        INSERT INTO share_link_otps (link_id, tenant_id, code_hash, expires_at)
        VALUES ($1, $2, $3, now() + ($4 || ' seconds')::interval)
        ON CONFLICT (link_id) DO UPDATE
            SET code_hash = EXCLUDED.code_hash, issued_at = now(),
                expires_at = EXCLUDED.expires_at, attempts = 0
        """,
        link_id,
        tenant_id,
        code_hash,
        str(int(ttl_seconds)),
    )


async def fetch_link_otp(
    conn: asyncpg.Connection, *, link_id: UUID
) -> tuple[bytes, bool, int] | None:
    """(code_hash, live, attempts) or None."""
    row = await conn.fetchrow(
        "SELECT code_hash, expires_at > now() AS live, attempts FROM share_link_otps WHERE link_id = $1",
        link_id,
    )
    return (bytes(row["code_hash"]), bool(row["live"]), int(row["attempts"])) if row else None


async def bump_link_otp_attempts(conn: asyncpg.Connection, *, link_id: UUID) -> int:
    value = await conn.fetchval(
        "UPDATE share_link_otps SET attempts = attempts + 1 WHERE link_id = $1 RETURNING attempts",
        link_id,
    )
    return int(value or 0)


async def delete_link_otp(conn: asyncpg.Connection, *, link_id: UUID) -> None:
    await conn.execute("DELETE FROM share_link_otps WHERE link_id = $1", link_id)


async def add_abuse_report(
    conn: asyncpg.Connection, *, tenant_id: UUID, link_id: UUID, note_id: UUID, reason: str
) -> None:
    await conn.execute(
        "INSERT INTO share_abuse_reports (tenant_id, link_id, note_id, reason) VALUES ($1, $2, $3, $4)",
        tenant_id,
        link_id,
        note_id,
        reason,
    )


async def spam_reports_for_sender(conn: asyncpg.Connection, *, created_by: UUID) -> int:
    """Spam reports against links one person minted — the abuse guard's input."""
    value = await conn.fetchval(
        """
        SELECT count(*) FROM share_abuse_reports r
        JOIN note_share_links l ON l.id = r.link_id
        WHERE r.reason = 'spam' AND l.created_by = $1
        """,
        created_by,
    )
    return int(value or 0)


async def revoke_all_external_links(conn: asyncpg.Connection, *, actor_sub: UUID) -> list[UUID]:
    """Every live link in the tenant, revoked; returns the note ids touched."""
    rows = await conn.fetch(
        """
        UPDATE note_share_links
        SET revoked_at = now(), revoked_by = $1, recipient_email = NULL
        WHERE revoked_at IS NULL
        RETURNING note_id
        """,
        actor_sub,
    )
    return sorted({r["note_id"] for r in rows}, key=str)


async def fetch_tenant_logo(
    conn: asyncpg.Connection, *, tenant_id: UUID
) -> tuple[bytes, str] | None:
    """(bytes, content type) of the workspace logo, or None when there is
    none. Read under `tenants_self_select` on the tenant-scoped connection."""
    row = await conn.fetchrow(
        "SELECT logo_bytes, logo_content_type FROM tenants WHERE id = $1", tenant_id
    )
    if row is None or not row["logo_bytes"] or not row["logo_content_type"]:
        return None
    return bytes(row["logo_bytes"]), str(row["logo_content_type"])


async def set_source_session_id_if_absent(
    conn: asyncpg.Connection, *, note_id: UUID, session_id: UUID
) -> None:
    """Backfill ``source_session_id`` only when it is still NULL.

    Used by finalize to link a dictation session to its note. A note
    that already carries a source session is left untouched (no-op).
    """
    await conn.execute(
        """
        UPDATE notes
        SET source_session_id = $2, updated_at = now()
        WHERE id = $1 AND source_session_id IS NULL
        """,
        note_id,
        session_id,
    )


async def fetch_version(conn: asyncpg.Connection, *, version_id: UUID) -> VersionRow | None:
    row = await conn.fetchrow(
        """
        SELECT id, note_id, version_number, parent_version_id,
               created_by, created_at,
               content_jsonb, rendered_text, metadata,
               is_amendment, amendment_type, amendment_reason
        FROM note_versions
        WHERE id = $1
        """,
        version_id,
    )
    if row is None:
        return None
    raw = row["content_jsonb"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    body_hash = metadata.get("body_hash") if isinstance(metadata, dict) else None
    return VersionRow(
        id=row["id"],
        note_id=row["note_id"],
        version_number=int(row["version_number"]),
        parent_version_id=row["parent_version_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        content=NoteContent.model_validate(raw),
        rendered_text=row["rendered_text"],
        body_hash=body_hash,
        is_amendment=bool(row["is_amendment"]),
        amendment_type=(
            NoteAmendmentType(row["amendment_type"]) if row["amendment_type"] else None
        ),
        amendment_reason=row["amendment_reason"],
    )


async def fetch_version_by_number(
    conn: asyncpg.Connection, *, note_id: UUID, version_number: int
) -> VersionRow | None:
    row = await conn.fetchval(
        "SELECT id FROM note_versions WHERE note_id = $1 AND version_number = $2",
        note_id,
        version_number,
    )
    if row is None:
        return None
    return await fetch_version(conn, version_id=row)


@dataclass(slots=True)
class VersionSummaryRow:
    """Lightweight version-list row — never decodes ``content_jsonb``."""

    id: UUID
    version_number: int
    parent_version_id: UUID | None
    created_by: UUID
    created_at: datetime
    is_amendment: bool
    amendment_type: NoteAmendmentType | None
    amendment_reason: str | None


async def list_version_summaries(
    conn: asyncpg.Connection, *, note_id: UUID
) -> list[VersionSummaryRow]:
    """All versions of a note as metadata-only summaries, oldest first."""
    rows = await conn.fetch(
        """
        SELECT id, version_number, parent_version_id, created_by, created_at,
               is_amendment, amendment_type, amendment_reason
        FROM note_versions
        WHERE note_id = $1
        ORDER BY version_number
        """,
        note_id,
    )
    return [
        VersionSummaryRow(
            id=r["id"],
            version_number=int(r["version_number"]),
            parent_version_id=r["parent_version_id"],
            created_by=r["created_by"],
            created_at=r["created_at"],
            is_amendment=bool(r["is_amendment"]),
            amendment_type=(
                NoteAmendmentType(r["amendment_type"]) if r["amendment_type"] else None
            ),
            amendment_reason=r["amendment_reason"],
        )
        for r in rows
    ]


# ── Create ──────────────────────────────────────────────────────────


async def create_note_with_v1(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    code: str,
    primary_author_id: UUID,
    co_author_ids: list[UUID],
    template_id: UUID,
    template_schema_version: int,
    source_session_id: UUID | None,
    content: NoteContent,
    source_asr_job_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    """Two-step insert (ADR-0020):

    1. INSERT note with NULL current_version_id.
    2. INSERT v1 in note_versions.
    3. UPDATE note.current_version_id.

    The deferrable FK constraint is satisfied at COMMIT.
    Caller MUST be inside a single transaction (tenant_connection
    already opens one).
    """
    rendered = rendered_text_from_content(content)
    body_hash = body_hash_for(content)

    note_id: UUID = await conn.fetchval(
        """
        INSERT INTO notes (
            tenant_id, code, status, primary_author_id, co_author_ids,
            template_id, template_schema_version,
            title, source_session_id, source_asr_job_id
        )
        VALUES ($1, $2, 'draft', $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        tenant_id,
        code,
        primary_author_id,
        co_author_ids,
        template_id,
        template_schema_version,
        content.title,
        source_session_id,
        source_asr_job_id,
    )

    version_id: UUID = await conn.fetchval(
        """
        INSERT INTO note_versions (
            note_id, version_number, parent_version_id, created_by,
            content_jsonb, rendered_text, diff_jsonb, metadata
        )
        VALUES ($1, 1, NULL, $2, $3::jsonb, $4, '{}'::jsonb, $5::jsonb)
        RETURNING id
        """,
        note_id,
        primary_author_id,
        json.dumps(content.model_dump(mode="json")),
        rendered,
        json.dumps({"body_hash": body_hash}),
    )

    await conn.execute(
        "UPDATE notes SET current_version_id = $2, updated_at = now() WHERE id = $1",
        note_id,
        version_id,
    )
    return note_id, version_id


async def fetch_notes_by_source_jobs(
    conn: asyncpg.Connection, *, asr_job_ids: list[UUID]
) -> list[asyncpg.Record]:
    """Notes created from the given transcription jobs (RLS-scoped).

    Powers the jobs-list "already assigned" badge — bulk, one round trip.
    """
    return await conn.fetch(
        """
        SELECT source_asr_job_id, id, code, status
        FROM notes
        WHERE source_asr_job_id = ANY($1::uuid[])
        """,
        asr_job_ids,
    )


# ── Append version (autosave / amendment) ───────────────────────────


async def append_version(
    conn: asyncpg.Connection,
    *,
    note_id: UUID,
    expected_version: int,
    new_content: NoteContent,
    created_by: UUID,
    diff_jsonb: dict[str, Any],
    is_amendment: bool = False,
    amendment_type: NoteAmendmentType | None = None,
    amendment_reason: str | None = None,
    parent_version_id_override: UUID | None = None,
    body_hash_override: str | None = None,
) -> tuple[UUID, int]:
    """Append a new version row to ``note_id``.

    Concurrency:
    - Caller obtains a row lock via ``SELECT ... FOR UPDATE`` on the
      notes row before calling this. We re-check ``version_number``
      here (defence-in-depth) so two callers cannot both think they
      hold the lock.

    Returns (new_version_id, new_version_number).
    """
    head = await conn.fetchrow(
        """
        SELECT v.id, v.version_number
        FROM notes n
        JOIN note_versions v ON v.id = n.current_version_id
        WHERE n.id = $1
        """,
        note_id,
    )
    if head is None:
        raise RuntimeError("note has no current_version; corrupt state")
    if int(head["version_number"]) != expected_version:
        from .conflicts import OptimisticLockMismatchError

        raise OptimisticLockMismatchError(
            current_version=int(head["version_number"]),
            expected_version=expected_version,
        )

    rendered = rendered_text_from_content(new_content)
    body_hash = body_hash_override or body_hash_for(new_content)
    new_version_number = expected_version + 1
    parent_version_id = parent_version_id_override or head["id"]

    new_version_id: UUID = await conn.fetchval(
        """
        INSERT INTO note_versions (
            note_id, version_number, parent_version_id, created_by,
            content_jsonb, rendered_text, diff_jsonb, metadata,
            is_amendment, amendment_type, amendment_reason
        )
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8::jsonb,
                $9, $10, $11)
        RETURNING id
        """,
        note_id,
        new_version_number,
        parent_version_id,
        created_by,
        json.dumps(new_content.model_dump(mode="json")),
        rendered,
        json.dumps(diff_jsonb),
        json.dumps({"body_hash": body_hash}),
        is_amendment,
        amendment_type.value if amendment_type else None,
        amendment_reason,
    )
    await conn.execute(
        """
        UPDATE notes
        SET current_version_id = $2,
            title              = $3,
            updated_at         = now()
        WHERE id = $1
        """,
        note_id,
        new_version_id,
        new_content.title,
    )
    return new_version_id, new_version_number


# ── Helpers used by routers ─────────────────────────────────────────


async def lock_note_for_update(conn: asyncpg.Connection, *, note_id: UUID) -> NoteRow | None:
    """Acquire a row lock on the note (used by autosave / amend).

    Combined with the optimistic ``expected_version`` check, this
    serialises concurrent writers; one wins, the other gets 409.
    """
    await conn.fetchrow(
        "SELECT id FROM notes WHERE id = $1 FOR UPDATE",
        note_id,
    )
    return await fetch_note(conn, note_id=note_id)


async def find_existing_version_by_body_hash(
    conn: asyncpg.Connection,
    *,
    note_id: UUID,
    body_hash: str,
) -> VersionRow | None:
    """Idempotency lookup: did we already record this exact body for
    this note? Used to make autosave PUTs idempotent on retry."""
    row_id = await conn.fetchval(
        """
        SELECT id FROM note_versions
        WHERE note_id = $1 AND metadata->>'body_hash' = $2
        ORDER BY version_number DESC LIMIT 1
        """,
        note_id,
        body_hash,
    )
    if row_id is None:
        return None
    return await fetch_version(conn, version_id=row_id)


async def list_amendment_chain(conn: asyncpg.Connection, *, note_id: UUID) -> list[VersionRow]:
    """Returns all versions for ``note_id`` ordered by version_number ASC.

    Used by the chain reconciler + the diff endpoint when resolving
    'from'/'to' by number.
    """
    rows = await conn.fetch(
        "SELECT id FROM note_versions WHERE note_id = $1 ORDER BY version_number",
        note_id,
    )
    out: list[VersionRow] = []
    for r in rows:
        v = await fetch_version(conn, version_id=r["id"])
        if v is not None:
            out.append(v)
    return out
