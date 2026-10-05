"""``workspace_glossary`` + ``note_item_corrections``.

Every function takes an RLS-scoped connection from ``tenant_connection``:
the tenant predicate is the policy's, not a WHERE clause here.
"""

from __future__ import annotations

import hashlib
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
    # The note whose speaker rename added this term.
    source_note_id: UUID | None = None


def _row(record: asyncpg.Record) -> GlossaryRow:
    return GlossaryRow(
        id=record["id"],
        term=str(record["term"]),
        kind=str(record["kind"]),
        heard_as=list(record["heard_as"] or []),
        created_by=record["created_by"],
        created_at=record["created_at"],
        source_note_id=record.get("source_note_id"),
    )


async def list_terms(conn: asyncpg.Connection) -> list[GlossaryRow]:
    """Every live term, people first, then alphabetically."""
    rows = await conn.fetch(
        """
        SELECT id, term, kind, heard_as, created_by, created_at, source_note_id
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
    source_note_id: UUID | None = None,
) -> GlossaryRow:
    record = await conn.fetchrow(
        """
        INSERT INTO workspace_glossary
            (tenant_id, term, kind, heard_as, created_by, source_note_id)
        VALUES ($1, $2, $3, $4::text[], $5, $6)
        RETURNING id, term, kind, heard_as, created_by, created_at, source_note_id
        """,
        tenant_id,
        term,
        kind,
        heard_as,
        created_by,
        source_note_id,
    )
    return _row(record)


async def note_exists(conn: asyncpg.Connection, *, note_id: UUID) -> bool:
    """Under the tenant's RLS: a note of another workspace does not exist."""
    return bool(await conn.fetchval("SELECT EXISTS (SELECT 1 FROM notes WHERE id = $1)", note_id))


async def merge_heard_as(
    conn: asyncpg.Connection, *, row: GlossaryRow, heard_as: list[str]
) -> GlossaryRow:
    """Add spellings to a term that is already there; the merge rules are in
    :func:`glossary.clean_heard_as`, this only writes."""
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
    """Keys whose LAST correction was a dismissal (a later ``restore`` cancels it);
    regeneration must not re-add these."""
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


NAME_TAG_PREFIX = "name:"


def name_review_tag(surface: str, canonical: str) -> str:
    """The flag that says "the author decided on THIS respelling": a truncated
    sha256 of the pair, since the log holds no text."""
    digest = hashlib.sha256(f"{surface}\u2192{canonical}".encode()).hexdigest()[:16]
    return f"{NAME_TAG_PREFIX}{digest}"


async def reviewed_name_tags(conn: asyncpg.Connection, *, note_id: UUID) -> set[str]:
    """Respellings the author already accepted or rejected in this note,
    so the "Names in this note" list does not ask twice."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT tag
        FROM note_item_corrections, unnest(flags_at_time) AS tag
        WHERE note_id = $1
          AND action IN ('correction_accepted', 'correction_rejected')
          AND tag LIKE 'name:%'
        """,
        note_id,
    )
    return {str(r["tag"]) for r in rows}


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
