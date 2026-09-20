"""``/asr/jobs`` — submit, list, fetch, cancel batch ASR jobs.

Notes:

- The POST handler streams the file body into a bounded in-memory buffer
  (``Settings.max_upload_mb``); FastAPI's underlying Starlette respects
  the size cap and fails the request early when the cap is exceeded.
- All 8 validators run synchronously before any DB or queue work; the
  pipeline short-circuits on first failure and returns RFC 9457.
- Audio is encrypted via ``EncryptedObjectStore`` before the row is
  inserted, so a crash between upload and DB insert leaves an
  orphaned ciphertext (not plaintext) which is reaped by a cleanup
  cron (sprint 16 lifecycle policy on the bucket).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from opentelemetry import metrics
from pydantic import BaseModel, ConfigDict, Field, field_validator

from asr_models import (
    SPEAKER_LABEL_PATTERN,
    ConfidenceSpanView,
    EnrichedSegment,
    JobEnqueuePayload,
    JobErrorKind,
    JobStatus,
    NameSuggestionView,
    SpeakerEditView,
    SpeakerStatView,
    TranscriptionJobView,
    TranscriptionOutput,
    TranscriptResultView,
    build_turns,
    default_speaker_name,
)
from audit import Severity
from auth import Claims
from db import tenant_connection
from storage import ObjectNotFoundError

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires, requires_any
from ..domain import repository
from ..domain.name_suggestions import suggest
from ..domain.speaker_edits import (
    SpeakerEdit,
    apply_edits,
    apply_to_roster,
    next_free_label,
    resolve_label,
    roster_after,
    speaker_stats,
)
from ..validators import ValidationCode, run_all
from ..validators.quota import validate_quota

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/asr", tags=["asr"])

_meter = metrics.get_meter("mdx.asr.service")
_uploads_counter = _meter.create_counter(
    "mdx_asr_uploads_total",
    description="POST /asr/jobs by status",
    unit="1",
)
_validation_rejects_counter = _meter.create_counter(
    "mdx_asr_validation_failures_total",
    description="Validation rejections by code",
    unit="1",
)
_jobs_counter = _meter.create_counter(
    "mdx_asr_jobs_total",
    description="Job lifecycle transitions by status",
    unit="1",
)
_speaker_edits_counter = _meter.create_counter(
    "mdx_asr_speaker_edits_total",
    description="Speaker edits by kind and action (apply/revert)",
    unit="1",
)
_diarized_opened_counter = _meter.create_counter(
    "mdx_asr_diarized_results_opened_total",
    description="Diarized transcripts opened for the first time (speaker-correction denominator)",
    unit="1",
)
_corrected_jobs_counter = _meter.create_counter(
    "mdx_asr_speaker_corrected_jobs_total",
    description="Jobs whose speakers a person corrected for the first time (edit or re-run)",
    unit="1",
)
_speaker_named_counter = _meter.create_counter(
    "mdx_asr_speaker_named_total",
    description="Speaker labels named, by how the name was chosen (picklist or typed)",
    unit="1",
)
_name_suggestions_counter = _meter.create_counter(
    "mdx_asr_name_suggestions_total",
    description="Name suggestions by outcome (offered, accepted, dismissed)",
    unit="1",
)
_rediarize_requests_counter = _meter.create_counter(
    "mdx_asr_rediarize_requests_total",
    description="Speaker re-labelling requests by outcome (accepted, undone, or refusal code)",
    unit="1",
)


def _reject(
    code: ValidationCode | str,
    detail: str,
    *,
    title: str,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    type_uri: str | None = None,
    **extra: object,
) -> HTTPException:
    """Build one submit-time rejection.

    Every reject on this endpoint — file shape or budget — leaves
    through here, so ``type``/``code``/``detail`` are assembled once and a
    client can switch on ``code`` alone. Counting happens here too: a
    rejection that is raised but never counted is a rejection nobody sees
    on the dashboard.

    ``problem_extras`` rather than a dict ``detail``: the shared handler
    renders ``str(exc.detail)``, so a dict arrives at the client as a
    stringified Python repr — single quotes and all — with the real
    document left at ``type: about:blank``. Extension members put ``code``
    and ``type`` where RFC 9457 says they go, and where a client can parse
    them. ``title`` is set by the handler from the status code and cannot
    be passed here, so it lands as ``reason``.
    """
    _validation_rejects_counter.add(1, {"code": str(code)})
    _uploads_counter.add(1, {"status": "rejected"})
    exc = HTTPException(status_code=status_code, detail=detail)
    exc.problem_extras = {  # type: ignore[attr-defined]
        "type_uri": type_uri or f"urn:mdx:asr:validation:{code}",
        "code": str(code),
        "reason": title,
        **extra,
    }
    return exc


@router.post(
    "/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TranscriptionJobView,
    summary="Submit a batch ASR job (multipart upload).",
)
async def submit_job(
    audio: Annotated[UploadFile, File(description="Audio file to transcribe.")],
    # ``auto`` (the clients' default) lets the recording decide: the worker
    # identifies the spoken language and transcribes in it. ``uk``/``en``
    # pin the decoder for callers that know better.
    language: Annotated[str, Form(pattern="^(auto|uk|en)$")],
    vocabulary_hint: Annotated[str | None, Form(max_length=2000)] = None,
    # Ambient Capture v1: run offline speaker diarization after
    # transcription. Rides the queue payload only — the stored result's
    # `speaker`/`speakers` fields are the durable record.
    diarize: Annotated[bool, Form()] = False,
    # Sprint 29: what a person knows about the recording. An exact count
    # ("People: 2") or a cap. Only meaningful with diarize=true.
    speakers_expected: Annotated[int | None, Form(ge=1, le=8)] = None,
    speakers_max: Annotated[int | None, Form(ge=1, le=8)] = None,
    # Sprint 30 capture context: invitee names offered as a rename picklist
    # (JSON array; content — stored on the row, never audited or logged)
    # and where the capture came from.
    name_candidates: Annotated[str | None, Form(max_length=4000)] = None,
    capture_source: Annotated[str | None, Form(pattern="^(calendar_event|manual|upload)$")] = None,
    # Sprint 31: a macOS capture with ch0 = microphone, ch1 = call audio,
    # and the account owner's name for the one local speaker (content —
    # never logged or audited).
    channel_layout: Annotated[str, Form(pattern="^(mono|mic_system)$")] = "mono",
    local_speaker_name: Annotated[str | None, Form(max_length=400)] = None,
    x_client_type: Annotated[str | None, Header(alias="X-Client-Type", max_length=32)] = None,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> TranscriptionJobView:
    state = get_state()
    candidates = _parse_name_candidates(name_candidates)
    local_name = " ".join((local_speaker_name or "").split()) or None
    if local_name is not None and len(local_name) > MAX_NAME_CHARS:
        raise _reject(
            "local_speaker_name_invalid",
            f"local_speaker_name must be at most {MAX_NAME_CHARS} characters",
            title="invalid local speaker name",
            status_code=422,
        )
    hint_sent = speakers_expected is not None or speakers_max is not None
    # Forwarded only to a job that will diarize; reported either way.
    hints_applied = diarize if hint_sent else None
    num_speakers = speakers_expected if diarize else None
    # Hint policy (Sprint 30, binding): a count a person set always wins
    # over a calendar-derived cap — the cap is dropped, never checked
    # against it (invitees regularly outnumber the people who speak).
    max_speakers = speakers_max if diarize and num_speakers is None else None
    capture_context = {
        k: v
        for k, v in (
            ("source", capture_source),
            ("client", _client_kind(x_client_type)),
            ("channel_layout", channel_layout),
        )
        if v
    }

    payload = await audio.read()
    mime_type = audio.content_type or "application/octet-stream"

    # Steps 2–7: synchronous file-shape validation.
    result, facts = await run_all(mime_type=mime_type, payload=payload)
    if not result.ok:
        raise _reject(result.code, result.detail, title="audio rejected by validation")
    if channel_layout == "mic_system" and facts.channels != 2:
        # A stereo file WITHOUT the field is an ordinary upload (downmixed as
        # always); declaring the layout is a promise about the channels.
        raise _reject(
            "channel_layout_mismatch",
            f"channel_layout=mic_system needs a 2-channel file, got {facts.channels}",
            title="channel layout does not match the file",
            status_code=422,
        )

    # Per-tenant concurrency cap, checked before the ciphertext is
    # even uploaded.
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        active = await repository.count_active_jobs(conn, tenant_id=claims.tid)
        if active >= settings.per_tenant_concurrent_jobs:
            raise _reject(
                ValidationCode.CONCURRENCY_EXCEEDED,
                (
                    f"tenant has {active} queued/running jobs; the concurrent "
                    f"limit is {settings.per_tenant_concurrent_jobs}. Wait for "
                    "one to finish and resubmit."
                ),
                title="too many active jobs for tenant",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                # Pre-dates the `code` field and clients may match on it.
                type_uri="urn:mdx:asr:rate_limit:per_tenant_concurrent",
                active=active,
                limit=settings.per_tenant_concurrent_jobs,
            )

    # Step 8: quota check, inside the same transaction as the row inserts.
    audio_id = uuid4()
    job_id = uuid4()
    storage_key = f"{claims.tid}/{audio_id}.enc"

    # Encrypt + upload BEFORE row insert. Orphan ciphertext on a crash
    # is preferable to an orphan row referencing nothing.
    header = await state.audio_store.put(
        key=storage_key,
        plaintext=payload,
        tenant_id=claims.tid,
        aad=audio_id.bytes,
    )

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        qr = await validate_quota(
            conn,
            tenant_id=claims.tid,
            incoming_size_bytes=facts.size_bytes,
            monthly_quota_bytes=settings.monthly_quota_bytes,
        )
        if not qr.ok:
            # Best-effort: delete the orphan ciphertext; cleanup cron
            # picks up any leftover.
            await state.audio_store.delete(key=storage_key)
            await _audit_quota_exceeded(state, claims, audio_id)
            raise _reject(
                qr.code,
                qr.detail,
                title="monthly tenant quota exceeded",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        await repository.insert_audio_row(
            conn,
            audio_id=audio_id,
            tenant_id=claims.tid,
            uploader_sub=claims.sub,
            mime_type=facts.mime_type,
            size_bytes=facts.size_bytes,
            duration_ms=facts.duration_ms,
            sha256=facts.sha256,
            envelope_metadata=_header_to_json(header),
            storage_uri=f"minio://{state.audio_store.bucket}/{storage_key}",
        )
        await repository.insert_job_row(
            conn,
            job_id=job_id,
            tenant_id=claims.tid,
            audio_id=audio_id,
            requester_sub=claims.sub,
            language=language,
            model="large-v3",
            name_candidates=candidates,
            capture_context=capture_context,
        )

    # Audit the upload + job creation.
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.AUDIO_UPLOADED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="audio",
        target_id=str(audio_id),
        payload={
            "size_bytes": facts.size_bytes,
            "duration_ms": facts.duration_ms,
            "sample_rate_hz": facts.sample_rate_hz,
            "codec": facts.codec,
        },
        severity=Severity.INFO,
    )

    queue_payload = JobEnqueuePayload(
        job_id=job_id,
        tenant_id=claims.tid,
        audio_id=audio_id,
        vocabulary_hint=vocabulary_hint or None,
        diarize=diarize,
        num_speakers=num_speakers,
        max_speakers=max_speakers,
        channel_layout=channel_layout,  # type: ignore[arg-type]
        local_speaker_name=local_name,
        language=language,
        model="large-v3",
        requester_sub=claims.sub,
    )
    try:
        await state.queue_producer.send(
            value=queue_payload.model_dump_json().encode("utf-8"),
            key=str(job_id).encode("utf-8"),
            headers={
                "tenant_id": str(claims.tid),
                "job_id": str(job_id),
                "schema_version": "1",
            },
        )
    except Exception as exc:  # noqa: BLE001 — every publish failure is the same failure
        # The row exists and the audio is stored, but nothing will ever
        # transcribe it. Left as-is the job sits in `queued` forever, holds
        # a slot in the tenant's concurrency budget, and shows the
        # user a spinner for work that was never handed to anyone.
        # Fail it here, where we still know why.
        logger.error(
            "asr.enqueue_failed",
            extra={
                "job_id": str(job_id),
                "error": str(exc),
                "error_class": type(exc).__name__,
            },
        )
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            await repository.fail_job(
                conn,
                job_id=job_id,
                error_kind=str(JobErrorKind.ENQUEUE_FAILED),
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        _uploads_counter.add(1, {"status": "rejected"})
        _jobs_counter.add(1, {"status": "failed"})
        http_exc = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "the job was recorded but could not be queued; it has been "
                "marked failed. Submit the recording again."
            ),
        )
        http_exc.problem_extras = {  # type: ignore[attr-defined]
            "type_uri": f"urn:mdx:asr:job:{JobErrorKind.ENQUEUE_FAILED}",
            "code": str(JobErrorKind.ENQUEUE_FAILED),
            "reason": "transcription queue unavailable",
            "job_id": str(job_id),
        }
        raise http_exc from exc

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.JOB_QUEUED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={
            "audio_id": str(audio_id),
            "language": language,
            "diarize": diarize,
            # The vocabulary, not the numbers (Sprint 29).
            "speakers_hint": _hint_kind(num_speakers, max_speakers),
            # How many names were offered — never the names (Sprint 30).
            "name_candidates": len(candidates),
            "channel_layout": channel_layout,
        },
        severity=Severity.INFO,
    )

    _uploads_counter.add(1, {"status": "accepted"})
    _jobs_counter.add(1, {"status": "queued"})

    return TranscriptionJobView(
        id=job_id,
        tenant_id=claims.tid,
        audio_id=audio_id,
        requester_sub=claims.sub,
        language=language,
        model="large-v3",
        status=JobStatus.QUEUED,
        queued_at=datetime.fromtimestamp(time.time()),
        diarize=diarize,
        hints_applied=hints_applied,
    )


# A service reading a result on a person's behalf (not the person opening
# it) names its purpose here; note-service sends `note_build`.
READ_PURPOSE_HEADER = "X-MDX-Read-Purpose"

# Name-candidate limits (Sprint 30 B-3).
MAX_NAME_CANDIDATES = 12
MAX_NAME_CHARS = 80
_CLIENT_KINDS = frozenset({"web", "ios", "macos", "android"})


def _client_kind(header: str | None) -> str | None:
    """``X-Client-Type`` → a known client word (web, ios, macos, android), else None."""
    value = (header or "").strip().lower()
    return value if value in _CLIENT_KINDS else None


def _parse_name_candidates(raw: str | None) -> list[str]:
    """Validate the picklist: a JSON array of ≤ 12 names, each 1..80 chars
    after collapsing whitespace, no control characters, de-duplicated
    case-insensitively. Anything else is a 422 — this text is rendered in
    three clients."""
    if raw is None or not raw.strip():
        return []

    def bad(detail: str) -> HTTPException:
        return _reject(
            "name_candidates_invalid", detail, title="invalid name candidates", status_code=422
        )

    try:
        value = json.loads(raw)
    except ValueError:
        raise bad("name_candidates must be a JSON array of strings") from None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise bad("name_candidates must be a JSON array of strings")
    if len(value) > MAX_NAME_CANDIDATES:
        raise bad(f"at most {MAX_NAME_CANDIDATES} name candidates")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if any(ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in item):
            raise bad("name candidates may not contain control characters")
        name = " ".join(item.split())
        if not 1 <= len(name) <= MAX_NAME_CHARS:
            raise bad(f"each name candidate must be 1..{MAX_NAME_CHARS} characters")
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _hint_kind(num_speakers: int | None, max_speakers: int | None) -> str:
    if num_speakers is not None:
        return "exact"
    if max_speakers is not None:
        return "max"
    return "none"


class AsrLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_duration_seconds: int
    max_upload_mb: int


@router.get(
    "/limits",
    response_model=AsrLimits,
    summary="What one upload may be — so a client can warn before, not fail after.",
)
async def limits(
    claims: Annotated[Claims, Depends(requires("asr.read", "asr_job"))] = ...,  # type: ignore[assignment]
) -> AsrLimits:
    return AsrLimits(
        max_duration_seconds=settings.max_duration_seconds, max_upload_mb=settings.max_upload_mb
    )


@router.get(
    "/jobs/{job_id}",
    response_model=TranscriptionJobView,
    summary="Fetch a job's status (and a pre-signed result URL on complete).",
)
async def get_job(
    job_id: UUID,
    claims: Annotated[Claims, Depends(requires("asr.read", "asr_job"))] = ...,  # type: ignore[assignment]
) -> TranscriptionJobView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        found = await repository.get_job_and_result_uri(conn, job_id=job_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    view, uri = found
    if view.status == JobStatus.COMPLETE:
        # Pre-signed URL with the configured TTL — deliberately short.
        # Follows the current revision (a re-run writes a new object).
        url = await state.transcript_store.presigned_url(
            key=_result_key(claims.tid, job_id, uri),
            expires_in=settings.s3_presigned_ttl_seconds,
        )
        view = view.model_copy(update={"result_url": url})
    return view


@router.get(
    "/jobs/{job_id}/result",
    response_model=TranscriptResultView,
    summary="Fetch a completed job's transcript (409 if not ready).",
)
async def get_job_result(
    job_id: UUID,
    request: Request,
    claims: Annotated[Claims, Depends(requires("asr.read", "asr_job"))] = ...,  # type: ignore[assignment]
) -> TranscriptResultView:
    """Architecture rule: presigned URLs serve ciphertext — useless to a
    browser — so the transcript is decrypted through the envelope path and
    returned on this AUTHENTICATED endpoint (ADR-0011 forbids client-side
    decrypt). Every plaintext read is audited.

    The raw transcript is run through nlp-service's batch pipeline
    (dictated «крапка»→"." + punctuation/number normalization) with the
    caller's own bearer forwarded; on any NLP failure the raw transcript
    is returned with ``nlp_applied=false``."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # Rev, names and artifact from ONE row read — a re-run swaps all three.
        found = await repository.get_job_and_result_uri(conn, job_id=job_id)
        view, uri = found if found is not None else (None, None)
        edits = (
            await repository.list_speaker_edits(
                conn, job_id=job_id, result_rev=view.diarization_rev
            )
            if view is not None and view.status == JobStatus.COMPLETE
            else []
        )
        candidates = (
            await repository.name_candidates(conn, job_id=job_id) if view is not None else []
        )
        name_sources = (
            await repository.name_sources(conn, job_id=job_id) if view is not None else {}
        )
        dismissed = (
            await repository.dismissed_suggestions(
                conn, job_id=job_id, result_rev=view.diarization_rev
            )
            if view is not None and settings.name_suggestions_enabled
            else []
        )
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if view.status != JobStatus.COMPLETE:
        # RFC 9457 problem detail — the result isn't ready (still queued/running)
        # or never will be (failed/cancelled). The client polls status and
        # retries; see spec §2.5 + retro E10 (FE retry-on-403-then-refetch).
        exc = HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job {job_id} is in status {view.status.value!r}, not 'complete'",
        )
        # For a terminal status the failure vocabulary travels with the
        # 409, so a client polling for a transcript learns in one response
        # that it is not coming and whether resubmitting would help —
        # rather than polling a `failed` job until it gives up.
        exc.problem_extras = {  # type: ignore[attr-defined]
            "type_uri": "urn:mdx:asr:result:not-ready",
            "reason": "Transcription result is not ready",
            "job_status": view.status.value,
            "error_kind": view.error_kind,
            "error_stage": view.error_stage,
            "error_retryable": view.error_retryable,
            "error_message": view.error_message,
        }
        raise exc
    raw = await _load_transcript(state, claims.tid, job_id, uri)
    output = TranscriptionOutput.model_validate_json(raw)
    # The "opened" fact the weekly speaker report counts from (Sprint 30);
    # set once. A service reading on the user's behalf (note-service builds
    # the note right after every capture) says so and is not an opening —
    # counting it would inflate the correction-rate denominator.
    # The audit row below stays the audit record either way.
    first_read = False
    if request.headers.get(READ_PURPOSE_HEADER, "").strip().lower() != "note_build":
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            first_read = await repository.mark_result_read(conn, job_id=job_id)
    if first_read and output.metadata.diarization is not None:
        _diarized_opened_counter.add(1)
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.TRANSCRIPT_ACCESSED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={"audio_id": str(view.audio_id), "bytes": len(raw)},
        severity=Severity.INFO,
    )
    result = await _enriched_result_view(
        state,
        job_id=job_id,
        output=output,
        authorization=request.headers.get("authorization"),
        speaker_names=view.speaker_names,
        edits=edits,
        result_rev=view.diarization_rev,
        name_candidates=candidates,
        name_sources=name_sources,
    )
    update: dict[str, object] = {
        "relabel_available": await _relabel_available(state, claims.tid, job_id, output)
    }
    if settings.name_suggestions_enabled:
        offered = [
            NameSuggestionView(
                label=s.label,
                name=s.name,
                quote=s.quote,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                segment_indices=s.segment_indices,
            )
            for s in suggest(
                result.turns,
                language=output.language,
                candidates=candidates,
                custom_names=view.speaker_names,
                dismissed=dismissed,
            )
        ]
        if offered and request.headers.get(READ_PURPOSE_HEADER, "").lower() != "note_build":
            await _count_offered(state, claims.tid, job_id, view.diarization_rev, offered)
        update["name_suggestions"] = offered
    return result.model_copy(update=update)


