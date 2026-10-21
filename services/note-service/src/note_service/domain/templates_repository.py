"""``workspace_templates`` (Sprint P2): a workspace's own text for a built-in note
template, per name and language. Every function takes an RLS-scoped connection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

import asyncpg

_COLUMNS: Final = "tenant_id, name, language, markdown, updated_by, created_at, updated_at"


@dataclass(frozen=True, slots=True)
class Row:
    tenant_id: UUID
    name: str
    language: str
    markdown: str
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


def _row(record: asyncpg.Record) -> Row:
    return Row(
        tenant_id=record["tenant_id"],
        name=str(record["name"]),
        language=str(record["language"]),
        markdown=str(record["markdown"]),
        updated_by=record["updated_by"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


async def fetch_all(conn: asyncpg.Connection, *, tenant_id: UUID) -> list[Row]:
    records = await conn.fetch(
        f"SELECT {_COLUMNS} FROM workspace_templates WHERE tenant_id = $1 ORDER BY name, language",
        tenant_id,
    )
    return [_row(r) for r in records]


async def fetch(
    conn: asyncpg.Connection, *, tenant_id: UUID, name: str, language: str
) -> Row | None:
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM workspace_templates "
        "WHERE tenant_id = $1 AND name = $2 AND language = $3",
        tenant_id,
        name,
        language,
    )
    return _row(record) if record is not None else None


async def upsert(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    name: str,
    language: str,
    markdown: str,
    updated_by: UUID,
) -> Row:
    record = await conn.fetchrow(
        f"""
        INSERT INTO workspace_templates (tenant_id, name, language, markdown, updated_by)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (tenant_id, name, language) DO UPDATE SET
            markdown = EXCLUDED.markdown, updated_by = EXCLUDED.updated_by
        RETURNING {_COLUMNS}
        """,
        tenant_id,
        name,
        language,
        markdown,
        updated_by,
    )
    return _row(record)


async def delete(conn: asyncpg.Connection, *, tenant_id: UUID, name: str, language: str) -> bool:
    result = await conn.execute(
        "DELETE FROM workspace_templates WHERE tenant_id = $1 AND name = $2 AND language = $3",
        tenant_id,
        name,
        language,
    )
    return result.endswith(" 1")
