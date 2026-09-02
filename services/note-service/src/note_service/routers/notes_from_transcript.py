"""Create a draft note from a batch transcription.

``POST /v1/notes/from-transcript`` — fetch a COMPLETE asr job's
NLP-enriched transcript from asr-service (the caller's own bearer is
forwarded; asr-service authorizes + tenant-scopes the read and audits
it), pick a template (explicit ``template_id`` or deterministic
auto-match), and create a draft note whose first free-text section
holds the transcript. The note then follows the normal note
lifecycle (edit → finalize).

``GET /v1/notes/by-source-job`` — bulk lookup so the transcription
jobs list can badge jobs that are already assigned.

One note per source job per tenant is enforced by a partial unique
index (migration 0045); a concurrent double-assign surfaces as 409.
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
from ..domain import code_sequence, template_match
from ..domain import notes_repository as repo
from ..domain.field_extraction_client import extract_fields
from ..domain.repository import get_template

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
            resp = await client.get(url, headers={"Authorization": auth_header})
    except httpx.HTTPError as exc:
        logger.warning("from_transcript.asr_unreachable: %s", exc.__class__.__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "asr_service_unavailable"},
        ) from exc

    if resp.status_code == status.HTTP_200_OK:
        return resp.json()  # type: ignore[no-any-return]

    # Pass through the statuses that carry meaning for the caller:
    # 404 unknown job, 409 not complete yet, 410 transcript erased,
    # 403 the caller may not read that job.
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
    """A diarized batch result carries top-level ``speakers`` (distinct
    labels, first-appearance order) and per-segment ``speaker`` labels.
    Either signal counts — a producer that labels segments but omits the
    roster still gets dialogue rendering."""
    if result.get("speakers"):
        return True
    if any(t.get("speaker") for t in result.get("turns", [])):
        return True
    return any(seg.get("speaker") for seg in result.get("segments", []))


# What an unattributed turn is labelled in a diarized note. Honest, not
# a guess: the diarizer heard someone it could not place.
UNKNOWN_SPEAKER = "Unknown speaker"


def _turns_text(result: dict[str, Any]) -> str:
    """Render asr-service's ``turns`` as the note body.

    asr-service already decided the structure (``asr_models.structure``:
    consecutive same-speaker segments are one turn, long turns break into
    paragraphs at pauses and sentence ends) and the display names (what a
    person named the speaker, else "Speaker N"). Here that becomes text:

        Mark: First paragraph of Mark's turn.
        Second paragraph of the same turn.

        Olena: Her reply.

    Turns are separated by a blank line so they read as paragraphs in
    the editor; the name sits at the start of the turn's first line, the
    form both apps rewrite when a speaker is renamed later. An undiarized
    transcript is one unattributed turn and renders as plain paragraphs.
    """
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
    """``SPEAKER_2`` → ``Speaker 2`` (mirrors ``asr_models.default_speaker_name``;
    note-service reads the transcript as JSON and does not depend on that lib)."""
    if label.startswith("SPEAKER_") and label[8:].isdigit():
        return f"Speaker {label[8:]}"
    return label


def _dialogue_text(result: dict[str, Any]) -> str:
    """Render a diarized transcript WITHOUT server-side turns as
    speaker-turn dialogue lines (a producer older than the ``turns``
    field, or a test fixture).

    Mirrors dictation-service's ``session/draft.py::dialogue_text``: one
    block per contiguous same-speaker run, a segment without a label
    rendered under the honesty label rather than silently merged into a
    neighbouring speaker's turn. Batch labels are the neutral
    ``SPEAKER_N`` form (ambient-capture contract); a ``speaker_names``
    map on the result names them, else the default "Speaker N".
    """
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
    # asr-service ships the transcript pre-structured (speaker turns,
    # paragraphs, display names); render that when it is there.
    if result.get("turns"):
        return _turns_text(result)
    # Diarized results (ambient capture: batch jobs run with diarize=true)
    # become speaker-turn dialogue, matching what a live conversation
    # session's finalize draft looks like.
    if _is_diarized(result):
        return _dialogue_text(result)
    # No structure at all (an older producer): flat prose, joined with
    # spaces so a round-trip through the editor keeps it intact.
    parts = [str(seg.get("text", "")).strip() for seg in result.get("segments", [])]
    return " ".join(p for p in parts if p)


def _content_for_template(
    *,
    definition: TemplateDefinition,
    template_id: UUID,
    schema_version: int,
    transcript: str,
    title: str,
    extracted_fields: dict[str, dict[str, Any]] | None = None,
) -> NoteContent:
    """All template sections in order; the transcript lands in the first
    free-text section (dictations are linear speech — distributing text
    across sections is the author's edit, not a guess we make).

    Sprint 13: typed sections additionally carry the extractor's
    PROPOSALS in ``field_specific_metadata`` (``source: "extracted"``).
    The prose always stays intact in the free-text section — a proposal
    never consumes or rewrites what was dictated.
    """
    ordered = sorted(definition.sections, key=lambda s: s.order)
    target = next((s for s in ordered if s.field_type == FieldType.FREE_TEXT), ordered[0])
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


# Where to look when a transcript's language has no templates of its own
# (a German or Polish recording under an auto-detected job): the
# catalogue's lingua franca. The transcript itself is untouched — only
# the section headings come from the fallback template.
TEMPLATE_LANGUAGE_FALLBACK = "en"


async def _candidates_for_language(
    conn: asyncpg.Connection, language: str
) -> tuple[list[template_match.TemplateCandidate], str]:
    """Active templates in ``language``, else in the fallback language.

    Returns the candidates and the language they are actually in.
    """
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
    # The language the transcript is IN — for an auto-detected job, what
    # the worker heard. The note follows it: template (section headings,
    # prompts) and field extraction are chosen for that language.
    language = str(result.get("language") or "uk")

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        existing = await conn.fetchrow(
            "SELECT id, code FROM notes WHERE source_asr_job_id = $1",
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
        # Sprint 13 (ADR-0028): typed-field proposals. Fail-open — an
        # unreachable nlp-service costs proposals, not the draft.
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
            )
        except asyncpg.UniqueViolationError:
            # Concurrent double-assign lost the race on the partial index.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "already_assigned", "detail": "assigned concurrently"},
            ) from None

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