async def _count_offered(
    state: object, tenant_id: UUID, job_id: UUID, rev: int, offered: list[NameSuggestionView]
) -> None:
    """Count each (job, revision, label, name) once — not every page load —
    so accepted/offered is a real rate. Redis down → not counted."""
    for s in offered:
        key = f"workspace:{tenant_id}:asr:suggestion_offered:{job_id}:{rev}:{s.label}:{s.name.casefold()}"
        try:
            first = await state.redis.set(key, b"1", ex=30 * 86400, nx=True)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — a metric never breaks a read
            return
        if first:
            _name_suggestions_counter.add(1, {"outcome": "offered"})


# How long "the audio of this job still exists" is believed (Sprint 32).
AUDIO_EXISTS_TTL_S = 600


async def _relabel_available(
    state: object, tenant_id: UUID, job_id: UUID, output: TranscriptionOutput
) -> bool:
    """Offer "Re-label with the current engine" only when it can work: the
    job was diarized, by another engine than today's, and its audio is
    still stored. Anything uncertain (Redis down, storage error) → False:
    never promise a re-run we cannot do."""
    stats = output.metadata.diarization
    if stats is None and not output.speakers:
        return False  # never diarized
    if stats is not None and stats.engine == settings.current_diar_engine:
        return False
    try:
        async with tenant_connection(state.app_pool, tenant_id) as conn:  # type: ignore[attr-defined]
            audio = await repository.audio_state(conn, job_id=job_id)
        if audio is None or audio.audio_status == "deleted":
            return False
        if audio.diarization_status in ("queued", "running"):
            return False  # a re-run is already on its way (it would be 409)
        if audio.diarization_runs >= settings.rediarize_max_runs:
            return False  # the budget is spent (it would be 429)
        audio_id = audio.audio_id
        cache_key = f"workspace:{tenant_id}:asr:audio_exists:{audio_id}"
        cached = await state.redis.get(cache_key)  # type: ignore[attr-defined]
        if cached is not None:
            return bytes(cached) == b"1" if isinstance(cached, bytes | bytearray) else cached == "1"
        exists = await state.audio_store.exists(key=f"{tenant_id}/{audio_id}.enc")  # type: ignore[attr-defined]
        await state.redis.set(cache_key, b"1" if exists else b"0", ex=AUDIO_EXISTS_TTL_S)  # type: ignore[attr-defined]
        return bool(exists)
    except Exception as exc:  # noqa: BLE001 — unknown is "no"
        logger.info(
            "asr.relabel_check_unavailable",
            extra={"job_id": str(job_id), "error_class": type(exc).__name__},
        )
        return False


