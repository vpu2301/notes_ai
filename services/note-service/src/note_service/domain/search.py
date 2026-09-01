"""Search query construction + cursor pagination + snippet generation.

Postgres ``simple`` FTS config (ADR-0021). Composes filter clauses
with AND. Joins to ``note_versions`` so the search hits the current
version's rendered text. Snippet via ``ts_headline`` is run inside the
same query for one DB round-trip.

Results are ordered most-recent-first by ``created_at`` (a monotonic,
never-NULL column) with ``id`` as a stable tie-break, so a
freshly-created draft always lands on the first page.

Cursor encoding (opaque to clients): base64 url-safe of the tuple
``(created_at_iso, note_id_hex)``. Tie-break by id so the cursor is
stable.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

import asyncpg


@dataclass(slots=True)
class SearchFilters:
    q: str | None = None
    author_id: UUID | None = None
    statuses: list[str] | None = None
    created_from: date | None = None
    created_to: date | None = None
    # Sprint 15 (ADR-0038): pre-assembled tsquery string from
    # domain/query_expansion — when set (and q is set) the FTS tier uses
    # to_tsquery('simple', ts_query) instead of plainto over q. The SAME
    # bind arg feeds the predicate, ts_headline AND exact_total; unset →
    # the pre-sprint-15 plainto path, byte-identical.
    ts_query: str | None = None


def _fts_clause(filters: SearchFilters, args: list[Any]) -> tuple[str, str] | None:
    """Append the FTS bind arg; return (predicate, tsquery_expr) or None.

    ONE place builds the tsquery expression so the match predicate,
    the snippet highlighter and the exact count can never disagree.
    """
    if not filters.q:
        return None
    if filters.ts_query is not None:
        args.append(filters.ts_query)
        expr = f"to_tsquery('simple', ${len(args)})"
    else:
        args.append(filters.q)
        expr = f"plainto_tsquery('simple', ${len(args)})"
    return f"v.search_vector @@ {expr}", expr


@dataclass(slots=True)
class SearchHit:
    note_id: UUID
    code: str
    title: str
    status: str
    template_id: UUID
    primary_author_id: UUID
    co_author_ids: list[UUID]
    snippet: str
    created_at: datetime
    updated_at: datetime


def encode_cursor(*, created_at: datetime, note_id: UUID) -> str:
    payload = {
        "c": created_at.isoformat(),
        "i": note_id.hex,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("ascii")).decode("ascii")


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    raw = base64.urlsafe_b64decode(value.encode("ascii"))
    obj = json.loads(raw.decode("ascii"))
    return datetime.fromisoformat(obj["c"]), UUID(obj["i"])


async def search_notes(
    conn: asyncpg.Connection,
    *,
    filters: SearchFilters,
    limit: int,
    cursor: tuple[datetime, UUID] | None,
) -> tuple[list[SearchHit], str | None, int | None]:
    """Run the FTS + filters query.

    Returns (hits, next_cursor, total_estimated).
    """
    where: list[str] = []
    args: list[Any] = []
    tsquery_expr: str | None = None

    fts = _fts_clause(filters, args)
    if fts is not None:
        predicate, tsquery_expr = fts
        where.append(predicate)

    if filters.author_id is not None:
        args.append(filters.author_id)
        where.append(f"(n.primary_author_id = ${len(args)} OR ${len(args)} = ANY(n.co_author_ids))")

    if filters.statuses:
        args.append(filters.statuses)
        where.append(f"n.status = ANY(${len(args)}::note_status[])")

    if filters.created_from is not None:
        args.append(filters.created_from)
        where.append(f"n.created_at >= ${len(args)}")

    if filters.created_to is not None:
        args.append(filters.created_to)
        where.append(f"n.created_at < ${len(args)}::date + 1")

    if cursor is not None:
        cur_c, cur_id = cursor
        # Order: created_at DESC, id DESC — keyset predicate for "strictly after".
        args.append(cur_c)
        args.append(cur_id)
        where.append(
            f"(n.created_at < ${len(args) - 1} "
            f" OR (n.created_at = ${len(args) - 1} AND n.id < ${len(args)}))"
        )

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    args.append(limit + 1)

    snippet_expr = (
        f"ts_headline('simple', v.rendered_text, {tsquery_expr}, "
        f"'MaxFragments=2, MaxWords=15, MinWords=5, StartSel=<mark>, StopSel=</mark>')"
        if tsquery_expr is not None
        else "''"
    )

    sql = f"""
        SELECT
            n.id, n.code, n.title, n.status, n.template_id,
            n.primary_author_id, n.co_author_ids,
            n.created_at, n.updated_at,
            {snippet_expr} AS snippet
        FROM notes n
        JOIN note_versions v ON v.id = n.current_version_id
        {where_sql}
        ORDER BY n.created_at DESC, n.id DESC
        LIMIT ${len(args)}
    """
    rows = await conn.fetch(sql, *args)

    has_more = len(rows) > limit
    rows = rows[:limit]
    hits: list[SearchHit] = []
    for r in rows:
        hits.append(
            SearchHit(
                note_id=r["id"],
                code=r["code"],
                title=r["title"],
                status=r["status"],
                template_id=r["template_id"],
                primary_author_id=r["primary_author_id"],
                co_author_ids=list(r["co_author_ids"] or []),
                snippet=r["snippet"] or "",
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
        )
    next_cursor: str | None = None
    if has_more and hits:
        last = hits[-1]
        next_cursor = encode_cursor(created_at=last.created_at, note_id=last.note_id)
    total_estimated = await _estimate_total(conn)
    return hits, next_cursor, total_estimated


async def _estimate_total(conn: asyncpg.Connection) -> int:
    """Cheap reltuples-based estimate. Caller can opt into ``total=exact``
    via the router; that path bypasses this helper."""
    val = await conn.fetchval("SELECT reltuples::bigint FROM pg_class WHERE relname = 'notes'")
    return int(val or 0)


async def exact_total(conn: asyncpg.Connection, filters: SearchFilters) -> int:
    """Slow path; rate-limited at router layer."""
    where: list[str] = []
    args: list[Any] = []
    fts = _fts_clause(filters, args)
    if fts is not None:
        where.append(fts[0])
    if filters.statuses:
        args.append(filters.statuses)
        where.append(f"n.status = ANY(${len(args)}::note_status[])")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    val = await conn.fetchval(
        f"""
        SELECT count(*) FROM notes n
        JOIN note_versions v ON v.id = n.current_version_id
        {where_sql}
        """,
        *args,
    )
    return int(val or 0)
