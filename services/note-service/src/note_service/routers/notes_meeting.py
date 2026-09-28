"""The note exists from the first second (Sprint 34, ADR-0055).

``POST /v1/notes/meeting`` creates the note when the author presses
Record, not when a transcript finally arrives. From then on the author
types into it — on the laptop, the Mac or the phone, online or not — and
the recording catches up:

    record start → POST /v1/notes/meeting          state=recording
    typing       → PUT  /v1/notes/{id}/draft       (the existing autosave)
                 + PUT  /v1/notes/{id}/my-notes/timing
    record stop  → POST /v1/notes/{id}/meeting/job state=transcribing
    asr complete → POST /v1/notes/{id}/transcript  state=ready
                 + the engine is queued (Sprint 33) — progress on
                   GET /v1/notes/{id}/generation, never on the state

``POST /from-transcript`` is untouched: uploads and older clients still
make a note out of a finished job, and one note per job stays enforced by
the partial unique index on ``notes.source_asr_job_id`` — whichever route
gets there first wins, the other gets 409 ``already_assigned``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteContent, NoteSection, NoteStatus
from template_models import FieldType, TemplateDefinition

from .. import audit_kinds, meeting_metrics
from ..config import settings
from ..deps import get_state, requires
from ..domain import access, code_sequence, generation_service, series_service, template_match
from ..domain import meetings_repository as meetings
from ..domain import notes_repository as repo
from ..domain.conflicts import OptimisticLockMismatchError
from ..domain.meeting_doc import agenda as agenda_rules
from ..domain.meeting_doc import user_notes as user_notes_rules
from ..domain.repository import get_template
from ..notifications import emit_budget_reached
from . import ai_settings as ai_settings_router
from .notes_from_transcript import (
    _PROSE_HOMES,
    TEMPLATE_LANGUAGE_FALLBACK,
    _fetch_transcript,
    _parse_definition,
    _transcript_text,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

# The author's scratchpad. Every meeting template carries it; the engine
# never writes it, and nothing here ever rewrites what was typed.
USER_NOTES_SECTION: Final = "user_notes"
ATTENDEES_SECTION: Final = "attendees"
AGENDA_SECTION: Final = "agenda"

# Meeting type → the seed template family that fits it. "client" has no
# family of its own; general meeting notes are the honest default rather
# than a sales script imposed on a customer call.
_TEMPLATE_FAMILY: Final[dict[str, str]] = {
    "auto": "meeting_notes",
    "client": "meeting_notes",
    "team": "project_update",
    "sales": "sales_call",
    "one_on_one": "one_on_one",
    "interview": "interview_debrief",
}
_FALLBACK_FAMILY: Final = "meeting_notes"

MAX_ATTENDEE_NAMES: Final = 12
MAX_NAME_CHARS: Final = 80
MAX_AGENDA_LINES: Final = agenda_rules.MAX_LINES
MAX_TIMING_LINES: Final = user_notes_rules.MAX_USER_LINES


# ── Wire models ─────────────────────────────────────────────────────


class CalendarContextIn(BaseModel):
    """What the invite knew. ``description`` is read for its agenda and
    then dropped — it is never stored and never returned."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["google", "ics", "eventkit"]
    title: str = Field(default="", max_length=512)
    ical_uid: str | None = Field(default=None, max_length=512)
    attendee_names: list[str] = Field(default_factory=list, max_length=64)
    agenda_lines: list[str] = Field(default_factory=list, max_length=64)
    description: str | None = Field(default=None, max_length=agenda_rules.MAX_DESCRIPTION_CHARS)


class StartMeetingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_capture_id: UUID
    title: str = Field(default="", max_length=512)
    started_at: datetime
    language: Literal["auto", "en", "de", "uk"] = "auto"
    meeting_type: Literal["auto", "client", "team", "sales", "one_on_one", "interview"] = "auto"
    template_id: UUID | None = None
    calendar: CalendarContextIn | None = None


class StartMeetingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    version_number: int
    template_id: UUID
    state: str


class LineTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_key: str = Field(min_length=1, max_length=64)
    offset_ms: int = Field(ge=0)


class LineTimesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[LineTime] = Field(max_length=MAX_TIMING_LINES)


class AttachJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asr_job_id: UUID


class MeetingView(BaseModel):
    """What a second device needs to show the right status and to finish
    the job the first one started."""

    model_config = ConfigDict(extra="forbid")

    state: str
    asr_job_id: UUID | None
    meeting_type: str
    started_at: datetime


class AttachTranscriptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version_number: int
    state: str


# ── Content assembly ────────────────────────────────────────────────


def _clean_names(names: list[str]) -> list[str]:
    """Attendee names as the note will show them: whitespace collapsed,
    control characters out, 1–80 characters, de-duplicated, ≤ 12."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in names:
        name = " ".join(raw.split())
        if not name or len(name) > MAX_NAME_CHARS:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) == MAX_ATTENDEE_NAMES:
            break
    return out


def calendar_context(calendar: CalendarContextIn | None) -> dict[str, Any]:
    """The stored shape: names and agenda lines only.

    The client may send either a parsed ``agenda_lines`` list (the web and
    native Google paths, which already have it from ``/v1/calendar/events``)
    or a raw ``description`` (EventKit, which only has the note field). The
    description is run through the same deterministic rules and discarded.
    """
    if calendar is None:
        return {}
    lines = [" ".join(line.split()) for line in calendar.agenda_lines]
    lines = [line[: agenda_rules.MAX_LINE_CHARS] for line in lines if line]
    if not lines:
        lines = list(agenda_rules.agenda_lines(calendar.description))
    context: dict[str, Any] = {"source": calendar.source}
    if calendar.title.strip():
        context["title"] = calendar.title.strip()[:512]
    if calendar.ical_uid:
        context["ical_uid"] = calendar.ical_uid
    names = _clean_names(calendar.attendee_names)
    if names:
        context["attendee_names"] = names
    if lines:
        context["agenda_lines"] = lines[:MAX_AGENDA_LINES]
    return context


def initial_content(
    *,
    definition: TemplateDefinition,
    template_id: UUID,
    schema_version: int,
    title: str,
    context: dict[str, Any],
) -> NoteContent:
    """v1 of a meeting note: every template section, empty, except the two
    the invite can already answer.

    ``user_notes`` is deliberately empty — it is the author's to fill, and
    a placeholder in it would be text they did not write.
    """
    attendees = context.get("attendee_names") or []
    agenda = context.get("agenda_lines") or []
    prefilled = {
        ATTENDEES_SECTION: "\n".join(attendees),
        AGENDA_SECTION: "\n".join(f"- [ ] {line}" for line in agenda),
    }
    return NoteContent(
        template_id=template_id,
        template_schema_version=schema_version,
        title=title,
        sections=[
            NoteSection(
                section_key=s.id,
                text=(
                    prefilled.get(s.id) or s.default_content
                    if s.field_type == FieldType.FREE_TEXT
                    else s.default_content
                ),
            )
            for s in sorted(definition.sections, key=lambda s: s.order)
        ],
    )


async def _pick_template(
    conn: asyncpg.Connection,
    *,
    template_id: UUID | None,
    meeting_type: str,
    language: str,
) -> tuple[UUID, TemplateDefinition, int, str]:
    """Explicit id, else the family for this meeting type in this
    language, else general meeting notes, else anything active.

    ``language='auto'`` is not yet a language: the recording has not been
    heard. The catalogue's lingua franca carries the headings until it is,
    and the transcript itself is never translated.
    """
    if template_id is not None:
        row = await get_template(conn, template_id=template_id)
        if row is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "template_not_found", "detail": "template_not_found"},
            )
        return template_id, _parse_definition(row), int(row["schema_version"]), str(row["name"])

    resolved = TEMPLATE_LANGUAGE_FALLBACK if language == "auto" else language
    candidates = await template_match.load_candidates(conn, language=resolved)
    if not candidates and resolved != TEMPLATE_LANGUAGE_FALLBACK:
        candidates = await template_match.load_candidates(conn, language=TEMPLATE_LANGUAGE_FALLBACK)
    if not candidates:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "no_templates", "detail": "no active templates"},
        )

    family = _TEMPLATE_FAMILY.get(meeting_type, _FALLBACK_FAMILY)
    # Per-language copies share the family's code prefix
    # ("sales_call", "sales_call_uk", …).
    for prefix in (family, _FALLBACK_FAMILY):
        for candidate in candidates:
            if candidate.code.startswith(prefix):
                return (
                    candidate.id,
                    candidate.definition,
                    candidate.schema_version,
                    candidate.name,
                )
    chosen = candidates[0]
    return chosen.id, chosen.definition, chosen.schema_version, chosen.name


# ── Routes ──────────────────────────────────────────────────────────


@router.post("/meeting", status_code=status.HTTP_201_CREATED, response_model=StartMeetingResponse)
async def start_meeting(
    body: StartMeetingRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> StartMeetingResponse:
    """Open the note. Called as Record is pressed — the client must not
    wait for it and must not let it stop the recording.

    Idempotent on ``client_capture_id``: a retry, a double tap and a
    second device that resumed the same capture all get the same note
    (200 rather than 201).
    """
    state = get_state()
    context = calendar_context(body.calendar)

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        existing = await meetings.find_by_capture(conn, client_capture_id=body.client_capture_id)
        if existing is not None:
            note = await repo.fetch_note(conn, note_id=existing.note_id)
            if note is not None:
                response.status_code = status.HTTP_200_OK
                return StartMeetingResponse(
                    id=note.id,
                    code=note.code,
                    version_number=note.current_version_number,
                    template_id=await _template_of(conn, note_id=note.id),
                    state=existing.state,
                )

        template_id, definition, schema_version, template_name = await _pick_template(
            conn,
            template_id=body.template_id,
            meeting_type=body.meeting_type,
            language=body.language,
        )
        chosen_title = body.title.strip() or str(context.get("title") or "").strip()
        title = (chosen_title or f"{template_name} — {date.today().isoformat()}")[:512]
        content = initial_content(
            definition=definition,
            template_id=template_id,
            schema_version=schema_version,
            title=title,
            context=context,
        )
        code = await code_sequence.next_code(conn, tenant_id=claims.tid)
        note_id, _version_id = await repo.create_note_with_v1(
            conn,
            tenant_id=claims.tid,
            code=code,
            primary_author_id=claims.sub,
            co_author_ids=[],
            template_id=template_id,
            template_schema_version=schema_version,
            source_session_id=None,
            content=content,
            # A title the author typed or their invite carried is theirs;
            # only the placeholder is for the generation job to replace.
            title_source="user" if chosen_title else "default",
        )
        try:
            await meetings.create(
                conn,
                note_id=note_id,
                tenant_id=claims.tid,
                created_by=claims.sub,
                client_capture_id=body.client_capture_id,
                meeting_type=body.meeting_type,
                started_at=body.started_at,
                calendar_context=context,
            )
        except asyncpg.UniqueViolationError:
            # Two devices pressed Record on the same capture at once; the
            # loser's note is rolled back with the transaction.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "capture_in_progress", "detail": "created concurrently"},
            ) from None

        # Sprint 36: a meeting in a series opens with what is still open
        # from last time. Deterministic, visibility-checked, and never
        # able to stop the meeting starting (see `link_and_carry`).
        carried = await series_service.link_and_carry(
            conn,
            claims=claims,
            note_id=note_id,
            started_at=body.started_at,
            title=title,
            calendar_context=context,
            content=content,
            language=TEMPLATE_LANGUAGE_FALLBACK if body.language == "auto" else body.language,
        )
        if carried != content:
            await repo.replace_v1_content(conn, note_id=note_id, content=carried)

    meeting_metrics.meetings_started.add(
        1, {"meeting_type": body.meeting_type, "has_calendar": str(bool(context)).lower()}
    )
    # Counts only: never the event title, the attendees or the agenda.
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_MEETING_STARTED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={
            "code": code,
            "meeting_type": body.meeting_type,
            "has_calendar": bool(context),
            "template_id": str(template_id),
        },
        severity=Severity.INFO,
    )
    return StartMeetingResponse(
        id=note_id,
        code=code,
        version_number=1,
        template_id=template_id,
        state="recording",
    )


async def _template_of(conn: asyncpg.Connection, *, note_id: UUID) -> UUID:
    template_id: UUID = await conn.fetchval("SELECT template_id FROM notes WHERE id = $1", note_id)
    return template_id


@router.put("/{note_id}/my-notes/timing", status_code=status.HTTP_204_NO_CONTENT)
async def put_line_times(
    note_id: UUID,
    body: LineTimesRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> None:
    """When each typed line was first touched, relative to the recording.

    First report wins: the line was typed once, and a later flush of the
    same key is the same line being edited, not heard again.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        await meetings.put_line_times(
            conn,
            tenant_id=claims.tid,
            note_id=note_id,
            lines=[(line.line_key, line.offset_ms) for line in body.lines],
        )