def _result_key(tenant_id: UUID, job_id: UUID, uri: str | None) -> str:
    """The current artifact's key: the row's ``result_storage_uri`` (a
    re-run points it at ``….r{rev}.json.enc``), else the original key."""
    return repository.key_from_uri(uri) if uri else f"{tenant_id}/{job_id}.json.enc"


async def _load_transcript(
    state: object, tenant_id: UUID, job_id: UUID, uri: str | None = None
) -> bytes:
    """Decrypt the stored transcript; 410 when retention/erasure removed it."""
    try:
        raw = await state.transcript_store.get(  # type: ignore[attr-defined]
            key=_result_key(tenant_id, job_id, uri),
            tenant_id=tenant_id,
            aad=job_id.bytes,
        )
    except ObjectNotFoundError:
        # Job says complete but the ciphertext is gone — retention TTL or
        # the S11 erasure engine removed it after the row was written.
        gone = HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                f"job {job_id} is complete but its transcript object "
                "has been deleted (retention/erasure)"
            ),
        )
        gone.problem_extras = {  # type: ignore[attr-defined]
            "type_uri": "urn:mdx:asr:result:erased",
            "reason": "Transcription result no longer exists",
            "code": "transcript_erased",
        }
        raise gone from None
    return bytes(raw)


# Languages nlp-service's batch pipeline accepts (its ``language`` Literal).
NLP_LANGUAGES = frozenset({"uk", "en", "de"})

