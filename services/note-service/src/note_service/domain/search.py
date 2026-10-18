"""Search query construction + cursor pagination + snippets (``simple`` FTS,
ADR-0021). Ordered by ``created_at`` desc with ``id`` as tie-break; the cursor
is url-safe base64 of ``(created_at_iso, note_id_hex)``.
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
    # ADR-0038: pre-assembled tsquery string from
    # domain/query_expansion — when set (and q is set) the FTS tier uses
    # to_tsquery('simple', ts_query) instead of plainto over q. The SAME
    # bind arg feeds the predicate, ts_headline AND exact_total; unset →
    # the pre-sprint-15 plainto path, byte-identical.
    ts_query: str | None = None
    # 0016 — the caller. ``viewer_sub`` restricts results to notes that
    # person may see (workspace-visible, theirs, or shared with them);
    # ``viewer_sees_all`` (tenant_admin / auditor) lifts that. Deleted
    # notes are never returned either way.
    viewer_sub: UUID | None = None
    viewer_sees_all: bool = False
    # W3: a guest sees only notes it holds a grant on — no workspace visibility, no authorship.
    viewer_guest: bool = False
    # W3: all | mine (author team) | shared_with_me (visible to me, not mine).
    scope: str = "all"
    # W5: "backfill" — the caller's notes the W5 script opened to the workspace (review list).
    changed_by: str | None = None


def _access_clauses(filters: SearchFilters, args: list[Any]) -> list[str]:
    """Visibility (who may see) plus the scope and author filters — shared by the page and the count."""
    out = ["n.deleted_at IS NULL"]
    if filters.author_id is not None:
        args.append(filters.author_id)
        out.append(f"(n.primary_author_id = ${len(args)} OR ${len(args)} = ANY(n.co_author_ids))")
    if filters.viewer_sub is None:
        return out
    # An unreferenced bind arg has no inferable type (IndeterminateDatatypeError),
    # so bind the viewer only when a clause below will use it.
    if filters.viewer_sees_all and not filters.viewer_guest and filters.scope == "all":
        return out
    args.append(filters.viewer_sub)
    i = len(args)
    mine = f"(n.primary_author_id = ${i} OR ${i} = ANY(n.co_author_ids))"
    granted = (
        f"EXISTS (SELECT 1 FROM note_collaborators c WHERE c.note_id = n.id AND c.user_sub = ${i})"
    )
    if filters.viewer_guest:
        out.append(granted)
    elif not filters.viewer_sees_all:
        out.append(f"(n.visibility = 'workspace' OR {mine} OR {granted})")
    if filters.scope == "mine" or filters.changed_by == "backfill":
        out.append(mine)
    elif filters.scope == "shared_with_me":
        out.append(f"NOT {mine}")
    if filters.changed_by == "backfill":
        out.append("n.visibility_source = 'backfill'")
    return out


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
    # 0016 — who can open it, for the list's private / shared / public badge.
    visibility: str = "private"
    # W3: people with a per-note grant (was `cardinality(shared_with_ids)`).
    shared_with_count: int = 0
    # W3: the caller's own per-note role, for `my_level`.
    my_collab_role: str | None = None
    has_public_link: bool = False
    # Live recipient disputes, for the "1 disputed" dot.
    open_disputes: int = 0
    # W5: default | author | backfill.
    visibility_source: str = "default"


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
    where.extend(_access_clauses(filters, args))

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
    viewer_arg = None
    if filters.viewer_sub is not None:
        args.append(filters.viewer_sub)
        viewer_arg = len(args)
    my_role_expr = (
        "(SELECT c.role::text FROM note_collaborators c "
        f"WHERE c.note_id = n.id AND c.user_sub = ${viewer_arg})"
        if viewer_arg is not None
        else "NULL::text"
    )
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
            n.visibility::text AS visibility, n.visibility_source,
            (SELECT count(*) FROM note_collaborators c WHERE c.note_id = n.id)
                AS shared_with_count,
            {my_role_expr} AS my_collab_role,
            EXISTS (
                SELECT 1 FROM note_share_links l
                WHERE l.note_id = n.id AND l.revoked_at IS NULL
                  AND (l.expires_at IS NULL OR l.expires_at > now())
            ) AS has_public_link,
            (
                SELECT count(*) FROM share_link_responses r
                WHERE r.note_id = n.id AND r.kind = 'dispute' AND r.cleared_at IS NULL
            ) AS open_disputes,
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
                visibility=r["visibility"],
                shared_with_count=r["shared_with_count"] or 0,
                my_collab_role=r["my_collab_role"],
                has_public_link=r["has_public_link"],
                open_disputes=int(r["open_disputes"] or 0),
                visibility_source=r["visibility_source"],
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
    where.extend(_access_clauses(filters, args))
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
