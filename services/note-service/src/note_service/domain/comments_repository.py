"""``note_comments`` rows (0074, W3 B-4).

Free functions on an RLS-scoped connection (house idiom). Every read and
write names the note as well as the comment, so a comment id from another
note never resolves (IDOR). Soft-deleted comments are invisible here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(frozen=True, slots=True)
class CommentRow:
    id: UUID
    note_id: UUID
    tenant_id: UUID
    author_sub: UUID
    anchor_kind: str
    anchor_key: str
    body: str
    created_at: datetime
    edited_at: datetime | None
    resolved_at: datetime | None
    resolved_by: UUID | None


_COLUMNS = (
    "id, note_id, tenant_id, author_sub, anchor_kind, anchor_key, body, "
    "created_at, edited_at, resolved_at, resolved_by"
)


def _row(record: asyncpg.Record) -> CommentRow:
    return CommentRow(
        id=record["id"],
        note_id=record["note_id"],
        tenant_id=record["tenant_id"],
        author_sub=record["author_sub"],
        anchor_kind=record["anchor_kind"],
        anchor_key=record["anchor_key"],
        body=record["body"],
        created_at=record["created_at"],
        edited_at=record["edited_at"],
        resolved_at=record["resolved_at"],
        resolved_by=record["resolved_by"],
    )


async def list_comments(conn: asyncpg.Connection, *, note_id: UUID) -> list[CommentRow]:
    rows = await conn.fetch(
        f"SELECT {_COLUMNS} FROM note_comments "
        "WHERE note_id = $1 AND deleted_at IS NULL ORDER BY created_at, id",
        note_id,
    )
    return [_row(r) for r in rows]


async def fetch_comment(
    conn: asyncpg.Connection, *, note_id: UUID, comment_id: UUID
) -> CommentRow | None:
    row = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM note_comments "
        "WHERE id = $1 AND note_id = $2 AND deleted_at IS NULL",
        comment_id,
        note_id,
    )
    return _row(row) if row is not None else None


async def insert_comment(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    author_sub: UUID,
    anchor_kind: str,
    anchor_key: str,
    body: str,
) -> CommentRow:
    row = await conn.fetchrow(
        "INSERT INTO note_comments (tenant_id, note_id, author_sub, anchor_kind, anchor_key, body) "
        f"VALUES ($1, $2, $3, $4, $5, $6) RETURNING {_COLUMNS}",
        tenant_id,
        note_id,
        author_sub,
        anchor_kind,
        anchor_key,
        body,
    )
    return _row(row)


async def update_body(
    conn: asyncpg.Connection, *, note_id: UUID, comment_id: UUID, body: str
) -> CommentRow | None:
    row = await conn.fetchrow(
        "UPDATE note_comments SET body = $3, edited_at = now() "
        f"WHERE id = $1 AND note_id = $2 AND deleted_at IS NULL RETURNING {_COLUMNS}",
        comment_id,
        note_id,
        body,
    )
    return _row(row) if row is not None else None


async def set_resolved(
    conn: asyncpg.Connection, *, note_id: UUID, comment_id: UUID, resolved_by: UUID | None
) -> CommentRow | None:
    """``resolved_by`` set → resolve now; ``None`` → unresolve."""
    row = await conn.fetchrow(
        "UPDATE note_comments "
        "SET resolved_at = CASE WHEN $3::uuid IS NULL THEN NULL ELSE now() END, "
        "    resolved_by = $3::uuid "
        f"WHERE id = $1 AND note_id = $2 AND deleted_at IS NULL RETURNING {_COLUMNS}",
        comment_id,
        note_id,
        resolved_by,
    )
    return _row(row) if row is not None else None


async def soft_delete(
    conn: asyncpg.Connection, *, note_id: UUID, comment_id: UUID, deleted_by: UUID
) -> bool:
    status = await conn.execute(
        "UPDATE note_comments SET deleted_at = now(), deleted_by = $3 "
        "WHERE id = $1 AND note_id = $2 AND deleted_at IS NULL",
        comment_id,
        note_id,
        deleted_by,
    )
    return status.endswith(" 1")


async def commenters_on_anchor(
    conn: asyncpg.Connection, *, note_id: UUID, anchor_kind: str, anchor_key: str
) -> list[UUID]:
    """Everyone with a live comment on this anchor (notification audience)."""
    rows = await conn.fetch(
        "SELECT DISTINCT author_sub FROM note_comments "
        "WHERE note_id = $1 AND anchor_kind = $2 AND anchor_key = $3 AND deleted_at IS NULL",
        note_id,
        anchor_kind,
        anchor_key,
    )
    return [r["author_sub"] for r in rows]