_PUNCT_ONLY = frozenset(".,:;!?…—–-()[]{}«»“”‘’'\"/\\*#№%&@+−=_|")


async def _enriched_result_view(
    state: object,
    *,
    job_id: UUID,
    output: TranscriptionOutput,
    authorization: str | None,
    speaker_names: dict[str, str] | None = None,
    edits: list[SpeakerEdit] | None = None,
    result_rev: int = 1,
    name_candidates: list[str] | None = None,
    name_sources: dict[str, str] | None = None,
) -> TranscriptResultView:
    """Run the raw transcript through nlp-service; fall back to raw on failure.

    Whatever happens to the text, the speaker structure survives: every
    segment keeps its diarization label, the roster rides along, and the
    view is finished with the display names and the turn structure
    (``_structured``) — the clients render turns, not segments.
    """
    raw_segments = _served_segments(output)
    view = TranscriptResultView(
        job_id=job_id,
        language=output.language,
        language_detected=output.language_detected,
        language_probability=output.language_probability,
        segments=raw_segments,
        metadata=output.metadata,
        speakers=list(output.speakers),
        result_rev=result_rev,
        count_confidence=(
            output.metadata.diarization.count_confidence if output.metadata.diarization else None
        ),
        speakers_hint=(
            output.metadata.diarization.hint_num_speakers if output.metadata.diarization else None
        ),
        name_candidates=list(name_candidates or []),
        speaker_sides=dict(output.speaker_sides),
        speaker_name_sources=dict(name_sources or {}),
    )
    overlap = list(output.overlap_ms)
    if not settings.nlp_enrich_enabled or not output.segments:
        return _structured(view, speaker_names, edits, overlap)
    # The post-processor has per-language rules (dictated punctuation,
    # number words). A language it has no rules for gets the raw Whisper
    # text — which is already punctuated — rather than a 422 from
    # nlp-service that we would then swallow.
    if output.language not in NLP_LANGUAGES:
        return _structured(view, speaker_names, edits, overlap)

    payload = [
        {
            "text": s.text,
            "words": [
                {
                    "text": w.text,
                    "start_s": w.start_ms / 1000.0,
                    "end_s": w.end_ms / 1000.0,
                    "probability": w.probability,
                }
                for w in s.words
            ],
        }
        for s in output.segments
    ]
    resp = await state.nlp_client.process_segments(  # type: ignore[attr-defined]
        tenant_id=UUID(int=0),  # tenant comes from the forwarded bearer
        segments=payload,
        language=output.language,
        authorization=authorization,
    )
    if resp is None or len(resp.get("segments", [])) != len(output.segments):
        return _structured(
            view, speaker_names, edits, overlap
        )  # NLP down/mismatched — raw transcript

    enriched: list[EnrichedSegment] = []
    for index, (raw_seg, nlp_seg) in enumerate(zip(output.segments, resp["segments"], strict=True)):
        text = str(nlp_seg.get("text", "")).strip()
        spans = [
            ConfidenceSpanView(
                start_char=sp["start_char"],
                end_char=sp["end_char"],
                level=sp["level"],
            )
            for sp in nlp_seg.get("confidence_spans", [])
        ]
        # A segment that was PURELY a voice command («новий абзац» alone)
        # comes back empty — it has no textual rendering; drop it.
        if not text:
            continue
        # A segment that is ONLY punctuation (Whisper split a dictated
        # «Крапка» into its own segment) merges into the previous one.
        # No-op when the previous segment already ends with that mark —
        # the punctuation stage adds trailing periods on its own. The
        # merged segment keeps the previous speaker: a lone period has
        # no voice of its own.
        if enriched and all(ch in _PUNCT_ONLY for ch in text):
            prev = enriched[-1]
            merged = prev.text.rstrip()
            if not merged.endswith(text):
                merged += text
            # The absorbed artifact segment travels with its host, so a
            # reassign of this turn also moves the punctuation (Sprint 30).
            enriched[-1] = prev.model_copy(
                update={
                    "text": merged,
                    "end_ms": raw_seg.end_ms,
                    "artifact_indices": [*prev.artifact_indices, index],
                    "speaker_uncertain": prev.speaker_uncertain or raw_seg.speaker_uncertain,
                }
            )
            continue
        enriched.append(
            EnrichedSegment(
                text=text,
                raw_text=raw_seg.text,
                start_ms=raw_seg.start_ms,
                end_ms=raw_seg.end_ms,
                words=raw_seg.words,
                avg_confidence=raw_seg.avg_confidence,
                confidence_spans=spans,
                speaker=raw_seg.speaker,
                artifact_index=index,
                artifact_indices=[index],
                speaker_uncertain=raw_seg.speaker_uncertain,
            )
        )
    return _structured(
        view.model_copy(
            update={
                "segments": enriched,
                "nlp_applied": True,
                "nlp_pipeline_version": resp.get("pipeline_version"),
            }
        ),
        speaker_names,
        edits,
        overlap,
    )