@router.post("/{note_id}/meeting/job", response_model=MeetingView)
async def attach_job(
    note_id: UUID,
    body: AttachJobRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> MeetingView:
    """The recording reached asr-service: bind the job to the note.

    Idempotent for the same pair. A job another note already owns is a
    409 ``already_assigned`` — the partial unique index on
    ``notes.source_asr_job_id`` is the single source of that truth,
    shared with ``from-transcript``.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        meeting = await _require_meeting(conn, note_id=note_id)
        if meeting.asr_job_id == body.asr_job_id:
            return _view(meeting)
        if meeting.asr_job_id is not None or note.source_asr_job_id is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "already_assigned",
                    "detail": "this note already has a recording",
                    "note_id": str(note_id),
                },
            )
        try:
            await conn.execute(
                "UPDATE notes SET source_asr_job_id = $2, updated_at = now() WHERE id = $1",
                note_id,
                body.asr_job_id,
            )
        except asyncpg.UniqueViolationError:
            owner = await conn.fetchrow(
                "SELECT id, code FROM notes WHERE source_asr_job_id = $1 AND deleted_at IS NULL",
                body.asr_job_id,
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "already_assigned",
                    "detail": "this transcription is already assigned to a note",
                    **({"note_id": str(owner["id"]), "note_code": owner["code"]} if owner else {}),
                },
            ) from None
        await meetings.bind_job(conn, note_id=note_id, asr_job_id=body.asr_job_id)
        return _view(await _require_meeting(conn, note_id=note_id))


@router.post("/{note_id}/transcript", response_model=AttachTranscriptResponse)
async def attach_transcript(
    note_id: UUID,
    request: Request,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> AttachTranscriptResponse:
    """The transcription finished: put it in the note.

    Called by ANY client of the author, on any device — which is how a
    meeting survives the laptop being closed mid-transcription. The job's
    ownership is proven the only way that is safe: by fetching the result
    with the caller's own bearer, so asr-service applies its own tenant
    and permission checks.
    """
    state = get_state()
    auth_header = request.headers.get("authorization") or ""

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        meeting = await _require_meeting(conn, note_id=note_id)
        job_id = meeting.asr_job_id or note.source_asr_job_id
        if job_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "no_job", "detail": "no recording is attached yet"},
            )
        if meeting.state == "ready":
            # A second device got there first. The note is written; saying
            # so is more useful than a conflict the client must decode.
            return AttachTranscriptResponse(
                id=note_id, version_number=note.current_version_number, state=meeting.state
            )
        if note.status != NoteStatus.DRAFT:
            raise HTTPException(
                status.HTTP_410_GONE,
                detail={"code": "note_cancelled", "detail": "the note is no longer a draft"},
            )

    # Outside the transaction: the ASR fetch is a network call, and
    # holding a tenant connection across it would pin the pool.
    result = await _fetch_transcript(job_id, auth_header=auth_header)
    transcript = _transcript_text(result)
    budget_crossed: tuple[int, int] | None = None

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.lock_note_for_update(conn, note_id=note_id), claims)
        meeting = await _require_meeting(conn, note_id=note_id)
        if meeting.state == "ready":
            return AttachTranscriptResponse(
                id=note_id, version_number=note.current_version_number, state=meeting.state
            )
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "no_version", "detail": "note has no current version"},
            )
        content = _with_transcript(version.content, transcript)
        version_number = note.current_version_number
        if content != version.content:
            # An empty transcript (silence, a discarded take) writes no
            # version: the note is what the author typed, and a duplicate
            # version in the hash chain says nothing happened twice.
            try:
                _, version_number = await repo.append_version(
                    conn,
                    note_id=note_id,
                    expected_version=note.current_version_number,
                    new_content=content,
                    created_by=claims.sub,
                    diff_jsonb={},
                )
            except OptimisticLockMismatchError as exc:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "code": "note_changed",
                        "detail": "the note was edited while the transcript was being fetched",
                        "current_version": exc.current_version,
                    },
                ) from None
        # Sprint 33: the note writes itself, exactly as it does for a
        # note made with `from-transcript`. Same transaction as the
        # transcript version, so the snapshot, the generation row and the
        # job exist together or not at all — and never able to cost the
        # capture: a stack with no object store or no model still ends
        # with the transcript in the note, as before. Silence starts no
        # run: there is nothing to write from.
        if transcript and settings.note_generation_enabled:
            try:
                await generation_service.start(
                    conn,
                    queue=state.job_queue,
                    store=state.transcripts_store,
                    tenant_id=claims.tid,
                    note_id=note_id,
                    requested_by=claims.sub,
                    transcript=result,
                    reason="auto",
                    transcript_rev=int(result.get("result_rev") or 1),
                    required_processors=ai_settings_router.required_processors(),
                )
            except generation_service.GenerationDisabledError:
                # The workspace turned it off. Not an error.
                pass
            except generation_service.ProcessorUnacknowledgedError:
                # Sprint L2: nobody agreed to a processor in the data path;
                # the generation view says so, the capture is still ready.
                logger.info(
                    "meeting.generation_blocked", extra={"reason": "processor_unacknowledged"}
                )
            except generation_service.BudgetExceededError as exc:
                budget_crossed = (exc.spent, exc.budget)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "meeting.generation_not_started",
                    extra={"note_id": str(note_id)},
                    exc_info=True,
                )
        # The capture is done the moment the transcript is in the note.
        # The engine's own progress lives on the generation row
        # (`GET /{note_id}/generation`); the meeting state does not
        # follow it, so a stalled run never leaves a capture "generating".
        await meetings.set_state(conn, note_id=note_id, state="ready")

    if budget_crossed is not None:
        await emit_budget_reached(
            state.redis,
            tenant_id=claims.tid,
            actor_user_id=claims.sub,
            spent_cents=budget_crossed[0],
            budget_cents=budget_crossed[1],
        )

    same_device = request.headers.get("x-mdx-client-capture") == str(meeting.client_capture_id)
    meeting_metrics.transcripts_attached.add(1, {"device_same": str(same_device).lower()})
    # U1: did the author type at all? Counted once per capture, at the one
    # moment the whole scratchpad is known. A bucket, never the lines.
    typed = user_notes_rules.split_lines(
        next((s.text for s in content.sections if s.section_key == USER_NOTES_SECTION), "")
    )
    meeting_metrics.user_lines.add(1, {"bucket": meeting_metrics.line_bucket(len(typed))})
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_MEETING_TRANSCRIPT_ATTACHED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={"asr_job_id": str(job_id), "device_same": same_device},
        severity=Severity.INFO,
    )
    return AttachTranscriptResponse(id=note_id, version_number=version_number, state="ready")


def _with_transcript(content: NoteContent, transcript: str) -> NoteContent:
    """Put the transcript in its section, leaving every other one — above
    all ``user_notes`` — byte-identical.

    An existing body in the target section is kept and the transcript
    appended: the author may have typed there before the recording landed,
    and nothing in this sprint overwrites their characters.
    """
    if not transcript:
        return content
    sections = list(content.sections)
    key = _transcript_section_key(sections)
    out: list[NoteSection] = []
    for section in sections:
        if section.section_key != key:
            out.append(section)
            continue
        body = section.text.rstrip()
        out.append(
            section.model_copy(update={"text": f"{body}\n\n{transcript}" if body else transcript})
        )
    return content.model_copy(update={"sections": out})


def _transcript_section_key(sections: list[NoteSection]) -> str | None:
    """Which section the transcript lands in: a prose home if the template
    has one, else the first section that is neither the author's scratchpad
    nor the attendee list. Same order as ``from-transcript``'s
    ``_transcript_home`` — one rule, two entry points.
    """
    keys = [s.section_key for s in sections]
    for candidate in _PROSE_HOMES:
        if candidate in keys:
            return candidate
    for key in keys:
        if key not in (USER_NOTES_SECTION, ATTENDEES_SECTION, AGENDA_SECTION):
            return key
    return keys[0] if keys else None


@router.post("/{note_id}/meeting/no-audio", response_model=MeetingView)
async def mark_no_audio(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> MeetingView:
    """The recording was discarded or never happened. The note stays — it
    holds what the author typed, which is the part that cannot be redone."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        meeting = await _require_meeting(conn, note_id=note_id)
        if meeting.state not in ("ready", "generating"):
            await meetings.set_state(conn, note_id=note_id, state="no_audio")
        return _view(await _require_meeting(conn, note_id=note_id))


@router.get("/{note_id}/meeting", response_model=MeetingView)
async def get_meeting(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> MeetingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        return _view(await _require_meeting(conn, note_id=note_id))


async def _require_meeting(conn: asyncpg.Connection, *, note_id: UUID) -> meetings.MeetingRow:
    """The sidecar, or 404. A note made by ``from-transcript`` or by hand
    has none, and is not a capture."""
    meeting = await meetings.fetch(conn, note_id=note_id)
    if meeting is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "not_a_meeting", "detail": "this note is not a live capture"},
        )
    return meeting


def _view(meeting: meetings.MeetingRow) -> MeetingView:
    return MeetingView(
        state=meeting.state,
        asr_job_id=meeting.asr_job_id,
        meeting_type=meeting.meeting_type,
        started_at=meeting.started_at.astimezone(UTC),
    )
