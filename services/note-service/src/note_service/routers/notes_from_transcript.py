"""Create a draft note from a batch transcription (the caller's bearer is forwarded
to asr-service, which authorizes and tenant-scopes the read).

One note per source job per tenant is enforced by a partial unique index; a
concurrent double-assign surfaces as 409.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteContent, NoteSection
from template_models import FieldType, TemplateDefinition

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import code_sequence, generation_service, template_match
from ..domain import notes_repository as repo
from ..domain.field_extraction_client import extract_fields
from ..domain.repository import get_template
from ..notifications import emit_budget_reached
from . import ai_settings as ai_settings_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

_ASR_TIMEOUT = httpx.Timeout(connect=2.0, read=15.0, write=5.0, pool=5.0)


# ── Wire models ─────────────────────────────────────────────────────


class CreateFromTranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asr_job_id: UUID
    # Omitted → deterministic auto-match against the transcript.
    template_id: UUID | None = None
    title: str = Field(default="", max_length=512)


class FromTranscriptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    version_id: UUID
    version_number: int
    status: str
    template_id: UUID
    template_name: str
    template_selection: Literal["explicit", "auto", "fallback"]
    template_score: int | None = None
    # Present when the engine is writing this note, so the client can start polling.
    generation: GenerationStub | None = None
    # Why no generation, when there is none.
    generation_blocked: (
        Literal["generation_disabled", "budget_exceeded", "processor_unacknowledged"] | None
    ) = None


class GenerationStub(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str


class SourceJobLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asr_job_id: UUID
    note_id: UUID
    code: str
    status: str


# ── asr-service fetch ───────────────────────────────────────────────


async def _fetch_transcript(job_id: UUID, *, auth_header: str) -> dict[str, Any]:
    url = f"{settings.asr_service_base_url.rstrip('/')}/asr/jobs/{job_id}/result"
    try:
        async with httpx.AsyncClient(timeout=_ASR_TIMEOUT) as client:
            # Not a person opening the transcript: asr-service must not count it
            # in the speaker-correction denominator.
            resp = await client.get(
                url,
                headers={"Authorization": auth_header, "X-MDX-Read-Purpose": "note_build"},
            )
    except httpx.HTTPError as exc:
        logger.warning("from_transcript.asr_unreachable: %s", exc.__class__.__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "asr_service_unavailable"},
        ) from exc

    if resp.status_code == status.HTTP_200_OK:
        return resp.json()  # type: ignore[no-any-return]

    # 404 unknown job, 409 not complete yet, 410 transcript erased, 403 may not read.
    if resp.status_code in (403, 404, 409, 410):
        try:
            detail = resp.json().get("detail", resp.json())
        except Exception:  # noqa: BLE001
            detail = {"error": "transcript_unavailable"}
        raise HTTPException(resp.status_code, detail=detail)

    logger.warning("from_transcript.asr_unexpected_status: %s", resp.status_code)
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        detail={"error": "asr_service_error", "upstream_status": resp.status_code},
    )


# ── Content assembly ────────────────────────────────────────────────


def _is_diarized(result: dict[str, Any]) -> bool:
    """Top-level ``speakers`` or per-segment ``speaker`` labels; either signal counts."""
    if result.get("speakers"):
        return True
    if any(t.get("speaker") for t in result.get("turns", [])):
        return True
    return any(seg.get("speaker") for seg in result.get("segments", []))


# Label for an unattributed turn in a diarized note.
UNKNOWN_SPEAKER = "Unknown speaker"


def _turns_text(result: dict[str, Any]) -> str:
    """Render asr-service's ``turns`` as the note body: "Name: first paragraph",
    blank line between turns. The name at the start of a turn's first line is the
    form both apps rewrite when a speaker is renamed later."""
    blocks: list[str] = []
    diarized = _is_diarized(result)
    for turn in result.get("turns", []):
        paragraphs = [str(p).strip() for p in turn.get("paragraphs", []) if str(p).strip()]
        if not paragraphs:
            continue
        if diarized:
            label = turn.get("name") or (
                default_speaker_name(str(turn["speaker"]))
                if turn.get("speaker")
                else UNKNOWN_SPEAKER
            )
            paragraphs[0] = f"{label}: {paragraphs[0]}"
        blocks.append("\n".join(paragraphs))
    return "\n\n".join(blocks)


def default_speaker_name(label: str) -> str:
    """``SPEAKER_2`` → ``Speaker 2`` (mirrors ``asr_models.default_speaker_name``)."""
    if label.startswith("SPEAKER_") and label[8:].isdigit():
        return f"Speaker {label[8:]}"
    return label


def _dialogue_text(result: dict[str, Any]) -> str:
    """Render a diarized transcript WITHOUT server-side turns as dialogue lines
    (mirrors dictation-service ``session/draft.py::dialogue_text``): one block per
    same-speaker run; an unlabelled segment gets UNKNOWN_SPEAKER, never merged."""
    names = result.get("speaker_names") or {}
    lines: list[str] = []
    prev_key: object = object()
    for seg in result.get("segments", []):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        speaker = seg.get("speaker")
        label = (
            (names.get(speaker) or default_speaker_name(str(speaker)))
            if speaker
            else UNKNOWN_SPEAKER
        )
        if speaker == prev_key and lines:
            lines[-1] = f"{lines[-1]} {text}"
        else:
            lines.append(f"{label}: {text}")
        prev_key = speaker
    return "\n\n".join(lines)


def _transcript_text(result: dict[str, Any]) -> str:
    if result.get("turns"):
        return _turns_text(result)
    if _is_diarized(result):
        return _dialogue_text(result)
    # No structure (an older producer): flat prose joined with spaces.
    parts = [str(seg.get("text", "")).strip() for seg in result.get("segments", [])]
    return " ".join(p for p in parts if p)


# Section ids that are made for running prose, best first.
_PROSE_HOMES = ("transcript", "discussion", "notes", "summary", "conversation", "body")


def _transcript_home(ordered: list[Any]) -> Any:
    free = [s for s in ordered if s.field_type == FieldType.FREE_TEXT]
    for key in _PROSE_HOMES:
        for s in free:
            if s.id == key:
                return s
    for s in free:
        if s.id != "attendees":
            return s
    return free[0] if free else ordered[0]


def _content_for_template(
    *,
    definition: TemplateDefinition,
    template_id: UUID,
    schema_version: int,
    transcript: str,
    title: str,
    extracted_fields: dict[str, dict[str, Any]] | None = None,
) -> NoteContent:
    """All template sections in order; the transcript lands in ONE free-text
    section (a prose home first, else any free-text section but the attendee list).
    Typed sections carry the extractor's PROPOSALS in ``field_specific_metadata``;
    the prose always stays intact."""
    ordered = sorted(definition.sections, key=lambda s: s.order)
    target = _transcript_home(ordered)
    proposals = extracted_fields or {}
    sections = [
        NoteSection(
            section_key=s.id,
            text=transcript if s.id == target.id else s.default_content,
            field_specific_metadata=proposals.get(s.id, {}),
        )
        for s in ordered
    ]
    return NoteContent(
        template_id=template_id,
        template_schema_version=schema_version,
        title=title,
        sections=sections,
    )


# Template language when the transcript's has none; only the section headings follow it.
TEMPLATE_LANGUAGE_FALLBACK = "en"


async def _candidates_for_language(
    conn: asyncpg.Connection, language: str
) -> tuple[list[template_match.TemplateCandidate], str]:
    """Active templates in ``language``, else in the fallback; returns (candidates, their language)."""
    candidates = await template_match.load_candidates(conn, language=language)
    if candidates or language == TEMPLATE_LANGUAGE_FALLBACK:
        return candidates, language
    fallback = await template_match.load_candidates(conn, language=TEMPLATE_LANGUAGE_FALLBACK)
    return fallback, TEMPLATE_LANGUAGE_FALLBACK


# ── Routes ──────────────────────────────────────────────────────────


@router.post(
    "/from-transcript",
    status_code=status.HTTP_201_CREATED,
    response_model=FromTranscriptResponse,
)
async def create_note_from_transcript(
    body: CreateFromTranscriptRequest,
    request: Request,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> FromTranscriptResponse:
    state = get_state()
    auth_header = request.headers.get("authorization") or ""

    result = await _fetch_transcript(body.asr_job_id, auth_header=auth_header)
    transcript = _transcript_text(result)
    if not transcript:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_transcript", "detail": "the job's transcript is empty"},
        )
    # The note follows the transcript's language: template and field extraction.
    language = str(result.get("language") or "uk")

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        existing = await conn.fetchrow(
            # A note in the bin has let go of its job.
            "SELECT id, code FROM notes WHERE source_asr_job_id = $1 AND deleted_at IS NULL",
            body.asr_job_id,
        )
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "already_assigned",
                    "detail": "this transcription is already assigned to a note",
                    "note_id": str(existing["id"]),
                    "note_code": existing["code"],
                },
            )

        selection: str
        score: int | None = None
        if body.template_id is not None:
            row = await get_template(conn, template_id=body.template_id)
            if row is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "template_not_found", "detail": "template_not_found"},
                )
            definition = _parse_definition(row)
            template_id, template_name = body.template_id, str(row["name"])
            schema_version = int(row["schema_version"])
            selection = "explicit"
        else:
            candidates, template_language = await _candidates_for_language(conn, language)
            choice = template_match.select_template(candidates, transcript)
            if choice is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "no_templates",
                        "detail": f"no active {language} templates to assign against",
                    },
                )
            if template_language != language:
                logger.info(
                    "from_transcript.template_language_fallback",
                    extra={"transcript_language": language, "template_language": template_language},
                )
            definition = choice.candidate.definition
            template_id, template_name = choice.candidate.id, choice.candidate.name
            schema_version = choice.candidate.schema_version
            selection, score = choice.mode, choice.score

        title = body.title.strip() or f"{template_name} — {date.today().isoformat()}"
        # Typed-field proposals (ADR-0028). Fail-open: costs proposals, not the draft.
        extracted_fields = await extract_fields(
            definition=definition,
            text=transcript,
            language=language,
            category=definition.category,
            authorization=auth_header,
        )
        content = _content_for_template(
            definition=definition,
            template_id=template_id,
            schema_version=schema_version,
            transcript=transcript,
            title=title,
            extracted_fields=extracted_fields,
        )

        code = await code_sequence.next_code(conn, tenant_id=claims.tid)
        generation_id: UUID | None = None
        generation_status = ""
        generation_blocked: str | None = None
        budget_crossed: tuple[int, int] | None = None
        try:
            note_id, version_id = await repo.create_note_with_v1(
                conn,
                tenant_id=claims.tid,
                code=code,
                primary_author_id=claims.sub,
                co_author_ids=[],
                template_id=template_id,
                template_schema_version=schema_version,
                source_session_id=None,
                content=content,
                source_asr_job_id=body.asr_job_id,
                title_source="user" if body.title.strip() else "default",
            )
        except asyncpg.UniqueViolationError:
            # Concurrent double-assign lost the race on the partial index.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "already_assigned", "detail": "assigned concurrently"},
            ) from None

        # Same transaction as the note (both exist or neither); never able to cost the note.
        if settings.note_generation_enabled:
            try:
                generation_id, generation_status = await generation_service.start(
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
                # The workspace turned it off: not an error.
                generation_id = None
                generation_blocked = "generation_disabled"
            except generation_service.ProcessorUnacknowledgedError:
                # A processor nobody agreed to; the Data page shows the dialog.
                generation_id = None
                generation_blocked = "processor_unacknowledged"
            except generation_service.BudgetExceededError as exc:
                generation_id = None
                generation_blocked = "budget_exceeded"
                budget_crossed = (exc.spent, exc.budget)
            except Exception:  # noqa: BLE001
                generation_id = None
                logger.warning(
                    "from_transcript.generation_not_started",
                    extra={"note_id": str(note_id)},
                    exc_info=True,
                )

    if budget_crossed is not None:
        await emit_budget_reached(
            state.redis,
            tenant_id=claims.tid,
            actor_user_id=claims.sub,
            spent_cents=budget_crossed[0],
            budget_cents=budget_crossed[1],
        )

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_CREATED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={
            "code": code,
            "version_id": str(version_id),
            "source_asr_job_id": str(body.asr_job_id),
            "template_selection": selection,
            "template_id": str(template_id),
        },
        severity=Severity.INFO,
    )

    return FromTranscriptResponse(
        generation=(
            GenerationStub(id=generation_id, status=generation_status)
            if generation_id is not None
            else None
        ),
        generation_blocked=generation_blocked,  # type: ignore[arg-type]
        id=note_id,
        code=code,
        version_id=version_id,
        version_number=1,
        status="draft",
        template_id=template_id,
        template_name=template_name,
        template_selection=selection,  # type: ignore[arg-type]
        template_score=score,
    )


@router.get("/by-source-job", response_model=list[SourceJobLink])
async def notes_by_source_job(
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    ids: Annotated[str, Query(description="Comma-separated asr job UUIDs (≤200).")],
) -> list[SourceJobLink]:
    try:
        job_ids = [UUID(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ids must be UUIDs"
        ) from None
    if not job_ids or len(job_ids) > 200:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="between 1 and 200 ids")
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        rows = await repo.fetch_notes_by_source_jobs(conn, asr_job_ids=job_ids)
    return [
        SourceJobLink(
            asr_job_id=row["source_asr_job_id"],
            note_id=row["id"],
            code=row["code"],
            status=str(row["status"]),
        )
        for row in rows
    ]


def _parse_definition(row: asyncpg.Record) -> TemplateDefinition:
    import json

    raw = row["schema_jsonb"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    try:
        return TemplateDefinition.model_validate(raw)
    except Exception:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "template_invalid", "detail": "template schema failed to parse"},
        ) from None