def _served_segments(output: TranscriptionOutput) -> list[EnrichedSegment]:
    """The stored segments as served, each knowing its artifact index."""
    return [
        EnrichedSegment(
            text=s.text,
            raw_text=s.text,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            words=s.words,
            avg_confidence=s.avg_confidence,
            speaker=s.speaker,
            artifact_index=i,
            artifact_indices=[i],
            speaker_uncertain=s.speaker_uncertain,
        )
        for i, s in enumerate(output.segments)
    ]


def _structured(
    view: TranscriptResultView,
    names: dict[str, str] | None,
    edits: list[SpeakerEdit] | None = None,
    overlap_ms: list[tuple[int, int]] | None = None,
) -> TranscriptResultView:
    """Finish a result view: fold the speaker edits, roster from what is
    actually on the segments, display names for every roster label, talk
    time, and the turn structure (adjacent turns that became one speaker
    join)."""
    live = edits or []
    segments = apply_edits(view.segments, live)
    # Labels every segment was moved away from drop out; labels a reassign
    # created join (Sprint 30).
    roster = roster_after(apply_to_roster(view.speakers, live), segments)
    custom = names or {}
    speaker_names = {label: custom.get(label) or default_speaker_name(label) for label in roster}
    # Sides follow merges (a label merged into another takes the target's
    # side); a label a reassign created has none.
    sides = {label: view.speaker_sides[label] for label in roster if label in view.speaker_sides}
    sources = {
        label: source for label, source in view.speaker_name_sources.items() if label in roster
    }
    turns = build_turns(segments, speaker_names=speaker_names, overlap_ms=overlap_ms)
    return view.model_copy(
        update={
            "segments": segments,
            "speakers": roster,
            "speaker_names": speaker_names,
            "turns": turns,
            "speaker_stats": speaker_stats(segments, roster),
            "speaker_sides": sides,
            "speaker_name_sources": sources,
            "edits": [
                SpeakerEditView(
                    id=e.id,
                    kind=e.kind,
                    from_label=e.from_label,
                    to_label=e.to_label,
                    created_at=e.created_at,
                    creates_label=e.creates_label,
                )
                for e in live
            ],
        }
    )


# ── Speaker naming ────────────────────────────────────────────────────


