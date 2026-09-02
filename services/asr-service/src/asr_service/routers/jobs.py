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

import logging
import time
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
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
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,  # type: ignore[assignment]
) -> TranscriptionJobView:
    state = get_state()

    payload = await audio.read()
    mime_type = audio.content_type or "application/octet-stream"

    # Steps 2–7: synchronous file-shape validation.
    result, facts = await run_all(mime_type=mime_type, payload=payload)
    if not result.ok:
        raise _reject(result.code, result.detail, title="audio rejected by validation")

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
        view = await repository.get_job(conn, job_id=job_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if view.status == JobStatus.COMPLETE:
        # Pre-signed URL with the configured TTL — deliberately short.
        url = await state.transcript_store.presigned_url(
            key=f"{claims.tid}/{job_id}.json.enc",
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
        view = await repository.get_job(conn, job_id=job_id)
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
    try:
        raw = await state.transcript_store.get(
            key=f"{claims.tid}/{job_id}.json.enc",
            tenant_id=claims.tid,
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
    output = TranscriptionOutput.model_validate_json(raw)
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
    return await _enriched_result_view(
        state,
        job_id=job_id,
        output=output,
        authorization=request.headers.get("authorization"),
        speaker_names=view.speaker_names,
    )


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
) -> TranscriptResultView:
    """Run the raw transcript through nlp-service; fall back to raw on failure.

    Whatever happens to the text, the speaker structure survives: every
    segment keeps its diarization label, the roster rides along, and the
    view is finished with the display names and the turn structure
    (``_structured``) — the clients render turns, not segments.
    """
    raw_segments = [
        EnrichedSegment(
            text=s.text,
            raw_text=s.text,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            words=s.words,
            avg_confidence=s.avg_confidence,
            speaker=s.speaker,
        )
        for s in output.segments
    ]
    view = TranscriptResultView(
        job_id=job_id,
        language=output.language,
        language_detected=output.language_detected,
        language_probability=output.language_probability,
        segments=raw_segments,
        metadata=output.metadata,
        speakers=list(output.speakers),
    )
    if not settings.nlp_enrich_enabled or not output.segments:
        return _structured(view, speaker_names)
    # The post-processor has per-language rules (dictated punctuation,
    # number words). A language it has no rules for gets the raw Whisper
    # text — which is already punctuated — rather than a 422 from
    # nlp-service that we would then swallow.
    if output.language not in NLP_LANGUAGES:
        return _structured(view, speaker_names)

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
        return _structured(view, speaker_names)  # NLP down/mismatched — raw transcript

    enriched: list[EnrichedSegment] = []
    for raw_seg, nlp_seg in zip(output.segments, resp["segments"], strict=True):
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
            enriched[-1] = prev.model_copy(update={"text": merged, "end_ms": raw_seg.end_ms})
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
    )


def _structured(view: TranscriptResultView, names: dict[str, str] | None) -> TranscriptResultView:
    """Finish a result view: roster from what is actually on the segments,
    display names for every roster label, and the turn structure."""
    roster = list(view.speakers)
    for seg in view.segments:
        if seg.speaker and seg.speaker not in roster:
            roster.append(seg.speaker)
    custom = names or {}
    speaker_names = {label: custom.get(label) or default_speaker_name(label) for label in roster}
    turns = build_turns(view.segments, speaker_names=speaker_names)
    return view.model_copy(
        update={"speakers": roster, "speaker_names": speaker_names, "turns": turns}
    )


# ── Speaker naming ────────────────────────────────────────────────────


class SpeakerNamesUpdate(BaseModel):
    """``PUT /asr/jobs/{id}/speakers`` body: the complete label → name
    mapping. A label left out (or given an empty name) goes back to its
    neutral default."""

    model_config = ConfigDict(extra="forbid")

    names: dict[str, str] = Field(default_factory=dict, max_length=64)

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
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
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
