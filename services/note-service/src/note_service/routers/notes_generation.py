"""The generation surface.

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
from ..domain import glossary_repository as glossary_repo
from ..domain import notes_repository as repo
from ..domain.meeting_doc import entities
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


class StageModel(BaseModel):
    """Which backend and model actually answered one stage's calls, and how many failed."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    backend: str | None
    model_id: str | None
    calls: int
    failed: int
    """sha256 of every distinct system text this stage sent."""
    system_hashes: list[str] = []


class PromptCall(BaseModel):
    """One call the resolver says this run makes, and whether a request with exactly
    that system text was sent (a retry with a suffix is a different text)."""

    model_config = ConfigDict(extra="forbid")

    call: str
    sha: str
    sent: bool


class ModelFallback(BaseModel):
    """A model override that landed on its fallback in the worker, and why."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    backend: str
    primary: str
    reason: str | None


class InstructionsRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """`workspace`, a meeting family (`client`, …) or `note` (N4)."""
    scope: str
    version: int
    """`stale`: the type's text was being updated, so the workspace's wrote the note."""
    fallback: str | None = None


class Provenance(BaseModel):
    """F1-01 — what produced this run, so two results can be told apart: the code, the
    prompt and profile versions, both flags as the run EXECUTED them and where they came
    from (``snapshot``: pinned at enqueue; ``deployment``: a row from before snapshots),
    the output language and its source, the transcript revision, and the models that
    answered. While queued or running it is the pinned snapshot; null fields are unknown."""

    model_config = ConfigDict(extra="forbid")

    run_kind: str
    build_sha: str | None = None
    pinned_build_sha: str | None = None
    prompt_version: str
    profile_version_id: str | None = None
    algorithm_version: str | None = None
    flags_source: Literal["snapshot", "deployment"] | None = None
    multilingual_evidence: bool | None = None
    fidelity: bool | None = None
    final_check: bool | None = None
    """Flags the worker's deployment has set differently from what the job was pinned with."""
    flags_differ: list[str] = []
    output_language: str | None = None
    output_language_source: str | None = None
    transcript_rev: int | None = None
    stages: list[StageModel] = []
    fallbacks: list[ModelFallback] = []
    prompt_calls: list[PromptCall] = []


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
    """Why a finished note is not complete without missing minutes: ``summary_composed``,
    ``topics_chapters``, ``claims_unverified``. Empty for complete and older generations."""
    incomplete_reasons: list[str] = []
    """The transcript revision it was written from, and the languages its lines were
    spoken in (recording's first); empty for generations before multilingual evidence."""
    transcript_rev: int | None = None
    source_languages: list[str] = []
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
    provenance: Provenance | None = None
    """N2 — the workspace's note instructions this run was written under; null: none."""
    instructions: InstructionsRef | None = None
    """N0 — the version of the workspace's model settings (style and parameters) that
    wrote it; 0: the defaults; null: a run from before N0."""
    model_settings_version: int | None = None
    """N0 — the writing style that wrote it (`business`, …); null before N0."""
    writing_style: str | None = None

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
    """B4 — what the line is: the speaker's words, one fact, or several. Null for rows
    written before the column existed."""
    provenance: Literal["verbatim", "paraphrase", "composed"] | None = None
    """B4 — a claim row's verdict cell (the label and the speaker's clause)."""
    verdict: str | None = None


def _excluded(stats: dict) -> list[ExcludedRange]:
    out: list[ExcludedRange] = []
    for entry in stats.get("excluded_ranges") or []:
        if isinstance(entry, (list, tuple)) and len(entry) == 3:
            out.append(
                ExcludedRange(start_ms=int(entry[0]), end_ms=int(entry[1]), reason=str(entry[2]))
            )
    return out


def _source_languages(stats: dict) -> list[str]:
    """Languages with spoken lines in this generation, the recording's first."""
    languages = stats.get("languages") or {}
    first = stats.get("recording_language")
    spoken = [c for c, v in languages.items() if c != "unknown" and (v or {}).get("lines")]
    return sorted(spoken, key=lambda c: (c != first, c))


def _coverage(stats: dict) -> Coverage | None:
    thirds = stats.get("facts_by_third")
    if not isinstance(thirds, list) or len(thirds) != 3:
        return None
    return Coverage(
        facts_by_third=[int(n) for n in thirds],
        speech_ms=int(stats.get("speech_ms") or 0),
        excluded_ms=int(stats.get("excluded_ms") or 0),
    )


