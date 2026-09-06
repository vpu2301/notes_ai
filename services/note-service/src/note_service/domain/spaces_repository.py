"""``note_spaces`` / ``note_space_items`` rows (0021).

Free functions on an RLS-scoped connection (house idiom). Every read and
write is scoped twice: RLS to the tenant, and ``user_sub`` here — a
space is personal, so a colleague's folders never come back and cannot
be renamed or emptied from another account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(frozen=True, slots=True)
class SpaceRow:
    id: UUID
    tenant_id: UUID
    user_sub: UUID
    name: str
    created_at: datetime
    updated_at: datetime


_COLUMNS = "id, tenant_id, user_sub, name, created_at, updated_at"


def _row(record: asyncpg.Record) -> SpaceRow:
    return SpaceRow(
        id=record["id"],
        tenant_id=record["tenant_id"],
        user_sub=record["user_sub"],
        name=record["name"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


async def list_spaces(conn: asyncpg.Connection, *, user_sub: UUID) -> list[SpaceRow]:
    rows = await conn.fetch(
        f"SELECT {_COLUMNS} FROM note_spaces "
        "WHERE user_sub = $1 AND deleted_at IS NULL "
        "ORDER BY created_at, id",
        user_sub,
    )
    return [_row(r) for r in rows]


async def list_items(conn: asyncpg.Connection, *, user_sub: UUID) -> dict[UUID, UUID]:
    """note id → space id, for every note the user filed in a live space."""
    rows = await conn.fetch(
        "SELECT i.note_id, i.space_id FROM note_space_items AS i "
        "JOIN note_spaces AS s ON s.id = i.space_id "
        "WHERE i.user_sub = $1 AND s.deleted_at IS NULL",
        user_sub,
    )
    return {r["note_id"]: r["space_id"] for r in rows}


async def create_space(
    conn: asyncpg.Connection, *, tenant_id: UUID, user_sub: UUID, name: str
) -> SpaceRow:
    record = await conn.fetchrow(
        "INSERT INTO note_spaces (tenant_id, user_sub, name) VALUES ($1, $2, $3) "
        f"RETURNING {_COLUMNS}",
        tenant_id,
        user_sub,
        name,
    )
    assert record is not None
    return _row(record)


async def rename_space(
    conn: asyncpg.Connection, *, user_sub: UUID, space_id: UUID, name: str
) -> SpaceRow | None:
    record = await conn.fetchrow(
        "UPDATE note_spaces SET name = $3, updated_at = now() "
        "WHERE id = $2 AND user_sub = $1 AND deleted_at IS NULL "
        f"RETURNING {_COLUMNS}",
        user_sub,
        space_id,
        name,
    )
    return _row(record) if record is not None else None


async def delete_space(conn: asyncpg.Connection, *, user_sub: UUID, space_id: UUID) -> bool:
    """Stamp the space deleted and unfile its notes. False when it is not
    the caller's (or already gone)."""
    async with conn.transaction():
        record = await conn.fetchrow(
            "UPDATE note_spaces SET deleted_at = now(), updated_at = now() "
            "WHERE id = $2 AND user_sub = $1 AND deleted_at IS NULL RETURNING id",
            user_sub,
            space_id,
        )
        if record is None:
            return False
        await conn.execute(
            "UPDATE note_space_items SET space_id = NULL, updated_at = now() WHERE space_id = $1",
            space_id,
        )
    return True


async def set_note_space(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    user_sub: UUID,
    note_id: UUID,
    space_id: UUID | None,
) -> bool:
    """File the note in ``space_id`` (None = unfile). False when the space
    is not the caller's live space."""
    if space_id is not None:
        owned = await conn.fetchval(
            "SELECT 1 FROM note_spaces WHERE id = $2 AND user_sub = $1 AND deleted_at IS NULL",
            user_sub,
            space_id,
        )
        if not owned:
            return False
    await conn.execute(
        "INSERT INTO note_space_items (tenant_id, user_sub, note_id, space_id) "
        "VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (tenant_id, user_sub, note_id) "
        "DO UPDATE SET space_id = EXCLUDED.space_id, updated_at = now()",
        tenant_id,
        user_sub,
        note_id,
        space_id,
    )
    return True
