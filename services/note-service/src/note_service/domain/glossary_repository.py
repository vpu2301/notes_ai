"""``workspace_glossary`` + ``note_item_corrections`` (migration 0050).

Every function takes an RLS-scoped connection from ``tenant_connection``:
the tenant predicate is the policy's, not a WHERE clause here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from .glossary import Term, clean_heard_as


@dataclass(slots=True)
class GlossaryRow:
    id: UUID
    term: str
    kind: str
    heard_as: list[str]
    created_by: UUID
    created_at: datetime


def _row(record: asyncpg.Record) -> GlossaryRow:
    return GlossaryRow(
        id=record["id"],
        term=str(record["term"]),
        kind=str(record["kind"]),
        heard_as=list(record["heard_as"] or []),
        created_by=record["created_by"],
        created_at=record["created_at"],
    )


async def list_terms(conn: asyncpg.Connection) -> list[GlossaryRow]:
    """Every live term, people first (they are what gets misheard), then
    alphabetically — a list a person reads, not a dump."""
    rows = await conn.fetch(
        """
        SELECT id, term, kind, heard_as, created_by, created_at
        FROM workspace_glossary
        WHERE deleted_at IS NULL
        ORDER BY (kind <> 'person'), lower(term)
        """
    )
    return [_row(r) for r in rows]


async def terms_for_matching(conn: asyncpg.Connection) -> list[Term]:
    """The shape the pure rules in ``domain.glossary`` take."""
    return [
        Term(term=row.term, kind=row.kind, heard_as=tuple(row.heard_as))
        for row in await list_terms(conn)
    ]


async def count_terms(conn: asyncpg.Connection) -> int:
    total: int = await conn.fetchval(
        "SELECT count(*) FROM workspace_glossary WHERE deleted_at IS NULL"
    )
    return int(total)


async def find_term(conn: asyncpg.Connection, *, term: str) -> GlossaryRow | None:
    record = await conn.fetchrow(
        """
        SELECT id, term, kind, heard_as, created_by, created_at
        FROM workspace_glossary
        WHERE lower(term) = lower($1) AND deleted_at IS NULL
        """,
        term,
    )
    return _row(record) if record is not None else None


async def add_term(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    term: str,
    kind: str,
    heard_as: list[str],
    created_by: UUID,
) -> GlossaryRow:
    record = await conn.fetchrow(
        """
        INSERT INTO workspace_glossary (tenant_id, term, kind, heard_as, created_by)
        VALUES ($1, $2, $3, $4::text[], $5)
        RETURNING id, term, kind, heard_as, created_by, created_at
        """,
        tenant_id,
        term,
        kind,
        heard_as,
        created_by,
    )
    return _row(record)


async def merge_heard_as(
    conn: asyncpg.Connection, *, row: GlossaryRow, heard_as: list[str]
) -> GlossaryRow:
    """Add spellings to a term that is already there.

    Saying "remember John Mayer" twice, after two different mishearings,
    should teach the second one rather than fail as a duplicate. The
    merge rules (de-duplication, the cap, never the term itself) are the
    pure ones in :func:`glossary.clean_heard_as`; this only writes.
    """
    merged = clean_heard_as([*row.heard_as, *heard_as], term=row.term)
    if merged == row.heard_as:
        return row
    record = await conn.fetchrow(
        """
        UPDATE workspace_glossary
        SET heard_as = $2::text[]
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, term, kind, heard_as, created_by, created_at
        """,
        row.id,
        merged,
    )
    if record is None:  # deleted between the read and the write
        raise LookupError("term not found")
    return _row(record)


async def soft_delete_term(conn: asyncpg.Connection, *, term_id: UUID) -> GlossaryRow | None:
    record = await conn.fetchrow(
        """
        UPDATE workspace_glossary
        SET deleted_at = now()
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, term, kind, heard_as, created_by, created_at
        """,
        term_id,
    )
    return _row(record) if record is not None else None


# ── Corrections ─────────────────────────────────────────────────────


async def record_correction(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    item_key: str,
    kind: str,
    action: str,
    reason: str | None,
    flags_at_time: list[str],
    actor_sub: UUID,
    prompt_version: str | None = None,
    model_id: str | None = None,
) -> None:
    """Append one correction. No text ever goes in — see migration 0050."""
    await conn.execute(
        """
        INSERT INTO note_item_corrections (
            tenant_id, note_id, item_key, kind, action, reason,
            flags_at_time, prompt_version, model_id, actor_sub
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::text[], $8, $9, $10)
        """,
        tenant_id,
        note_id,
        item_key,
        kind,
        action,
        reason,
        flags_at_time,
        prompt_version,
        model_id,
        actor_sub,
    )


async def dismissed_keys(conn: asyncpg.Connection, *, note_id: UUID) -> set[str]:
    """Keys whose LAST correction was a dismissal.

    Regeneration must not re-add these: the author has already said this
    line does not belong. A later ``restore`` cancels it, which is why the
    query looks at the most recent row per key rather than at any row.
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (item_key) item_key, action
        FROM note_item_corrections
        WHERE note_id = $1 AND action IN ('dismiss', 'restore')
        ORDER BY item_key, created_at DESC
        """,
        note_id,
    )
    return {str(r["item_key"]) for r in rows if r["action"] == "dismiss"}


async def corrections_for(conn: asyncpg.Connection, *, note_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT item_key, kind, action, reason, flags_at_time, actor_sub, created_at
        FROM note_item_corrections
        WHERE note_id = $1
        ORDER BY created_at DESC
        """,
        note_id,
    )