def _provenance(row: gen_repo.GenerationRow) -> Provenance:
    stats = row.stats or {}
    sent = {str(h) for c in stats.get("calls") or [] for h in c.get("system_hashes") or []}
    pinned = getattr(row, "config_snapshot", None) or {}
    runtime = stats.get("runtime") or {}
    flags = runtime.get("flags") or {}
    final = (stats.get("final_check") or {}).get("ran")
    return Provenance(
        run_kind=str(runtime.get("run_kind") or pinned.get("run_kind") or "generation"),
        build_sha=runtime.get("build_sha"),
        pinned_build_sha=runtime.get("pinned_build_sha") or pinned.get("build_sha"),
        prompt_version=row.prompt_version,
        profile_version_id=stats.get("profile_version_id") or pinned.get("profile_version_id"),
        algorithm_version=runtime.get("algorithm_version") or pinned.get("algorithm_version"),
        flags_source=runtime.get("flags_source") or ("snapshot" if pinned else None),
        multilingual_evidence=flags.get("multilingual", pinned.get("multilingual")),
        fidelity=flags.get("fidelity", pinned.get("fidelity")),
        final_check=final if final is not None else runtime.get("final_check"),
        flags_differ=[str(f) for f in runtime.get("flags_differ") or []],
        output_language=stats.get("output_language") or pinned.get("output_language"),
        output_language_source=stats.get("output_language_source"),
        transcript_rev=getattr(row, "transcript_rev", None),
        stages=[
            StageModel(
                stage=str(c.get("stage")),
                backend=c.get("backend"),
                model_id=c.get("model_id"),
                calls=int(c.get("calls") or 0),
                failed=int(c.get("failed") or 0),
                system_hashes=[str(h) for h in c.get("system_hashes") or []],
            )
            for c in stats.get("calls") or []
        ],
        prompt_calls=[
            PromptCall(call=str(call), sha=str(sha), sent=str(sha) in sent)
            for call, sha in (stats.get("prompt_hashes") or {}).items()
        ],
        fallbacks=[
            ModelFallback(
                kind=str(f.get("kind")),
                backend=str(f.get("backend")),
                primary=str(f.get("primary")),
                reason=f.get("reason"),
            )
            for f in runtime.get("fallbacks") or []
        ],
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
        incomplete_reasons=[str(r) for r in stats.get("incomplete") or []],
        transcript_rev=getattr(row, "transcript_rev", None),
        source_languages=_source_languages(stats),
        coverage=_coverage(stats),
        recording_type=stats.get("recording_type"),
        recording_type_source=stats.get("recording_type_source"),
        language=stats.get("language"),
        provenance=_provenance(row),
        instructions=_instructions_ref(stats),
        model_settings_version=_model_settings_version(stats),
        writing_style=str(stats["writing_style"]) if stats.get("writing_style") else None,
    )


def _model_settings_version(stats: dict[str, object]) -> int | None:
    ref = stats.get("model_params")
    return int(ref["version"]) if isinstance(ref, dict) and "version" in ref else None


def _instructions_ref(stats: dict[str, object]) -> InstructionsRef | None:
    ref = stats.get("instructions")
    if not isinstance(ref, dict) or "version" not in ref:
        return None
    return InstructionsRef(
        scope=str(ref.get("scope") or "workspace"),
        version=int(ref["version"]),
        fallback=str(ref["fallback"]) if ref.get("fallback") else None,
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
        note = access.require_edit(await repo.fetch_note(conn, note_id=note_id), claims)
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

    # Outside the transaction: a network call must not hold a pooled connection;
    # asr-service authorises the read with the caller's own bearer.
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
            # The list in the error is what the client shows in the dialog.
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
        reviewed = await glossary_repo.reviewed_name_tags(conn, note_id=note_id)
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
            corrections=_undecided(_json_list(_get(r, "corrections")), reviewed),
            mentions=_json_list(_get(r, "mentions")),
            provenance=_line_provenance(_get(r, "provenance")),
            verdict=_verdict(_get(r, "payload")) if r["kind"] == "claim" else None,
        )
        for r in rows
    ]


def _line_provenance(value: object) -> Literal["verbatim", "paraphrase", "composed"] | None:
    return value if value in ("verbatim", "paraphrase", "composed") else None  # type: ignore[return-value]


def _verdict(value: object) -> str | None:
    """B4 — a claim row's verdict from its payload."""
    import json

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict) and isinstance(value.get("verdict"), str):
        return value["verdict"] or None
    return None


def _get(row: object, key: str) -> object:
    """A column that may be absent (a row read before 0059, a test fake)."""
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError):
        return None


def _undecided(corrections: list[object], reviewed: set[str]) -> list[object]:
    """The respellings still waiting for the author; one decided anywhere in the note is not
    offered again, and grammar is never offered (F2-02: an article, an ending or capitals,
    as rows stored before the guard may still carry)."""
    return [
        c
        for c in corrections
        if not isinstance(c, dict)
        or (
            entities.is_correction(str(c.get("surface", "")), str(c.get("canonical", "")))
            and glossary_repo.name_review_tag(
                str(c.get("surface", "")), str(c.get("canonical", ""))
            )
            not in reviewed
        )
    ]


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
