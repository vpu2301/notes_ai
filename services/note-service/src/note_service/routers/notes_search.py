"""GET /notes/search — the note list surface.

Two standings reach it (S14):

  `note.read`  — member / viewer. The full list: titles, snippets,
                 authors.
  `stats.read` — tenant_admin, who holds no content read. Same rows,
                 stripped to counts and timings: no title, no snippet.
                 This is what keeps the business dashboard's KPIs
                 working after the admin was separated from note
                 content, without giving back a browsable list of the
                 tenant's notes.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from opentelemetry import metrics
from pydantic import BaseModel, ConfigDict

from audit import Severity
from auth import Claims, can_claims
from db import tenant_connection

from .. import audit_kinds
from ..deps import get_state, requires_any
from ..domain import access, query_expansion
from ..domain import search as searchmod
from ..domain.pii_redactor import is_author_team, redact_snippet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

_meter = metrics.get_meter("mdx.note")
# Sprint 15: closes the sprint-08 gap — the dashboard panel "Search latency
# (split by has_q)" and the NoteSearchLatencyHigh alert have queried
# mdx_notes_search_latency_ms_histogram since sprint 08, but nothing ever
# created the instrument. unit deliberately empty (exporter appends unit
# names; values are ms); the "*latency*" View supplies the ms buckets.
_search_latency = _meter.create_histogram(
    "mdx_notes_search_latency_ms_histogram",
    description="End-to-end note search latency in ms (label has_q)",
    unit="",
)
_expansion_metric = _meter.create_counter(
    "mdx_notes_search_expansion_total",
    description="Query-expansion outcomes on /v1/notes/search (label hit)",
    unit="1",
)


class SearchHitDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    code: str
    title: str
    status: str
    template_id: UUID
    primary_author_id: UUID
    co_author_ids: list[UUID]
    snippet: str
    updated_at: str


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hits: list[SearchHitDTO]
    next_cursor: str | None
    total_estimated: int | None
    total_exact: int | None = None
    # Sprint 15 (ADR-0038): synonym terms that broadened this query —
    # transparency for the FE ("also matching: quarterly review, QBR").
    # Empty when expansion found nothing or expand=false.
    expanded_terms: list[str] = []


@router.get("/search", response_model=SearchResponse)
async def search_notes(
    claims: Annotated[
        Claims,
        Depends(requires_any(("note.read", "note"), ("stats.read", "tenant"))),
    ],
    q: str | None = Query(default=None, max_length=200),
    author_id: UUID | None = None,
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    created_from: date | None = None,
    created_to: date | None = None,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    total: str | None = Query(default=None, description="set to 'exact' for full count"),
    expand: bool = Query(
        default=True,
        description="Synonym query expansion (ADR-0038); false = exact terms only.",
    ),
) -> SearchResponse:
    state = get_state()
    started = time.perf_counter()
    cursor_decoded: tuple[datetime, UUID] | None = None
    if cursor:
        try:
            cursor_decoded = searchmod.decode_cursor(cursor)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid cursor: {exc}",
            ) from exc

    filters = searchmod.SearchFilters(
        q=q,
        author_id=author_id,
        statuses=status_filter,
        created_from=created_from,
        created_to=created_to,
        viewer_sub=claims.sub,
        viewer_sees_all=access.sees_whole_tenant(claims),
    )

    expanded_terms: list[str] = []
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        if q and expand:
            expansion = await query_expansion.expand_query(conn, raw_q=q)
            if expansion.tsquery is not None and expansion.groups_used > 0:
                filters.ts_query = expansion.tsquery
                expanded_terms = expansion.expanded_terms
            _expansion_metric.add(1, {"hit": str(bool(expansion.groups_used)).lower()})
        hits, next_cursor, total_estimated = await searchmod.search_notes(
            conn,
            filters=filters,
            limit=limit,
            cursor=cursor_decoded,
        )
        total_exact: int | None = None
        if total == "exact":
            total_exact = await searchmod.exact_total(conn, filters)

        # S14 — which of the two standings admitted this caller decides
        # what the rows may contain. `stats.read` alone (a tenant_admin)
        # gets counts and timings; `note.read` gets the full list.
        content_read = can_claims(claims, "note.read", "note")

    out: list[SearchHitDTO] = []
    for h in hits:
        if not content_read:
            # Stats mode. Every content-bearing field is dropped at
            # construction rather than blanked afterwards, so a field
            # added to SearchHitDTO later cannot leak by being forgotten
            # here — it simply takes its model default.
            out.append(
                SearchHitDTO(
                    note_id=h.note_id,
                    code=h.code,
                    title="",
                    status=h.status,
                    template_id=h.template_id,
                    primary_author_id=h.primary_author_id,
                    co_author_ids=h.co_author_ids,
                    snippet="",
                    updated_at=h.updated_at.isoformat(),
                )
            )
            continue

        on_team = is_author_team(
            viewer_user_id=claims.sub,
            primary_author_id=h.primary_author_id,
            co_author_ids=h.co_author_ids,
            viewer_roles=list(claims.roles),
        )
        snippet = h.snippet if on_team else redact_snippet(h.snippet)
        out.append(
            SearchHitDTO(
                note_id=h.note_id,
                code=h.code,
                title=h.title,
                status=h.status,
                template_id=h.template_id,
                primary_author_id=h.primary_author_id,
                co_author_ids=h.co_author_ids,
                snippet=snippet,
                updated_at=h.updated_at.isoformat(),
            )
        )

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_SEARCHED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=None,
        payload={
            "q": q or "",
            "has_q": q is not None,
            "result_count": len(out),
            "filters": {
                "status": status_filter or [],
                "created_from": created_from.isoformat() if created_from else None,
                "created_to": created_to.isoformat() if created_to else None,
            },
        },
        severity=Severity.INFO,
    )
    if expanded_terms:
        # Aggregated search.expanded (ADR-0038): counted in memory, one
        # audit row per tenant per flush — never per keystroke.
        await state.search_audit_buffer.record(
            tenant_id=claims.tid, expanded_terms=len(expanded_terms)
        )

    _search_latency.record(
        (time.perf_counter() - started) * 1000.0,
        {"has_q": str(q is not None).lower()},
    )
    return SearchResponse(
        hits=out,
        next_cursor=next_cursor,
        total_estimated=total_estimated,
        total_exact=total_exact,
        expanded_terms=expanded_terms,
    )
