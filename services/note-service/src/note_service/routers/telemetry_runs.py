"""Telemetry read API (telemetry sprint 4): run summaries, one run's full record, its Markdown
report, and the admin dashboard's aggregates.

Who sees a run: the platform admin (``telemetry.read_all``) any run in any tenant; everyone
else only runs of a recording in their workspace that they submitted, whose note they can view,
or — a workspace admin — any. A run the caller may not see is a 404, like one that does not
exist. Nothing here reads audio, transcripts or notes, or reruns anything; free-form fields
pass through ``redact()`` again on the way out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

import telemetry
from auth import Claims
from auth.perms import can_claims
from db import tenant_connection
from telemetry import queries
from telemetry.overview import aggregate
from telemetry.report import missing_measurements, render_report
from telemetry.schema import RunExport

from ..deps import get_state, requires
from ..domain import access
from ..domain import notes_repository as repo

router = APIRouter(tags=["telemetry"])

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "partial"]
# The dashboard reads at most this many runs of a period (newest first) and says so.
OVERVIEW_CAP = 500
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_FAR = datetime(9999, 1, 1, tzinfo=UTC)

Reader = Annotated[Claims, Depends(requires("telemetry.read", "telemetry"))]
Admin = Annotated[Claims, Depends(requires("telemetry.read_all", "telemetry"))]


def _platform_admin(claims: Claims) -> bool:
    return can_claims(claims, "telemetry.read_all", "telemetry")


async def _may_read(conn: Any, claims: Claims, recording_id: UUID) -> bool:
    """The recording is in the caller's workspace (RLS) and the caller submitted it, can view
    its note, or administers the workspace."""
    requester = await conn.fetchval(
        "SELECT requester_sub FROM transcription_jobs WHERE id = $1", recording_id
    )
    if requester is None:
        return False
    if str(requester) == str(claims.sub) or access.sees_whole_tenant(claims):
        return True
    note_id = await conn.fetchval(
        "SELECT id FROM notes WHERE source_asr_job_id = $1 AND deleted_at IS NULL", recording_id
    )
    note = await repo.fetch_note(conn, note_id=note_id) if note_id is not None else None
    return note is not None and access.can_view(note, claims)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")


async def _load(claims: Claims, run_id: UUID) -> RunExport:
    state = get_state()
    tenant = claims.tid
    admin = _platform_admin(claims)
    if admin:
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            found = await queries.run_tenant(conn, run_id)
        if found is None:
            raise _not_found()
        tenant = found
    async with tenant_connection(state.app_pool, tenant) as conn:
        record = await queries.fetch_export(conn, run_id)
        if record is None:
            raise _not_found()
        if not admin and not await _may_read(conn, claims, record.processing_run.recording_id):
            raise _not_found()
    return _redacted(record)


def _redacted(record: RunExport) -> RunExport:
    data = record.model_dump(mode="json")
    for s in data["spans"]:
        s["attributes"] = telemetry.redact(s["attributes"])
    for e in data["client_events"]:
        e["attributes"] = telemetry.redact(e["attributes"])
    if data["run_context"] is not None:
        ctx = data["run_context"]
        ctx["effective_config"] = telemetry.redact(ctx["effective_config"])
    return RunExport.model_validate(data)


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = telemetry.redact(row)
    return out


def _window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    return start or _EPOCH, end or _FAR


@router.get("/v1/telemetry/runs")
async def list_runs(
    claims: Reader,
    recording_id: UUID | None = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Run summaries, newest first, keyset-paginated (``next_cursor``)."""
    try:
        before = queries.decode_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    state = get_state()
    filters: dict[str, Any] = {
        "recording_id": recording_id, "status": run_status, "submitted_from": start,
        "submitted_to": end, "before": before, "limit": limit + 1,
    }  # fmt: skip
    rows: list[dict[str, Any]] = []
    if _platform_admin(claims):
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            if recording_id is not None:
                tenant = await queries.recording_tenant(conn, recording_id)
                tenants = [tenant] if tenant is not None else []
            else:
                tenants = await queries.tenants_between(conn, *_window(start, end))
        for tenant in tenants:
            async with tenant_connection(state.app_pool, tenant) as conn:
                rows += await queries.list_runs(conn, **filters)
    else:
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            if recording_id is not None:
                if not await _may_read(conn, claims, recording_id):
                    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recording not found")
            elif not access.sees_whole_tenant(claims):
                filters["requester"] = claims.sub  # the caller's own recordings
            rows = await queries.list_runs(conn, **filters)
    rows.sort(key=lambda r: (r["submitted_at"], r["processing_run_id"]), reverse=True)
    page = rows[:limit]
    more = len(rows) > limit
    last = page[-1] if page else None
    return {
        "runs": [_summary(r) for r in page],
        "next_cursor": (
            queries.encode_cursor(last["submitted_at"], last["processing_run_id"])
            if more and last is not None
            else None
        ),
    }


@router.get("/v1/telemetry/recordings/{recording_id}/runs")
async def recording_runs(recording_id: UUID, claims: Reader) -> dict[str, Any]:
    """Every run of one recording: the initial run and its reprocesses."""
    page = await list_runs(claims, recording_id=recording_id, limit=100)
    return {"runs": page["runs"]}


@router.get("/v1/telemetry/runs/{run_id}")
async def get_run(run_id: UUID, claims: Reader) -> dict[str, Any]:
    """The full structured record: run, context, spans, LLM calls, client events, and every
    measurement that is missing with its reason."""
    record = await _load(claims, run_id)
    data: dict[str, Any] = record.model_dump(mode="json")
    data["missing_measurements"] = missing_measurements(record)
    return data


@router.get(
    "/v1/telemetry/runs/{run_id}/report.md",
    responses={200: {"content": {"text/markdown": {}}}},
)
async def get_report(run_id: UUID, claims: Reader) -> Response:
    record = await _load(claims, run_id)
    run = record.processing_run
    filename = f"diagnostics-{run.recording_id}-{run.processing_run_id}.md"
    return Response(
        content=render_report(record),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/v1/admin/telemetry/overview")
async def overview(
    claims: Admin,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    """Dashboard aggregates over the stored runs of a period (default: the last 7 days)."""
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=7)
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        tenants = await queries.tenants_between(conn, start, end)
    heads: list[tuple[UUID, dict[str, Any]]] = []
    for tenant in tenants:
        async with tenant_connection(state.app_pool, tenant) as conn:
            rows = await queries.list_runs(
                conn, submitted_from=start, submitted_to=end, limit=OVERVIEW_CAP + 1
            )
        heads += [(tenant, r) for r in rows]
    heads.sort(key=lambda h: (h[1]["submitted_at"], h[1]["processing_run_id"]), reverse=True)
    capped = len(heads) > OVERVIEW_CAP
    records: list[RunExport] = []
    for tenant, row in heads[:OVERVIEW_CAP]:
        async with tenant_connection(state.app_pool, tenant) as conn:
            record = await queries.fetch_export(conn, row["processing_run_id"])
        if record is not None:
            records.append(_redacted(record))
    return {"from": start.isoformat(), "to": end.isoformat(), "capped": capped,
            **aggregate(records)}  # fmt: skip
