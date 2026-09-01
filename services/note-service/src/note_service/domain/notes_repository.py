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
from dataclasses import dataclass
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


async def fetch_note(conn: asyncpg.Connection, *, note_id: UUID) -> NoteRow | None:
    row = await conn.fetchrow(
        """
        SELECT n.id, n.tenant_id, n.code, n.status,
               n.current_version_id, v.version_number AS current_version_number,
               n.primary_author_id, n.co_author_ids,
               n.title, n.created_at, n.updated_at, n.finalized_at,
               n.cancelled_at, n.source_session_id
        FROM notes n
        LEFT JOIN note_versions v ON v.id = n.current_version_id
        WHERE n.id = $1
        """,
        note_id,
    )
    if row is None:
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
    )


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