class SpeakerNamesUpdate(BaseModel):
    """``PUT /asr/jobs/{id}/speakers`` body: the complete label → name
    mapping. A label left out (or given an empty name) goes back to its
    neutral default."""

    model_config = ConfigDict(extra="forbid")

    names: dict[str, str] = Field(default_factory=dict, max_length=64)
    # How each name was chosen (Sprint 30): feeds mdx_asr_speaker_named_total
    # only; never stored.
    sources: dict[str, Literal["picklist", "typed", "suggestion"]] = Field(
        default_factory=dict, max_length=64
    )

    @field_validator("names")
    @classmethod
    def _clean(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        cleaned: dict[str, str] = {}
        for label, name in value.items():
            if not re.match(SPEAKER_LABEL_PATTERN, label):
                raise ValueError(f"{label!r} is not a speaker label (SPEAKER_1..)")
            name = " ".join(name.split())
            if not name:
                continue
            if len(name) > 80:
                raise ValueError(f"name for {label} is longer than 80 characters")
            cleaned[label] = name
        return cleaned


class SpeakerNamesView(BaseModel):
    job_id: UUID
    speaker_names: dict[str, str]


@router.put(
    "/jobs/{job_id}/speakers",
    response_model=SpeakerNamesView,
    summary="Name the diarized speakers of a job (label → display name).",
)
async def set_speaker_names(
    job_id: UUID,
    body: SpeakerNamesUpdate,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> SpeakerNamesView:
    """Diarization labels are neutral (``SPEAKER_N``); people give them
    names. The mapping is stored on the job so every surface reading the
    transcript — web, desktop, the note built from it — shows the same
    names. Works on any job (naming does not care about status); the
    view merges the names on the next read."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        stored = await repository.set_speaker_names(conn, job_id=job_id, names=body.names)
        if stored is not None:
            # Sprint 31: provenance is persisted; removing a name the
            # platform set from the channel records "cleared" so a re-run
            # never puts it back.
            await repository.update_name_sources(
                conn, job_id=job_id, names=stored, sources=dict(body.sources)
            )
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    for label, source in body.sources.items():
        if label in stored:
            _speaker_named_counter.add(1, {"source": source})
            if source == "suggestion":
                _name_suggestions_counter.add(1, {"outcome": "accepted"})
                await state.audit_writer.write_event(
                    tenant_id=claims.tid,
                    kind=audit_kinds.NAME_SUGGESTION_ACCEPTED,
                    actor_sub=claims.sub,
                    actor_role=(claims.roles[0] if claims.roles else None),
                    target_kind="asr_job",
                    target_id=str(job_id),
                    payload={"label": label},  # never the name
                    severity=Severity.INFO,
                )
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.SPEAKERS_NAMED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        # Labels only: who a speaker IS is content, and audit payloads
        # carry pointers, not content (ADR-0031).
        payload={"labels": sorted(stored)},
        severity=Severity.INFO,
    )
    return SpeakerNamesView(job_id=job_id, speaker_names=stored)


# ── Speaker edits (Sprint 28) ─────────────────────────────────────────


class SpeakerMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_label: str = Field(alias="from", pattern=SPEAKER_LABEL_PATTERN)
    into: str = Field(pattern=SPEAKER_LABEL_PATTERN)


class SpeakerEditResult(BaseModel):
    job_id: UUID
    edit_id: UUID
    speakers: list[str]
    speaker_names: dict[str, str]
    speaker_stats: list[SpeakerStatView]
    # A reassign to a speaker the system missed: the label it allocated.
    created_label: str | None = None


def _names_after_revert(names: dict[str, str], edit: SpeakerEdit) -> dict[str, str]:
    """The naming once ``edit`` is reverted: a merge takes back the name it
    copied onto its target; a move to a new speaker takes the created
    label's name with it (the label may be allocated again later, to
    someone else)."""
    out = dict(names)
    if (
        edit.kind == "merge"
        and edit.from_label
        and edit.to_label
        and out.get(edit.from_label)
        and out.get(edit.to_label) == out.get(edit.from_label)
    ):
        del out[edit.to_label]
    if edit.kind == "reassign" and edit.creates_label and edit.to_label:
        out.pop(edit.to_label, None)
    return out


def _live_roster(output: TranscriptionOutput, edits: list[SpeakerEdit]) -> list[str]:
    """The roster a person sees now: artifact labels with live edits folded."""
    segments = apply_edits(_served_segments(output), edits)
    return roster_after(apply_to_roster(output.speakers, edits), segments)


def _edit_view(
    job_id: UUID,
    output: TranscriptionOutput,
    names: dict[str, str],
    edits: list[SpeakerEdit],
) -> TranscriptResultView:
    """The structured view after an edit (no NLP pass: only speakers moved)."""
    return _structured(
        TranscriptResultView(
            job_id=job_id,
            language=output.language,
            segments=_served_segments(output),
            metadata=output.metadata,
            speakers=list(output.speakers),
        ),
        names,
        edits,
        list(output.overlap_ms),
    )


def _problem(status_code: int, code: str, detail: str) -> HTTPException:
    exc = HTTPException(status_code=status_code, detail=detail)
    exc.problem_extras = {  # type: ignore[attr-defined]
        "type_uri": f"urn:mdx:asr:speakers:{code}",
        "code": code,
    }
    return exc


@router.post(
    "/jobs/{job_id}/speakers/merge",
    response_model=SpeakerEditResult,
    summary="Merge one diarized speaker into another (reversible overlay).",
)
async def merge_speakers(
    job_id: UUID,
    body: SpeakerMergeRequest,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> SpeakerEditResult:
    """Every segment of ``from`` reads as ``into`` from now on — in the
    roster, the names, the turns and the talk time. The stored transcript
    is not touched; the edit is undone with ``DELETE …/speakers/edits/{id}``.
    If ``from`` has a name and ``into`` has none, ``into`` takes the name."""
    if body.from_label == body.into:
        raise _problem(422, "same_label", "cannot merge a speaker into itself")
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        found = await repository.get_job_and_result_uri(conn, job_id=job_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    job, uri = found
    if job.status != JobStatus.COMPLETE:
        raise _problem(409, "job_not_complete", f"job {job_id} is {job.status.value!r}")
    if job.diarization_status in ("queued", "running"):
        raise _problem(
            409, "rediarize_in_progress", "speakers are being re-labelled; merge after it finishes"
        )
    output = TranscriptionOutput.model_validate_json(
        await _load_transcript(state, claims.tid, job_id, uri)
    )

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repository.lock_job_for_edit(conn, job_id=job_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        rev = int(row["diarization_rev"])
        # Re-checked under the lock: a re-run (or undo) that swapped the
        # labelling after the transcript above was read would otherwise get
        # an edit validated against the old roster but stored on the new one.
        if (
            row.get("diarization_status") in ("queued", "running")
            or rev != job.diarization_rev
            or row.get("result_storage_uri") != uri
        ):
            raise _problem(
                409, "rediarize_in_progress", "speakers were just re-labelled; reload and try again"
            )
        edits = await repository.list_speaker_edits(conn, job_id=job_id, result_rev=rev)
        names = repository.parse_speaker_names(row["speaker_names"])
        existing = next(
            (
                e
                for e in edits
                if e.kind == "merge"
                and e.from_label == body.from_label
                and resolve_label(e.to_label or "", edits) == resolve_label(body.into, edits)
            ),
            None,
        )
        created = existing is None
        first_correction = created and not await repository.has_corrections(conn, job_id=job_id)
        if existing is None:
            roster = _live_roster(output, edits)
            for label in (body.from_label, body.into):
                if label not in roster:
                    raise _problem(422, "unknown_label", f"{label} is not in the current roster")
            edit = await repository.insert_speaker_edit(
                conn,
                tenant_id=claims.tid,
                job_id=job_id,
                result_rev=rev,
                kind="merge",
                from_label=body.from_label,
                to_label=body.into,
                actor_sub=claims.sub,
            )
            edits = [*edits, edit]
            if names.get(body.from_label) and not names.get(body.into):
                # Copied, not moved: an undo then restores both sides.
                names[body.into] = names[body.from_label]
                names = await repository.set_speaker_names(conn, job_id=job_id, names=names) or {}
        else:
            edit = existing

    if created:
        await state.audit_writer.write_event(
            tenant_id=claims.tid,
            kind=audit_kinds.SPEAKERS_MERGED,
            actor_sub=claims.sub,
            actor_role=(claims.roles[0] if claims.roles else None),
            target_kind="asr_job",
            target_id=str(job_id),
            payload={"from_label": body.from_label, "into_label": body.into},
            severity=Severity.INFO,
        )
        _speaker_edits_counter.add(1, {"kind": "merge", "action": "apply"})
        if first_correction:
            _corrected_jobs_counter.add(1)
    view = _edit_view(job_id, output, names, edits)
    return SpeakerEditResult(
        job_id=job_id,
        edit_id=edit.id,
        speakers=view.speakers,
        speaker_names=view.speaker_names,
        speaker_stats=view.speaker_stats,
    )


# ── Turn-level correction (Sprint 30) ─────────────────────────────────

# One reassign moves at most this many artifact segments; the table's CHECK
# holds the same bound. A live roster never exceeds the engines' cap.
MAX_REASSIGN_SEGMENTS = 500
MAX_LIVE_SPEAKERS = 8


class SpeakerReassignRequest(BaseModel):
    """Move turns: ``to`` is a roster label, ``"new"`` (a speaker the system
    missed) or ``null`` (unattributed). ``segment_indices`` are the turn's
    ``segment_indices`` from the result view — artifact index space, valid
    only for ``result_rev``."""

    model_config = ConfigDict(extra="forbid")

    result_rev: int = Field(ge=1)
    segment_indices: list[int] = Field(min_length=1)
    to: str | None

    @field_validator("to")
    @classmethod
    def _target(cls, value: str | None) -> str | None:
        import re

        if value is None or value == "new" or re.match(SPEAKER_LABEL_PATTERN, value):
            return value
        raise ValueError('to must be a speaker label, "new" or null')


async def _locked_edit_context(
    state: object, claims: Claims, job_id: UUID
) -> tuple[TranscriptionOutput, str | None, int]:
    """Load the current artifact for an edit; 404 / 409 like the merge route."""
    async with tenant_connection(state.app_pool, claims.tid) as conn:  # type: ignore[attr-defined]
        found = await repository.get_job_and_result_uri(conn, job_id=job_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    job, uri = found
    if job.status != JobStatus.COMPLETE:
        raise _problem(409, "job_not_complete", f"job {job_id} is {job.status.value!r}")
    if job.diarization_status in ("queued", "running"):
        raise _problem(
            409, "rediarize_in_progress", "speakers are being re-labelled; edit after it finishes"
        )
    output = TranscriptionOutput.model_validate_json(
        await _load_transcript(state, claims.tid, job_id, uri)
    )
    return output, uri, job.diarization_rev


@router.post(
    "/jobs/{job_id}/speakers/reassign",
    response_model=SpeakerEditResult,
    summary="Move turns to another speaker, a new speaker, or unattributed.",
)
async def reassign_turns(
    job_id: UUID,
    body: SpeakerReassignRequest,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> SpeakerEditResult:
    """One wrong reply fixed in two clicks. An overlay edit like a merge:
    the stored transcript never changes, the latest edit can be undone,
    and the edit applies only to the revision it was made on."""
    if len(body.segment_indices) > MAX_REASSIGN_SEGMENTS:
        raise _problem(
            422, "too_many_segments", f"at most {MAX_REASSIGN_SEGMENTS} segments per move"
        )
    state = get_state()
    output, uri, rev_seen = await _locked_edit_context(state, claims, job_id)
    indices = sorted(set(body.segment_indices))
    if indices[0] < 0 or indices[-1] >= len(output.segments):
        raise _problem(422, "bad_segment_index", "segment index outside this transcript")

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repository.lock_job_for_edit(conn, job_id=job_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        rev = int(row["diarization_rev"])
        if row.get("diarization_status") in ("queued", "running"):
            raise _problem(409, "rediarize_in_progress", "speakers are being re-labelled")
        if body.result_rev != rev or rev != rev_seen or row.get("result_storage_uri") != uri:
            # Indices mean something only within one revision.
            exc = _problem(
                409, "stale_result_rev", "the speakers changed since this view was loaded"
            )
            exc.problem_extras["current_rev"] = rev  # type: ignore[attr-defined]
            raise exc
        edits = await repository.list_speaker_edits(conn, job_id=job_id, result_rev=rev)
        names = repository.parse_speaker_names(row["speaker_names"])
        roster = _live_roster(output, edits)

        latest = edits[-1] if edits else None
        if (
            latest is not None
            and latest.kind == "reassign"
            and sorted(latest.segment_indices) == indices
            and (
                (body.to == "new" and latest.creates_label)
                or (
                    body.to != "new"
                    and not latest.creates_label
                    and latest.to_label == (resolve_label(body.to, edits) if body.to else None)
                )
            )
        ):
            # The same move again (a double click, a retry): same answer.
            view = _edit_view(job_id, output, names, edits)
            return SpeakerEditResult(
                job_id=job_id,
                edit_id=latest.id,
                speakers=view.speakers,
                speaker_names=view.speaker_names,
                speaker_stats=view.speaker_stats,
                created_label=latest.to_label if latest.creates_label else None,
            )

        creates = body.to == "new"
        if creates:
            # Every label the job has EVER used — reverted edits and older
            # revisions included — so a new speaker never inherits a name
            # someone gave an earlier, undone one.
            known = [*output.speakers, *(s.speaker for s in output.segments)]
            known += await repository.all_edit_labels(conn, job_id=job_id)
            target: str | None = next_free_label(known)
        elif body.to is None:
            target = None
        else:
            target = resolve_label(body.to, edits)
            if target not in roster:
                raise _problem(422, "unknown_label", f"{body.to} is not in the current roster")

        first_correction = not await repository.has_corrections(conn, job_id=job_id)
        pending = SpeakerEdit(
            id=uuid4(),
            kind="reassign",
            from_label=None,
            to_label=target,
            segment_indices=indices,
            result_rev=rev,
            seq=(edits[-1].seq + 1) if edits else 1,
            created_at=datetime.now(),
            creates_label=creates,
        )
        if len(_live_roster(output, [*edits, pending])) > MAX_LIVE_SPEAKERS:
            raise _problem(
                422, "too_many_speakers", f"a transcript has at most {MAX_LIVE_SPEAKERS} speakers"
            )
        edit = await repository.insert_speaker_edit(
            conn,
            tenant_id=claims.tid,
            job_id=job_id,
            result_rev=rev,
            kind="reassign",
            from_label=None,
            to_label=target,
            actor_sub=claims.sub,
            segment_indices=indices,
            creates_label=creates,
        )
        edits = [*edits, edit]

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.TURN_REASSIGNED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        # Counts and the kind of target — never text, never names.
        payload={
            "segments": len(indices),
            "to": "new" if creates else ("none" if target is None else "existing"),
        },
        severity=Severity.INFO,
    )
    _speaker_edits_counter.add(1, {"kind": "reassign", "action": "apply"})
    if first_correction:
        _corrected_jobs_counter.add(1)
    view = _edit_view(job_id, output, names, edits)
    return SpeakerEditResult(
        job_id=job_id,
        edit_id=edit.id,
        speakers=view.speakers,
        speaker_names=view.speaker_names,
        speaker_stats=view.speaker_stats,
        created_label=target if creates else None,
    )


@router.post(
    "/jobs/{job_id}/speakers/edits/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revert every speaker edit of the current revision.",
)
async def reset_speaker_edits(
    job_id: UUID,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> Response:
    """Back to what the diarizer produced for this revision. Idempotent;
    the stored transcript was never changed, so nothing else moves."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repository.lock_job_for_edit(conn, job_id=job_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        rev = int(row["diarization_rev"])
        live = await repository.list_speaker_edits(conn, job_id=job_id, result_rev=rev)
        reverted = await repository.revert_live_edits(conn, job_id=job_id, result_rev=rev)
        names = repository.parse_speaker_names(row["speaker_names"])
        restored = names
        for edit in reversed(live):  # newest first, as repeated undos would
            restored = _names_after_revert(restored, edit)
        if restored != names:
            await repository.set_speaker_names(conn, job_id=job_id, names=restored)
    if reverted:
        await state.audit_writer.write_event(
            tenant_id=claims.tid,
            kind=audit_kinds.SPEAKER_EDITS_RESET,
            actor_sub=claims.sub,
            actor_role=(claims.roles[0] if claims.roles else None),
            target_kind="asr_job",
            target_id=str(job_id),
            payload={"count": reverted},
            severity=Severity.INFO,
        )
        _speaker_edits_counter.add(reverted, {"kind": "all", "action": "reset"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/jobs/{job_id}/speakers/edits/{edit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Undo the latest speaker edit of a job.",
)
async def undo_speaker_edit(
    job_id: UUID,
    edit_id: UUID,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> Response:
    """Only the latest live edit can be undone — keeps the fold deterministic."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repository.lock_job_for_edit(conn, job_id=job_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        found = await repository.get_speaker_edit(conn, job_id=job_id, edit_id=edit_id)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        edit, reverted = found
        live = await repository.list_speaker_edits(
            conn, job_id=job_id, result_rev=int(row["diarization_rev"])
        )
        if reverted or not live or live[-1].id != edit_id:
            raise _problem(409, "edit_not_latest", "only the latest speaker edit can be undone")
        await repository.revert_speaker_edit(conn, edit_id=edit_id)
        names = repository.parse_speaker_names(row["speaker_names"])
        restored = _names_after_revert(names, edit)
        if restored != names:
            await repository.set_speaker_names(conn, job_id=job_id, names=restored)
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.SPEAKER_EDIT_REVERTED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={"kind": edit.kind},
        severity=Severity.INFO,
    )
    _speaker_edits_counter.add(1, {"kind": edit.kind, "action": "revert"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Name suggestions (Sprint 32) ─────────────────────────────────────


class DismissSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(pattern=SPEAKER_LABEL_PATTERN)
    name: str = Field(min_length=1, max_length=80)


@router.post(
    "/jobs/{job_id}/speakers/suggestions/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Never offer this name for this speaker again (this job).",
)
async def dismiss_name_suggestion(
    job_id: UUID,
    body: DismissSuggestionRequest,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> Response:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        added = await repository.dismiss_suggestion(
            conn, job_id=job_id, label=body.label, name=body.name
        )
    if added is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if added:
        _name_suggestions_counter.add(1, {"outcome": "dismissed"})
        await state.audit_writer.write_event(
            tenant_id=claims.tid,
            kind=audit_kinds.NAME_SUGGESTION_DISMISSED,
            actor_sub=claims.sub,
            actor_role=(claims.roles[0] if claims.roles else None),
            target_kind="asr_job",
            target_id=str(job_id),
            payload={"label": body.label},  # never the name
            severity=Severity.INFO,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Speaker re-labelling (Sprint 29) ──────────────────────────────────


class RediarizeRequest(BaseModel):
    """``speakers_expected``: the count a person states; ``null`` lets the
    engine decide again (e.g. after an engine upgrade)."""

    model_config = ConfigDict(extra="forbid")

    speakers_expected: int | None = Field(default=None, ge=1, le=8)


class RediarizeStatusView(BaseModel):
    job_id: UUID
    diarization_status: str
    diarization_rev: int


@router.post(
    "/jobs/{job_id}/rediarize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RediarizeStatusView,
    summary="Re-label a complete job's speakers from its stored audio (no re-transcription).",
)
async def rediarize(
    job_id: UUID,
    body: RediarizeRequest,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> RediarizeStatusView:
    """ "There were 2 people": new speaker labels in minutes, words untouched.

    The job's ``status`` stays ``complete`` — the transcript is readable
    the whole time; progress rides ``diarization_status``. Sprint 28 merges
    belong to the replaced labelling and stop applying. Capped: one run in
    flight and ``rediarize_max_runs`` per job, plus a per-user hourly
    limit. Re-runs do not count against the tenant's concurrent-job cap.
    """
    state = get_state()
    decision = await state.limiter.allow(
        "rediarize_user",
        str(claims.sub),
        limit=settings.rediarize_user_hourly_limit,
        window_seconds=3600,
        # The per-job run cap in the database bounds the damage if Redis
        # is down; refusing every re-run for that is the worse outcome.
        fail_open=True,
    )
    if not decision.allowed:
        _rediarize_requests_counter.add(1, {"outcome": "rate_limited"})
        exc = _problem(429, "rate_limited", "too many re-labelling requests; try again later")
        exc.headers = {"Retry-After": str(decision.retry_after)}
        raise exc

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        first_correction = not await repository.has_corrections(conn, job_id=job_id)
        claim = await repository.claim_rediarize(
            conn, job_id=job_id, max_runs=settings.rediarize_max_runs
        )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if claim.refused is not None:
        _rediarize_requests_counter.add(1, {"outcome": claim.refused})
        code = 429 if claim.refused == "rediarize_limit" else 409
        raise _problem(code, claim.refused, _REDIARIZE_REFUSALS[claim.refused])

    queue_payload = JobEnqueuePayload(
        job_id=job_id,
        tenant_id=claims.tid,
        audio_id=claim.audio_id,  # type: ignore[arg-type]
        # Not used by a re-run (no ASR pass); the field is required.
        language="auto",
        diarize=True,
        num_speakers=body.speakers_expected,
        task="rediarize",
        target_rev=claim.target_rev,
        rediarize_id=claim.request_id,
        requester_sub=claims.sub,
    )
    try:
        await state.queue_producer.send(
            value=queue_payload.model_dump_json().encode("utf-8"),
            key=str(job_id).encode("utf-8"),
            headers={
                "tenant_id": str(claims.tid),
                "job_id": str(job_id),
                "schema_version": "1",
            },
        )
    except Exception as exc:  # noqa: BLE001 — every publish failure is the same failure
        # Nothing will pick the run up: put the row back as it was and do
        # not count the run, so "try again" is honest advice.
        logger.error(
            "asr.rediarize_enqueue_failed",
            extra={"job_id": str(job_id), "error_class": type(exc).__name__},
        )
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            await repository.release_rediarize_claim(conn, job_id=job_id, claim=claim)
        _rediarize_requests_counter.add(1, {"outcome": "enqueue_failed"})
        raise _problem(
            503, "enqueue_failed", "speaker re-labelling could not be queued; try again"
        ) from exc

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.REDIARIZE_REQUESTED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={
            "hint": "exact" if body.speakers_expected is not None else "none",
            # Sprint 32: a re-run without a count is "re-label with the
            # current engine"; with one, a person correcting the count.
            "reason": "user_count" if body.speakers_expected is not None else "engine_upgrade",
        },
        severity=Severity.INFO,
    )
    _rediarize_requests_counter.add(1, {"outcome": "accepted"})
    if first_correction:
        _corrected_jobs_counter.add(1)
    return RediarizeStatusView(
        job_id=job_id, diarization_status="queued", diarization_rev=claim.current_rev
    )


_REDIARIZE_REFUSALS = {
    "job_not_complete": "speakers can be re-labelled once the transcript is complete",
    "rediarize_in_progress": "speakers are already being re-labelled",
    "audio_unavailable": "the recording is no longer stored, so speakers cannot be re-labelled",
    "rediarize_limit": "this transcript has been re-labelled the maximum number of times",
    "nothing_to_undo": "there is no earlier labelling to go back to",
}


@router.post(
    "/jobs/{job_id}/rediarize/undo",
    response_model=RediarizeStatusView,
    summary="Go back to the speaker labels the last re-run replaced (one step).",
)
async def undo_rediarize(
    job_id: UUID,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> RediarizeStatusView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        outcome = await repository.undo_rediarize(conn, job_id=job_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if outcome.refused is not None:
        _rediarize_requests_counter.add(1, {"outcome": outcome.refused})
        raise _problem(409, outcome.refused, _REDIARIZE_REFUSALS[outcome.refused])
    if outcome.undone_uri:
        # One step only: the undone labelling is not kept for a redo.
        # Best effort — an orphan costs storage, not correctness.
        try:
            await state.transcript_store.delete(key=repository.key_from_uri(outcome.undone_uri))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "asr.rediarize_undo_delete_failed",
                extra={"job_id": str(job_id), "error_class": type(exc).__name__},
            )
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.REDIARIZE_UNDONE,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={},
        severity=Severity.INFO,
    )
    _rediarize_requests_counter.add(1, {"outcome": "undone"})
    return RediarizeStatusView(
        job_id=job_id, diarization_status="complete", diarization_rev=outcome.rev
    )


@router.get(
    "/jobs",
    response_model=list[TranscriptionJobView],
    summary="List tenant's recent jobs.",
)
async def list_jobs(
    claims: Annotated[
        Claims,
        Depends(requires_any(("asr.read", "asr_job"), ("stats.read", "tenant"))),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    since: Annotated[datetime | None, Query()] = None,
) -> list[TranscriptionJobView]:
    """One view for every caller. Reachable by a member with `asr.read`
    and by a tenant_admin with only `stats.read` (job counts and
    throughput for the business dashboard). The row carries no
    transcript content; the transcript itself stays behind `asr.read`
    on the result endpoint.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        return await repository.list_jobs(conn, limit=limit, status=status_filter, since=since)


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel a queued or running job.",
)
async def cancel_job(
    job_id: UUID,
    claims: Annotated[Claims, Depends(requires("asr.cancel", "asr_job"))] = ...,  # type: ignore[assignment]
) -> dict[str, str]:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        outcome = await repository.request_cancel(conn, job_id=job_id)
    if outcome is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="job is already complete/failed/cancelled, or does not exist",
        )
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.JOB_CANCELLED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={"outcome": outcome},
        severity=Severity.INFO,
    )
    _jobs_counter.add(1, {"status": outcome})
    return {"status": outcome}


async def _audit_quota_exceeded(state: object, claims: Claims, audio_id: UUID) -> None:
    # ``state`` typed as object so the import-linter doesn't see this fn
    # as creating a cycle with main_deps.
    try:
        await state.audit_writer.write_event(  # type: ignore[attr-defined]
            tenant_id=claims.tid,
            kind=audit_kinds.QUOTA_EXCEEDED,
            actor_sub=claims.sub,
            target_kind="audio",
            target_id=str(audio_id),
            payload={"reason": "monthly_quota"},
            severity=Severity.WARN,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit.quota_exceeded.write_failed",
            extra={"error": str(exc), "error_class": type(exc).__name__},
        )


def _header_to_json(header: object) -> dict[str, str | int]:
    from storage.object_store import header_metadata_for_row

    return header_metadata_for_row(header)  # type: ignore[arg-type]
