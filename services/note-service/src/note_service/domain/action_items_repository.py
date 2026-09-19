"""SQL for ``note_action_items`` and ``share_link_responses`` (0037).

Thin, like ``notes_repository``: every query runs on a tenant-scoped
connection and RLS does the isolation. The anonymous routes get such a
connection only after the Sprint 19 resolver named the tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

if TYPE_CHECKING:  # pragma: no cover
    from .action_items import ParsedItem


@dataclass(slots=True)
class ItemRow:
    id: UUID
    note_id: UUID
    note_version_id: UUID
    item_key: str
    position: int
    text: str
    owner_label: str | None
    owner_confidence: float | None
    due_date: date | None
    due_text: str | None
    due_confidence: float | None
    status: str


@dataclass(slots=True)
class ResponseRow:
    id: UUID
    note_id: UUID
    link_id: UUID
    link_label: str
    kind: str
    item_key: str | None
    section_key: str | None
    comment: str | None
    created_at: datetime
    cleared_at: datetime | None


_ITEM_COLS = (
    "id, note_id, note_version_id, item_key, position, text, owner_label, owner_confidence, "
    "due_date, due_text, due_confidence, status::text AS status"
)


def _item(r: asyncpg.Record) -> ItemRow:
    return ItemRow(
        id=r["id"],
        note_id=r["note_id"],
        note_version_id=r["note_version_id"],
        item_key=r["item_key"],
        position=int(r["position"]),
        text=r["text"],
        owner_label=r["owner_label"],
        owner_confidence=r["owner_confidence"],
        due_date=r["due_date"],
        due_text=r["due_text"],
        due_confidence=r["due_confidence"],
        status=r["status"],
    )


_RESP_COLS = (
    "r.id, r.note_id, r.link_id, l.label AS link_label, r.kind::text AS kind, r.item_key, "
    "r.section_key, r.comment, r.created_at, r.cleared_at"
)


def _response(r: asyncpg.Record) -> ResponseRow:
    return ResponseRow(
        id=r["id"],
        note_id=r["note_id"],
        link_id=r["link_id"],
        link_label=r["link_label"] or "",
        kind=r["kind"],
        item_key=r["item_key"],
        section_key=r["section_key"],
        comment=r["comment"],
        created_at=r["created_at"],
        cleared_at=r["cleared_at"],
    )


# ── items ────────────────────────────────────────────────────────────


async def latest_statuses(
    conn: asyncpg.Connection, *, note_id: UUID, keys: list[str], before_version_id: UUID
) -> dict[str, str]:
    """The most recent status per key on any earlier version of the note."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (item_key) item_key, status::text AS status
        FROM note_action_items
        WHERE note_id = $1 AND item_key = ANY($2::text[]) AND note_version_id <> $3
        ORDER BY item_key, created_at DESC
        """,
        note_id,
        keys,
        before_version_id,
    )
    return {r["item_key"]: r["status"] for r in rows}


async def insert_items(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    version_id: UUID,
    items: list[ParsedItem],
    statuses: dict[str, str],
) -> int:
    inserted = 0
    for position, p in enumerate(items):
        result = await conn.execute(
            """
            INSERT INTO note_action_items
                (tenant_id, note_id, note_version_id, item_key, position, text,
                 owner_label, owner_confidence, due_date, due_text, due_confidence, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::action_item_status)
            ON CONFLICT (note_version_id, item_key) DO NOTHING
            """,
            tenant_id,
            note_id,
            version_id,
            p.item_key,
            position,
            p.text,
            p.owner_label,
            p.owner_confidence,
            p.due_date,
            p.due_text,
            p.due_confidence,
            statuses.get(p.item_key, "open"),
        )
        if result and result.split()[-1] == "1":
            inserted += 1
    return inserted


async def fetch_items(conn: asyncpg.Connection, *, version_id: UUID) -> list[ItemRow]:
    rows = await conn.fetch(
        f"SELECT {_ITEM_COLS} FROM note_action_items WHERE note_version_id = $1 ORDER BY position",
        version_id,
    )
    return [_item(r) for r in rows]


async def fetch_item(conn: asyncpg.Connection, *, note_id: UUID, item_id: UUID) -> ItemRow | None:
    row = await conn.fetchrow(
        f"SELECT {_ITEM_COLS} FROM note_action_items WHERE note_id = $1 AND id = $2",
        note_id,
        item_id,
    )
    return _item(row) if row else None


async def set_item_status(
    conn: asyncpg.Connection, *, item_id: UUID, status: str, actor_sub: UUID | None
) -> None:
    await conn.execute(
        """
        UPDATE note_action_items
        SET status = $2::action_item_status, status_changed_by = $3, status_changed_at = now()
        WHERE id = $1
        """,
        item_id,
        status,
        actor_sub,
    )


# ── responses ────────────────────────────────────────────────────────


async def upsert_response(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    link_id: UUID,
    kind: str,
    item_key: str | None,
    section_key: str | None,
    comment: str | None,
) -> UUID:
    """Replace this link's live response on the target — whatever its
    kind: a recipient's stance on an item is one of confirm / done /
    dispute, not a pile of them. The old row is cleared (not deleted) so
    the history survives."""
    await conn.execute(
        """
        UPDATE share_link_responses SET cleared_at = now()
        WHERE link_id = $1 AND cleared_at IS NULL
          AND COALESCE(item_key, '') = COALESCE($2, '')
          AND COALESCE(section_key, '') = COALESCE($3, '')
        """,
        link_id,
        item_key,
        section_key,
    )
    row = await conn.fetchrow(
        """
        INSERT INTO share_link_responses
            (tenant_id, note_id, link_id, kind, item_key, section_key, comment)
        VALUES ($1, $2, $3, $4::share_response_kind, $5, $6, $7)
        RETURNING id
        """,
        tenant_id,
        note_id,
        link_id,
        kind,
        item_key,
        section_key,
        comment,
    )
    assert row is not None
    return row["id"]


async def withdraw_response(
    conn: asyncpg.Connection, *, link_id: UUID, item_key: str | None, section_key: str | None
) -> int:
    """The recipient takes it back: every live response of this link on
    the target is cleared with no actor."""
    result = await conn.execute(
        """
        UPDATE share_link_responses SET cleared_at = now(), cleared_by = NULL
        WHERE link_id = $1 AND cleared_at IS NULL
          AND COALESCE(item_key, '') = COALESCE($2, '')
          AND COALESCE(section_key, '') = COALESCE($3, '')
        """,
        link_id,
        item_key,
        section_key,
    )
    return int(result.split()[-1]) if result else 0


async def clear_response(
    conn: asyncpg.Connection, *, note_id: UUID, response_id: UUID, actor_sub: UUID
) -> ResponseRow | None:
    row = await conn.fetchrow(
        """
        UPDATE share_link_responses r SET cleared_at = now(), cleared_by = $3
        FROM note_share_links l
        WHERE r.id = $2 AND r.note_id = $1 AND r.cleared_at IS NULL AND l.id = r.link_id
        RETURNING """
        + _RESP_COLS,
        note_id,
        response_id,
        actor_sub,
    )
    return _response(row) if row else None


async def clear_responses_for_note(
    conn: asyncpg.Connection, *, note_id: UUID, actor_sub: UUID
) -> int:
    result = await conn.execute(
        """
        UPDATE share_link_responses SET cleared_at = now(), cleared_by = $2
        WHERE note_id = $1 AND cleared_at IS NULL
        """,
        note_id,
        actor_sub,
    )
    return int(result.split()[-1]) if result else 0


async def list_responses(
    conn: asyncpg.Connection, *, note_id: UUID, include_cleared: bool = False
) -> list[ResponseRow]:
    rows = await conn.fetch(
        f"""
        SELECT {_RESP_COLS}
        FROM share_link_responses r JOIN note_share_links l ON l.id = r.link_id
        WHERE r.note_id = $1 AND ($2 OR r.cleared_at IS NULL)
        ORDER BY r.created_at DESC
        """,
        note_id,
        include_cleared,
    )
    return [_response(r) for r in rows]


async def responses_for_link(conn: asyncpg.Connection, *, link_id: UUID) -> list[ResponseRow]:
    rows = await conn.fetch(
        f"""
        SELECT {_RESP_COLS}
        FROM share_link_responses r JOIN note_share_links l ON l.id = r.link_id
        WHERE r.link_id = $1 AND r.cleared_at IS NULL
        ORDER BY r.created_at DESC
        """,
        link_id,
    )
    return [_response(r) for r in rows]


async def live_response_counts_by_link(
    conn: asyncpg.Connection, *, note_id: UUID
) -> dict[UUID, int]:
    rows = await conn.fetch(
        """
        SELECT link_id, count(*) AS n FROM share_link_responses
        WHERE note_id = $1 AND cleared_at IS NULL GROUP BY link_id
        """,
        note_id,
    )
    return {r["link_id"]: int(r["n"]) for r in rows}
