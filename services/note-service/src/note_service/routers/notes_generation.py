"""The generation surface (Sprint 33).

    GET  /v1/notes/{id}/generation        how the writing is going
    POST /v1/notes/{id}/generation        regenerate
    GET  /v1/notes/{id}/generated-items   the verified facts, with evidence

The status route is what lets a client say "4 of 10 parts" and, when
something went wrong, **which minutes** could not be processed — a
generation that fails silently is worse than one that says so.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteStatus, ReadPurpose

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import access, generation_service
from ..domain import generation_repository as gen_repo
from ..domain import notes_repository as repo
from ..notifications import emit_budget_reached
from . import ai_settings as ai_settings_router
from .notes_from_transcript import _fetch_transcript

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


class ExcludedRange(BaseModel):
    """A stretch of the recording left out of the notes, confirmed by code
    (Summary Engine v2, Q2). ``reason`` is a closed vocabulary — background,
    other_language, artifact, duplicate, unrelated — for the client to
    turn into words; never text from the recording."""

    model_config = ConfigDict(extra="forbid")

    start_ms: int
    end_ms: int
    reason: str


class Coverage(BaseModel):
    """How the facts spread over the recording, and how much speech was
    set aside. Counts and milliseconds only."""

    model_config = ConfigDict(extra="forbid")

    """Facts found in the first, middle and last third of the recording."""
    facts_by_third: list[int]
    speech_ms: int
    excluded_ms: int


class GenerationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    step: str | None
    windows_total: int | None
    windows_done: int | None
    windows_failed: int | None
    """``[[start_ms, end_ms]]`` — which minutes are missing, so the note
    can name them instead of apologising in general."""
    failed_ranges: list[list[int]]
    prompt_version: str
    model_id: str | None
    """Why it ended without a document, from a closed vocabulary. The
    client turns it into a sentence; the API never sends prose it would
    have to translate."""
    error_kind: str | None
    created_at: datetime
    finished_at: datetime | None
    """Sections the engine did NOT write because the author had already
    written there; their facts are offered instead of imposed."""
    suggested_sections: list[str]
    """How many sections the run wrote (or found already exactly right).
    Zero on a finished run means the recording yielded nothing the
    verifier would let through — the client says so rather than showing
    an empty tab with no way forward."""
    sections_written: int | None = None
    """Q2 — what was left out, and how the facts cover the recording.
    Empty / null for generations made before Q2."""
    excluded_ranges: list[ExcludedRange] = []
    coverage: Coverage | None = None
    """Q3 — what the recording was taken to be (``meeting``, ``podcast_broadcast``,
    ``lecture_webinar``, ``voice_memo``, …) and who decided: ``user`` (a
    meeting type or template the author chose), ``classifier``, ``rule`` or
    ``template`` (the classifier could not answer). Null before Q3."""
    recording_type: str | None = None
    recording_type_source: str | None = None
    """The spoken language the run wrote in (``en``/``de``/``uk``), so the
    client labels exclusions in it. Null before Q3."""
    language: str | None = None

    @property
    def live(self) -> bool:
        return self.status in gen_repo.LIVE_STATUSES


class GenerationStarted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str


class GeneratedItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str
    kind: str
    section_key: str
    text: str
    owner_label: str | None
    due_text: str | None
    due_date: date | None
    explicit: bool
    confidence: float
    flags: list[str]
    """The words that prove it. A row cannot exist without one."""
    quote: str
    start_ms: int
    end_ms: int
    speaker_label: str | None
    speaker_name: str | None
    placement: str
    """Q5 — the line's facts (item keys), how sure it is, whose position it
    is, the names respelled in it (``[{surface, canonical, source}]``) and
    the dates it names (``[{text, date, time, direction}]``). Empty for
    rows written before Q5."""
    cites: list[str] = []
    certainty: str | None = None
    attributed_to: str | None = None
    """F2 — for a sub-point, the row key of the bullet it sits under."""
    parent_key: str | None = None
    """F3 — a figure row's verified fields: ``{name, value, unit,
    qualifier}``, every word in its quote. Null for every other row."""
    figure: dict[str, str] | None = None
    corrections: list[dict[str, str]] = []
    mentions: list[dict[str, str | None]] = []


def _excluded(stats: dict) -> list[ExcludedRange]:
    out: list[ExcludedRange] = []
    for entry in stats.get("excluded_ranges") or []:
        if isinstance(entry, (list, tuple)) and len(entry) == 3:
            out.append(
                ExcludedRange(start_ms=int(entry[0]), end_ms=int(entry[1]), reason=str(entry[2]))
            )
    return out


def _coverage(stats: dict) -> Coverage | None:
    thirds = stats.get("facts_by_third")
    if not isinstance(thirds, list) or len(thirds) != 3:
        return None
    return Coverage(
        facts_by_third=[int(n) for n in thirds],
        speech_ms=int(stats.get("speech_ms") or 0),
        excluded_ms=int(stats.get("excluded_ms") or 0),
    )


def _view(row: gen_repo.GenerationRow) -> GenerationView:
    stats = row.stats or {}
    return GenerationView(
        id=row.id,
        status=row.status,
        step=row.step,
        windows_total=row.windows_total,
        windows_done=row.windows_done,
        windows_failed=row.windows_failed,
        failed_ranges=row.failed_ranges,
        prompt_version=row.prompt_version,
        model_id=row.model_id,
        error_kind=row.error_kind,
        created_at=row.created_at,
        finished_at=row.finished_at,
        suggested_sections=list((row.stats or {}).get("suggested_sections", [])),
        sections_written=(
            len((row.stats or {}).get("section_hashes", {}))
            if row.status in ("complete", "partial")
            else None
        ),
        excluded_ranges=_excluded(stats),
        coverage=_coverage(stats),
        recording_type=stats.get("recording_type"),
        recording_type_source=stats.get("recording_type_source"),
        language=stats.get("language"),
    )


async def _audit(claims: Claims, kind: str, note_id: UUID, payload: dict[str, object]) -> None:
    """Ids and counts only — never a quote, a name or a line of the note."""
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload=payload,
        severity=Severity.INFO,
    )


@router.get("/{note_id}/generation", response_model=GenerationView)
async def get_generation(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: ReadPurpose | None = None,
) -> GenerationView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        access.require_read_purpose(note, claims, purpose)
        row = await gen_repo.latest_for_note(conn, note_id=note_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no generation for this note")
    return _view(row)


@router.post(
    "/{note_id}/generation",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerationStarted,
)
async def regenerate(
    note_id: UUID,
    request: Request,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> GenerationStarted:
    """Write the note again from the recording.

    Safe to press: the writer rewrites only sections nobody has edited
    since the last run, so the author's own text survives a regenerate
    exactly as it survives the first pass.
    """
    state = get_state()
    auth_header = request.headers.get("authorization") or ""

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        if note.status != NoteStatus.DRAFT:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "note_cancelled", "detail": "the note is no longer a draft"},
            )
        if note.source_asr_job_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "no_transcript",
                    "detail": "this note was not made from a recording",
                },
            )
        job_id = note.source_asr_job_id

    # Outside the transaction: a network call must not hold a pooled
    # connection, and asr-service authorises the read with the caller's
    # own bearer rather than a service identity we do not have.
    transcript = await _fetch_transcript(job_id, auth_header=auth_header)

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        try:
            generation_id, generation_status = await generation_service.start(
                conn,
                queue=state.job_queue,
                store=state.transcripts_store,
                tenant_id=claims.tid,
                note_id=note_id,
                requested_by=claims.sub,
                transcript=transcript,
                reason="regenerate",
                transcript_rev=int(transcript.get("result_rev") or 1),
                enforce_limit=True,
                required_processors=ai_settings_router.required_processors(),
            )
        except generation_service.GenerationBusyError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "generation_in_progress",
                    "detail": "this note is already being written",
                },
            ) from None
        except generation_service.GenerationDisabledError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "generation_disabled",
                    "detail": "this workspace has turned automatic note writing off",
                },
            ) from None
        except generation_service.ProcessorUnacknowledgedError as exc:
            # Sprint L2 — the list in the error is what the client shows
            # in the dialog, from the same registry the router uses.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "processor_unacknowledged",
                    "detail": "a workspace admin has to agree to who processes your meetings",
                    "processors": [{"name": p.name, "region": p.region} for p in exc.processors],
                },
            ) from None
        except generation_service.BudgetExceededError as exc:
            await emit_budget_reached(
                state.redis,
                tenant_id=claims.tid,
                actor_user_id=claims.sub,
                spent_cents=exc.spent,
                budget_cents=exc.budget,
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "budget_exceeded",
                    "detail": "this workspace has spent its AI budget for the month",
                    "spent_cents": exc.spent,
                    "budget_cents": exc.budget,
                },
            ) from None
        except generation_service.GenerationRateLimitedError:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "too_many_generations",
                    "detail": "this note has been rewritten too many times today",
                },
            ) from None

    await _audit(claims, audit_kinds.NOTE_GENERATION_REQUESTED, note_id, {"reason": "regenerate"})
    return GenerationStarted(id=generation_id, status=generation_status)


@router.get("/{note_id}/generated-items", response_model=list[GeneratedItemView])
async def generated_items(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: ReadPurpose | None = None,
    generation: Literal["current", "all"] = "all",
) -> list[GeneratedItemView]:
    """Every verified fact behind this note, with the words that prove it.

    Same audience as the transcript: these ARE transcript excerpts, so
    the read goes through `require_view` and the oversight-read purpose
    rule. The shared page never calls this.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        access.require_read_purpose(note, claims, purpose)
        rows = await gen_repo.items_for_note(
            conn, note_id=note_id, current_only=generation == "current"
        )
    return [
        GeneratedItemView(
            item_key=str(r["item_key"]),
            kind=str(r["kind"]),
            section_key=str(r["section_key"]),
            text=str(r["text"]),
            owner_label=r["owner_label"],
            due_text=r["due_text"],
            due_date=r["due_date"],
            explicit=bool(r["explicit"]),
            confidence=float(r["confidence"]),
            flags=list(r["flags"] or []),
            quote=str(r["quote"]),
            start_ms=int(r["start_ms"]),
            end_ms=int(r["end_ms"]),
            speaker_label=r["speaker_label"],
            speaker_name=r["speaker_name"],
            placement=str(r["placement"]),
            cites=list(_get(r, "cites") or []),
            certainty=_get(r, "certainty"),
            attributed_to=_get(r, "attributed_to"),
            parent_key=_get(r, "parent_key"),
            figure=_figure(_get(r, "payload")) if r["kind"] == "figure" else None,
            corrections=_json_list(_get(r, "corrections")),
            mentions=_json_list(_get(r, "mentions")),
        )
        for r in rows
    ]


def _get(row: object, key: str) -> object:
    """A column that may be absent (a row read before 0059, a test fake)."""
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError):
        return None


def _json_list(value: object) -> list:
    """asyncpg returns JSONB as text unless a codec is set; both are fine."""
    import json

    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    return list(value) if isinstance(value, list) else []


def _figure(value: object) -> dict[str, str] | None:
    """F3 — a figure row's payload as ``{name, value, unit, qualifier}``."""
    import json

    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None
    return {k: str(value.get(k) or "") for k in ("name", "value", "unit", "qualifier")}
