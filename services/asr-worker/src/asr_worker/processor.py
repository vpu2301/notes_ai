"""Main job processor — Whisper inference loop.

Lifecycle of a job:

1. Pull message from Redis Streams via ``RedisStreamsConsumer``.
2. Parse :class:`JobEnqueuePayload` from the message value.
3. Idempotency check: SELECT status from transcription_jobs.
4. Mark running, audit ``asr.transcription_started``.
5. Fetch encrypted audio bytes from S3 via ``EncryptedObjectStore``.
6. Decode via ffmpeg into mono 16 kHz float32 PCM.
7. Run ``WhisperEngine.transcribe`` (the payload's optional free-text
   vocabulary hint feeds Whisper's initial_prompt).
8. Serialize :class:`TranscriptionOutput` JSON; encrypt + upload.
9. Mark complete, audit ``asr.transcription_complete``.
10. ACK the Redis message.

Failure modes are the closed vocabulary in :mod:`asr_models.errors`, and
the vocabulary decides the retry: a kind whose spec says ``retryable`` goes
back to ``consumer.fail()`` for redelivery, everything else is recorded on
the row and acked. Re-delivering a corrupt file three more times only
delays the failure the user is already waiting on.

  - ``AudioDecodeError``      → ``corrupt_audio``        (terminal)
  - decoded PCM has no speech → ``no_speech``            (terminal)
  - audio object gone         → ``audio_missing``        (terminal)
  - envelope/AAD failure      → ``decrypt_failed``       (terminal)
  - object store unreachable  → ``storage_unavailable``  (retried)
  - model not loaded          → ``model_unavailable``    (retried)
  - CUDA OOM                  → ``gpu_oom``              (terminal; frees cache)
  - inference over budget     → ``timeout``              (terminal)
  - transcript upload failed  → ``result_store_failed``  (retried)
  - anything else             → ``unhandled``            (retried → DLQ)

Whatever the kind, the row reaches a terminal status before the message is
acked. A failure the worker knows about and the ``transcription_jobs`` row
does not is the one outcome this module must never produce: the job would
sit in ``running`` forever, holding a slot in the tenant's concurrency
budget and showing a spinner nobody will ever resolve. The retry-exhausted
path (DLQ) and the reaper in asr-service exist for the two cases where the
worker cannot write that row itself.

Cancellation is checked at four points, because ``DELETE /asr/jobs/{id}``
on a RUNNING job can only ask: it sets ``cancel_requested`` and leaves the
status alone, so nothing stops unless the worker looks. It looks before
claiming the job, after decoding the audio, between inference chunks, and
once more before the transcript is stored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import numpy as np
from opentelemetry import metrics

from asr_models import (
    DiarizationStats,
    JobEnqueuePayload,
    JobErrorKind,
    Segment,
    TranscriptionOutput,
    spec_for,
)
from audit import Severity
from crypto import CryptoError
from db import tenant_connection
from diarization import (
    UNKNOWN,
    DiarizationHints,
    DiarizationUnavailableError,
    Diarizer,
    OfflineDiarization,
    SileroSegmenter,
    diarize_dual,
)
from messaging import Message, RedisStreamsConsumer
from models import ProviderError, TranscriptionCancelledError
from storage import ObjectNotFoundError

from . import audit_kinds
from .audio_io import AudioDecodeError, decode_to_pcm, mixdown
from .config import settings
from .main_deps import WorkerState
from .notifications import emit_transcription_completed, emit_transcription_failed

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.asr.worker")
_inference_seconds = _meter.create_histogram(
    "mdx_asr_inference_seconds",
    description="Inference wall-clock per job",
    unit="s",
)
_audio_duration_seconds = _meter.create_histogram(
    "mdx_asr_audio_duration_seconds",
    description="Audio duration per job",
    unit="s",
)
_realtime_factor = _meter.create_histogram(
    "mdx_asr_realtime_factor",
    description="audio_duration / infer_seconds (>1 = faster than realtime)",
    unit="1",
)
_gpu_memory_peak = _meter.create_histogram(
    "mdx_asr_gpu_memory_peak_mb",
    description="Peak GPU memory per job",
    unit="MB",
)
_oom_counter = _meter.create_counter(
    "mdx_asr_oom_total",
    description="Times the worker hit CUDA OOM",
    unit="1",
)
_diarized_jobs = _meter.create_counter(
    "mdx_asr_diarized_jobs_total",
    description="Batch jobs that ran offline speaker diarization",
    unit="1",
)
_diarization_speakers = _meter.create_histogram(
    "mdx_asr_diarization_speakers",
    description="Speakers that reached the transcript per diarized job",
    unit="1",
    explicit_bucket_boundaries_advisory=[1, 2, 3, 4, 5, 6, 7, 8],
)
_diarization_seconds = _meter.create_histogram(
    "mdx_asr_diarization_seconds",
    description="Wall time of the diarization step per job",
    unit="s",
)
_diarization_unknown_share = _meter.create_histogram(
    "mdx_asr_diarization_unknown_share",
    description="Share of diarized speech left without a speaker label",
    unit="1",
    explicit_bucket_boundaries_advisory=[0.01, 0.02, 0.05, 0.08, 0.1, 0.2, 0.3, 0.5, 1.0],
)
_diarization_clusters_dropped = _meter.create_counter(
    "mdx_asr_diarization_clusters_dropped_total",
    description="Clusters dissolved by the speaker floor or the roster cap",
    unit="1",
)
# Acceptance metric for the diarizer (Sprint 29): p95 must stay ≤ 0.25.
# Per job, so the quantile is of the ratio itself, not a ratio of quantiles.
_diarization_audio_ratio = _meter.create_histogram(
    "mdx_asr_diarization_audio_ratio",
    description="Diarization wall time divided by audio duration, per diarized job or re-run",
    unit="1",
    explicit_bucket_boundaries_advisory=[0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.5, 1.0],
)
_shadow_delta = _meter.create_histogram(
    "mdx_asr_diarization_shadow_delta",
    description="Shadow engine speakers minus primary engine speakers per job",
    unit="1",
    explicit_bucket_boundaries_advisory=[-4, -3, -2, -1, 0, 1, 2, 3, 4],
)
_diarizer_unavailable = _meter.create_counter(
    "mdx_asr_diarization_unavailable_total",
    description="Diarized jobs or re-runs that could not load the diarization engine",
    unit="1",
)
_dual_jobs = _meter.create_counter(
    "mdx_asr_diarization_dual_jobs_total",
    description="Dual-channel captures diarized, by outcome (dual | mono_fallback)",
    unit="1",
)
_rediarize_total = _meter.create_counter(
    "mdx_asr_rediarize_total",
    description="Speaker re-labelling runs by outcome",
    unit="1",
)
_rediarize_seconds = _meter.create_histogram(
    "mdx_asr_rediarize_seconds",
    description="Wall time of a speaker re-labelling run",
    unit="s",
)
_warmup_gauge = _meter.create_gauge(
    "mdx_asr_warmup_seconds",
    description="Worker warmup duration on startup",
    unit="s",
)
_model_loaded_gauge = _meter.create_gauge(
    "mdx_asr_model_loaded",
    description="1 if Whisper model is loaded",
    unit="1",
)


async def run_forever(state: WorkerState) -> None:
    """Top-level loop. Consumes the queue until SIGTERM."""
    _warmup_gauge.set(state.engine.warmup_seconds)
    _model_loaded_gauge.set(1 if state.engine.is_loaded else 0)

    async with state.consumer as consumer:
        async for msg in consumer:
            try:
                await _process_one(state, msg)
                await consumer.ack(msg)
            except _NonRetryableError as exc:
                # Already recorded a failure on the job row; ack so the
                # message doesn't keep getting redelivered.
                logger.info(
                    "processor.non_retryable",
                    extra={"reason": exc.kind, "detail": str(exc)},
                )
                await consumer.ack(msg)
            except _RetryableError as exc:
                # Transient by classification — hand it back for redelivery.
                # The job row is left in `running` on purpose: it IS still
                # running, on the next attempt. Only exhaustion is terminal.
                logger.warning(
                    "processor.retryable",
                    extra={"reason": exc.kind, "detail": str(exc)},
                )
                await _fail_or_retry(state, consumer, msg, exc)
            except Exception as exc:  # noqa: BLE001
                logger.exception("processor.unhandled", exc_info=exc)
                await _fail_or_retry(
                    state,
                    consumer,
                    msg,
                    _RetryableError(str(JobErrorKind.UNHANDLED), str(exc)),
                )


async def _fail_or_retry(
    state: WorkerState,
    consumer: RedisStreamsConsumer,
    msg: Message,
    exc: _JobError,
) -> None:
    """Hand a retryable failure back to the queue; land it if that was the last try.

    ``consumer.fail`` reports whether this attempt exhausted the retry
    budget and moved the message to the DLQ. That was previously the end of
    the story from the queue's side and the beginning of a silence on the
    database's: the message left the stream, and the job row stayed in
    ``running`` with no worker, no retry, and no explanation — indefinitely.
    A DLQ'd message is a dead job, and the row has to say so.
    """
    dead_lettered = await consumer.fail(msg, error_kind=exc.kind)
    if not dead_lettered:
        return
    ids = _identify(msg)
    if ids is None:
        # Unparseable payload — there is no row to fail. The DLQ entry is
        # the whole record, which is why bad_payload is never retried.
        return
    tenant_id, job_id, requester_sub = ids
    request_id = _rediarize_request(msg)
    if request_id is not None:
        # A re-labelling run that ran out of retries fails the RE-RUN, not
        # the job: the transcript and its previous labels are untouched.
        with contextlib.suppress(Exception):
            await _mark_rediarize_failed(
                state,
                tenant_id,
                job_id,
                request_id=request_id,
                kind=str(JobErrorKind.RETRY_EXHAUSTED),
            )
        return
    logger.error(
        "processor.retry_exhausted",
        extra={"job_id": str(job_id), "last_error_kind": exc.kind},
    )
    # Suppressed: if the database is what's failing, this write fails too.
    # The reaper in asr-service is the backstop for exactly that case.
    with contextlib.suppress(Exception):
        await _mark_failed(
            state,
            tenant_id,
            job_id,
            kind=str(JobErrorKind.RETRY_EXHAUSTED),
            detail=f"dead-lettered after repeated {exc.kind}: {exc.detail}",
            requester_sub=requester_sub,
        )


def _identify(msg: Message) -> tuple[UUID, UUID, UUID] | None:
    """(tenant_id, job_id, requester_sub) from a queue message, if it parses."""
    try:
        payload = JobEnqueuePayload.model_validate_json(msg.value.decode("utf-8"))
    except Exception:  # noqa: BLE001 — any parse failure means "no job to name"
        return None
    return payload.tenant_id, payload.job_id, payload.requester_sub


def _rediarize_request(msg: Message) -> UUID | None:
    """The re-run request a message carries, or None for a transcribe."""
    try:
        payload = JobEnqueuePayload.model_validate_json(msg.value.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if payload.task != "rediarize":
        return None
    request_id: UUID | None = payload.rediarize_id
    return request_id


# How often the engine may ask the database whether the user has
# cancelled. Between VAD chunks, so the real granularity is whichever is
# coarser — one chunk, or one second.
_CANCEL_POLL_SECONDS = 1.0


class _JobError(Exception):
    """A classified failure. ``kind`` is always a :class:`JobErrorKind` value."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


class _NonRetryableError(_JobError):
    """Terminal: the row already says failed, and redelivery cannot help."""


class _RetryableError(_JobError):
    """Transient: hand the message back; the same job may yet succeed."""


def _classified(kind: JobErrorKind, detail: str) -> _JobError:
    """Build the right exception for ``kind`` straight from its spec.

    Retry policy lives in the vocabulary, not at the raise site — so
    ``storage_unavailable`` cannot be spelled retryable in one branch and
    terminal in the next.
    """
    spec = spec_for(str(kind))
    cls = _RetryableError if spec is not None and spec.retryable else _NonRetryableError
    return cls(str(kind), detail)


async def _process_one(state: WorkerState, msg: Message) -> None:
    try:
        payload = JobEnqueuePayload.model_validate_json(msg.value.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — decode or schema, same dead end
        # Version skew: asr-service enqueued a shape this worker cannot
        # read. Retrying re-reads the same bytes to the same conclusion, so
        # this goes straight to the DLQ where an operator can see it.
        logger.error("processor.bad_payload", extra={"error": str(exc)})
        raise _NonRetryableError(
            str(JobErrorKind.BAD_PAYLOAD), f"{type(exc).__name__}: {exc}"
        ) from exc
    tenant_id = payload.tenant_id
    job_id = payload.job_id

    # Before the "row is complete → skip" guard below: a re-labelling run
    # targets a job that is complete by definition.
    if payload.task == "rediarize":
        await _rediarize_one(state, payload)
        return

    # Idempotency: check the row before doing work.
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        row = await conn.fetchrow(
            "SELECT status, cancel_requested FROM transcription_jobs WHERE id = $1",
            job_id,
        )
        if row is None:
            logger.warning(
                "processor.job_row_missing",
                extra={"job_id": str(job_id), "tenant_id": str(tenant_id)},
            )
            raise _NonRetryableError(str(JobErrorKind.JOB_ROW_MISSING), "job_id not in DB")
        if row["status"] in {"complete", "failed"}:
            logger.info(
                "processor.idempotent_skip",
                extra={"job_id": str(job_id), "status": row["status"]},
            )
            return
        if row["status"] == "cancelled":
            return
        if row["cancel_requested"]:
            await _mark_cancelled(state, tenant_id, job_id)
            return
        # Move the row to running.
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET status='running', started_at=now(), attempts=attempts+1
            WHERE id = $1 AND status IN ('queued','running')
            """,
            job_id,
        )

    await state.audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.TRANSCRIPTION_STARTED,
        target_kind="asr_job",
        target_id=str(job_id),
        payload={"audio_id": str(payload.audio_id)},
        severity=Severity.INFO,
    )

    t0 = time.monotonic()
    # Every classified failure below leaves through `die`, which records the
    # terminal ones on the row before raising. Retryable kinds deliberately
    # leave the row in `running`: the job has not failed, this attempt has.
    die = _dier(state, tenant_id, job_id, requester_sub=payload.requester_sub)
    try:
        ciphertext_key = f"{tenant_id}/{payload.audio_id}.enc"
        try:
            audio_bytes = await state.audio_store.get(
                key=ciphertext_key,
                tenant_id=tenant_id,
                aad=payload.audio_id.bytes,
            )
        except ObjectNotFoundError as exc:
            # Retention, the S11 erasure engine, or an upload whose row was
            # written but whose object never landed. The bytes are not
            # coming back — no amount of redelivery finds them.
            raise await die(JobErrorKind.AUDIO_MISSING, str(exc)) from exc
        except CryptoError as exc:
            # Wrong AAD, a tenant KEK that will not unwrap, a truncated
            # envelope. Deterministic, and an operator's problem — the
            # user re-uploading the same file changes nothing.
            raise await die(JobErrorKind.DECRYPT_FAILED, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — S3 transport
            raise await die(JobErrorKind.STORAGE_UNAVAILABLE, str(exc)) from exc

        try:
            stereo, pcm = await _decode_capture(audio_bytes, payload.channel_layout)
        except AudioDecodeError as exc:
            raise await die(JobErrorKind.CORRUPT_AUDIO, str(exc)) from exc

        audio_seconds = pcm.shape[0] / 16_000.0
        _audio_duration_seconds.record(audio_seconds)

        # ffmpeg is happy to decode a file into nothing — a container whose
        # audio stream is empty, or a recording that is pure silence. Whisper
        # given no samples answers with a hallucinated phrase, and a
        # hallucination stored as a `complete` transcript is worse than any
        # failure: it reaches the note looking like something the speaker
        # said.
        if audio_seconds <= 0:
            raise await die(JobErrorKind.NO_SPEECH, "decoded audio contains no samples")

        # Check cancel between fetch and inference.
        if await _is_cancelled(state, tenant_id, job_id):
            await _mark_cancelled(state, tenant_id, job_id)
            return

        if not state.engine.is_loaded:
            # The readiness probe should have caught this; if it did not,
            # say so rather than letting the engine's bare RuntimeError get
            # filed as `unhandled`.
            raise await die(JobErrorKind.MODEL_UNAVAILABLE, "whisper model is not loaded")

        max_infer = max(
            60.0,
            audio_seconds * settings.asr_max_inference_seconds_multiplier,
        )
        try:
            output: TranscriptionOutput = await asyncio.wait_for(
                state.engine.transcribe(
                    pcm,
                    language=payload.language,
                    # Optional free-text vocabulary hint → initial_prompt.
                    prompt=payload.vocabulary_hint,
                    # Cancel is a request, not a status: DELETE /asr/jobs/{id}
                    # on a RUNNING job only sets `cancel_requested`, and it is
                    # the worker that has to act on it. Before this it never
                    # looked again after inference started, so pressing Cancel
                    # on a job that was already transcribing did nothing at
                    # all — the job ran to completion and came back `complete`.
                    should_cancel=_cancel_poller(state, tenant_id, job_id),
                ),
                timeout=max_infer,
            )
        except TranscriptionCancelledError:
            await _mark_cancelled(state, tenant_id, job_id)
            return
        except TimeoutError:
            raise await die(JobErrorKind.TIMEOUT, f"inference exceeded {max_infer:.1f}s") from None
        except ProviderError as exc:
            # HTTP ASR backend (dev_mac_asr / hf_eu_asr) failed. Retryable
            # kinds (warming, unavailable, timeout, rate_limited) become
            # MODEL_UNAVAILABLE so the job is re-queued; anything else is
            # a hard failure with the kind in the message (no content).
            if exc.retryable:
                raise await die(
                    JobErrorKind.MODEL_UNAVAILABLE, f"asr backend {exc.backend}: {exc.kind}"
                ) from exc
            raise await die(
                JobErrorKind.UNHANDLED,
                f"asr backend {exc.backend}: {exc.kind}: {exc.message[:120]}",
            ) from exc
        except _CudaOOMError as exc:
            _oom_counter.add(1)
            err = await die(JobErrorKind.GPU_OOM, str(exc))
            _release_cuda_cache()
            raise err from exc

        # Inference ran and produced nothing. Same reasoning as the empty-PCM
        # gate above, one stage later: a zero-segment transcript stored as
        # `complete` reads to the user as "we transcribed your recording
        # and it was blank", which is indistinguishable from a lost dictation.
        if not output.segments:
            raise await die(
                JobErrorKind.NO_SPEECH,
                f"no speech recognised in {audio_seconds:.1f}s of audio",
            )

        infer_seconds = time.monotonic() - t0
        _inference_seconds.record(infer_seconds)
        if audio_seconds > 0:
            _realtime_factor.record(audio_seconds / max(infer_seconds, 1e-6))
        _gpu_memory_peak.record(output.metadata.peak_gpu_mem_mb)

        diar: OfflineDiarization | None = None
        # Set when a REMOTE diarizer (shape B) could not label this
        # recording: the transcript still completes, and the row carries
        # why, so the UI can offer "try telling speakers apart again".
        diarization_error: str | None = None
        if payload.diarize:
            # Ambient Capture v1: speaker-attribute the finished transcript.
            # Runs after the transcript exists so a diarizer failure can be
            # classified precisely (diarization_*) instead of burning the
            # Whisper pass into an `unhandled`.
            try:
                await state.diarizer.ensure_loaded()
            except DiarizationUnavailableError as exc:
                _diarizer_unavailable.add(1, {"engine": state.diarizer.engine})
                if not _remote(state.diarizer):
                    raise await die(JobErrorKind.DIARIZATION_UNAVAILABLE, str(exc)) from exc
                diarization_error = _remote_diarization_skipped(
                    JobErrorKind.DIARIZATION_UNAVAILABLE, state, job_id=job_id, exc=exc
                )
            diar_t0 = time.monotonic()
            try:
                if diarization_error is None:
                    diar, layout = await _diarize_capture(
                        state, pcm, stereo, _hints(payload), job_id=job_id
                    )
            except Exception as exc:  # noqa: BLE001 — model choked on these samples
                if not _remote(state.diarizer):
                    raise await die(JobErrorKind.DIARIZATION_FAILED, str(exc)) from exc
                diarization_error = _remote_diarization_skipped(
                    JobErrorKind.DIARIZATION_FAILED, state, job_id=job_id, exc=exc
                )
        if diar is not None:
            # Stop the clock before word attribution: this number is
            # judged against the 0.25 x audio budget, and attribution is
            # not the diarizer's work.
            diar_seconds = time.monotonic() - diar_t0
            output = _apply_diarization(output, diar)
            stats = _diarization_stats(output, diar, diar_seconds, channel_layout=layout)
            output = output.model_copy(
                update={"metadata": output.metadata.model_copy(update={"diarization": stats})}
            )
            _record_diarization_metrics(stats, audio_seconds=audio_seconds)

        # Last look before the transcript becomes a fact. A cancel that
        # landed during the final chunk, or while the audio was being
        # decoded, must not be overwritten by a `complete` — the user
        # asked for this job to stop, and a stored transcript is not stopping.
        if await _is_cancelled(state, tenant_id, job_id):
            await _mark_cancelled(state, tenant_id, job_id)
            return

        result_key = f"{tenant_id}/{job_id}.json.enc"
        body = output.model_dump_json().encode("utf-8")
        try:
            await state.transcript_store.put(
                key=result_key,
                plaintext=body,
                tenant_id=tenant_id,
                aad=job_id.bytes,
            )
        except Exception as exc:  # noqa: BLE001 — encrypt or transport
            # Retryable, and the retry redoes the inference. That is the
            # cheaper mistake: the alternative is a job marked complete
            # pointing at an object that was never written, which fails much
            # later, on read, as a 410 the user cannot act on.
            raise await die(JobErrorKind.RESULT_STORE_FAILED, str(exc)) from exc

        try:
            async with tenant_connection(state.app_pool, tenant_id) as conn:
                await conn.execute(
                    """
                    UPDATE transcription_jobs
                    SET status='complete',
                        result_storage_uri=$2,
                        finished_at=now(),
                        metadata=$3::jsonb,
                        detected_language=$4,
                        -- Shape B only: the transcript is complete but the
                        -- speakers are missing, and the clients read this
                        -- to offer a re-run.
                        diarization_status=CASE WHEN $5::text IS NULL THEN diarization_status
                                                ELSE 'failed' END,
                        diarization_error=COALESCE($5::text, diarization_error)
                    WHERE id = $1
                    """,
                    job_id,
                    f"minio://{state.transcript_store.bucket}/{result_key}",
                    json.dumps(output.metadata.model_dump(mode="json")),
                    # For an `auto` job this is what language identification
                    # heard; for a pinned job it echoes the pin. Clients pick
                    # the note template from it, so it lives on the row, not
                    # only inside the encrypted result.
                    output.language,
                    diarization_error,
                )
                await conn.execute(
                    "UPDATE audio_files SET status='transcribed' WHERE id = $1",
                    payload.audio_id,
                )
                named = _channel_name(output, payload.local_speaker_name)
                if named is not None:
                    # The one name the platform sets without a click (ADR-0053):
                    # the only speaker on this Mac's microphone is the account
                    # owner. Visible provenance, one click clears it — and a
                    # label a person already named or cleared is left alone.
                    await conn.execute(
                        """
                        UPDATE transcription_jobs
                        SET speaker_names = speaker_names || $2::jsonb,
                            speaker_name_sources = speaker_name_sources || $3::jsonb
                        WHERE id = $1
                          AND NOT (speaker_name_sources ? $4)
                          AND NOT (speaker_names ? $4)
                        """,
                        job_id,
                        json.dumps({named[0]: named[1]}),
                        json.dumps({named[0]: "channel"}),
                        named[0],
                    )
        except Exception as exc:  # noqa: BLE001 — asyncpg transport / pool
            # The transcript is stored; only the bookkeeping failed. The
            # redelivery re-runs inference and overwrites the same key, so
            # this is safe to retry — and unlike the alternative it does not
            # strand a finished transcript behind a `running` row.
            raise await die(JobErrorKind.DB_UNAVAILABLE, str(exc)) from exc

        await state.audit_writer.write_event(
            tenant_id=tenant_id,
            kind=audit_kinds.TRANSCRIPTION_COMPLETE,
            target_kind="asr_job",
            target_id=str(job_id),
            payload={
                "audio_seconds": round(audio_seconds, 2),
                "infer_seconds": round(infer_seconds, 2),
                "realtime_factor": round(audio_seconds / max(infer_seconds, 1e-6), 2),
                "peak_gpu_mem_mb": output.metadata.peak_gpu_mem_mb,
                "model": output.metadata.model,
                "segments": len(output.segments),
                "diarized": bool(payload.diarize),
                "speakers": len(output.speakers),
                "clusters_raw": (
                    output.metadata.diarization.clusters_raw
                    if output.metadata.diarization
                    else None
                ),
                "unknown_share": (
                    output.metadata.diarization.unknown_share
                    if output.metadata.diarization
                    else None
                ),
                "language": output.language,
                "language_detected": output.language_detected,
                "language_probability": output.language_probability,
            },
            severity=Severity.INFO,
        )

        # After the status UPDATE and the audit write, outside the
        # tenant_connection block — the same shape note-service uses.
        # A job the user submitted and stopped watching is the strongest
        # case in the system for a notification.
        await emit_transcription_completed(
            state.redis,
            tenant_id=tenant_id,
            job_id=job_id,
            requester_sub=payload.requester_sub,
            duration_ms=int(audio_seconds * 1000),
            segments=len(output.segments),
            language=output.language,
            model=output.metadata.model,
        )
        # After the job is complete and announced: the shadow engine can
        # neither change what the user sees nor make them wait for it.
        if diar is not None and state.shadow_diarizer is not None:
            await _run_shadow(state.shadow_diarizer, pcm, payload, diar, job_id=job_id)
    except _JobError:
        raise
    except Exception as exc:
        # Last-chance translation: anything we recognise as CUDA OOM
        # becomes a non-retryable error to avoid hammering the GPU.
        if _looks_like_oom(exc):
            _oom_counter.add(1)
            err = await die(JobErrorKind.GPU_OOM, str(exc))
            _release_cuda_cache()
            raise err from exc
        raise


def _apply_diarization(
    output: TranscriptionOutput, diar: OfflineDiarization
) -> TranscriptionOutput:
    """Speaker-attribute the transcript from the diarized timeline.

    Whisper segments follow its own pause heuristics, not speaker turns:
    a single segment routinely spans "…so that's the plan. — Sounds
    good." from two people. Attributing whole segments would label the
    reply with whoever talked longer. So attribution happens per WORD
    (the worker asks Whisper for word timings), and a segment is split
    wherever the speaker changes; each piece keeps its own words, timing
    and mean word probability.

    A word the diarizer cannot attribute inherits its neighbours' label
    when they agree (mid-sentence dropouts), and a one-word island
    between two runs of the same speaker is folded back — a diarizer
    hiccup, not a real interjection. What stays unattributed keeps
    ``speaker=None``: an uncertain label on a meeting transcript is worse
    than no label. Segments without word timings fall back to majority
    attribution of the whole span.

    ``speakers`` is the first-appearance roster of labels that actually
    ended up on a segment — a client counting "3 speakers" should be able
    to find all three in the text.
    """
    segments: list[Segment] = []
    for seg in output.segments:
        segments.extend(_split_segment_by_speaker(seg, diar))
    roster: list[str] = []
    for seg in segments:
        if seg.speaker and seg.speaker not in roster:
            roster.append(seg.speaker)
    return output.model_copy(
        update={
            "segments": segments,
            "speakers": roster,
            # Sprint 30: kept so the read path can mark turns where people
            # talked over each other. Intervals only.
            "overlap_ms": list(getattr(diar, "overlap_ms", []) or []),
            # Sprint 31: sides of the labels that reached the text.
            "speaker_sides": {
                label: side
                for label, side in (getattr(diar, "sides", None) or {}).items()
                if label in roster
            },
        }
    )


def _diarization_stats(
    output: TranscriptionOutput,
    diar: OfflineDiarization,
    seconds: float,
    *,
    channel_layout: str | None = None,
) -> DiarizationStats:
    """Numbers that explain the roster: clusterer counts, speech per
    speaker that reached the text, and how much speech stayed unlabelled."""
    evidence = diar.segments
    speech_ms = sum(s.end_ms - s.start_ms for s in evidence)
    unknown_ms = sum(s.end_ms - s.start_ms for s in evidence if s.label == UNKNOWN)
    per_speaker: dict[str, int] = {}
    for seg in output.segments:
        if not seg.speaker:
            continue
        spoken = (
            sum(w.end_ms - w.start_ms for w in seg.words)
            if seg.words
            else seg.end_ms - seg.start_ms
        )
        per_speaker[seg.speaker] = per_speaker.get(seg.speaker, 0) + spoken
    cs = diar.stats
    roster = diar.roster
    return DiarizationStats(
        engine=diar.engine,
        engine_version=diar.engine_version,
        hint_num_speakers=diar.hints.num_speakers,
        hint_max_speakers=diar.hints.max_speakers,
        count_confidence=roster.count_confidence if roster else None,
        channel_layout=channel_layout,
        leak_gain_db=(
            round(float(channel.leak_gain_db), 1)
            if (channel := getattr(diar, "channel", None)) and channel.leak_gain_db is not None
            else None
        ),
        local_speakers=channel.local_speakers if channel else None,
        remote_speakers=channel.remote_speakers if channel else None,
        both_share=channel.both_share if channel else None,
        speakers_dissolved=roster.speakers_dissolved if roster else 0,
        overlap_share=roster.overlap_share if roster else None,
        chunks=cs.chunks,
        clusters_raw=cs.clusters_raw,
        clusters_after_merge=cs.clusters_after_merge,
        clusters_dropped=cs.clusters_dropped,
        speakers=len(output.speakers),
        speech_seconds=round(speech_ms / 1000, 2),
        speaker_speech_seconds=sorted(
            (round(ms / 1000, 2) for ms in per_speaker.values()), reverse=True
        ),
        unknown_share=round(unknown_ms / speech_ms, 4) if speech_ms else 0.0,
        seconds=round(seconds, 3),
    )


# The local side must hold at least this much speech before the platform
# names its only speaker after the account owner (Sprint 31 B-5).
CHANNEL_NAME_MIN_SPEECH_MS = 10_000


async def _decode_capture(
    audio_bytes: bytes, channel_layout: str
) -> tuple[np.ndarray | None, np.ndarray]:
    """(stereo int16 (n, 2) or None, mono float32 for ASR)."""
    if channel_layout == "mic_system":
        stereo = await decode_to_pcm(
            audio_bytes,
            ffmpeg_path=settings.ffmpeg_path,
            timeout_seconds=settings.ffmpeg_timeout_seconds,
            channels=2,
        )
        # ASR stays one pass, on the mixdown.
        return stereo, mixdown(stereo)
    pcm = await decode_to_pcm(
        audio_bytes,
        ffmpeg_path=settings.ffmpeg_path,
        timeout_seconds=settings.ffmpeg_timeout_seconds,
    )
    return None, pcm


async def _diarize_capture(
    state: WorkerState,
    pcm: np.ndarray,
    stereo: np.ndarray | None,
    hints: DiarizationHints,
    *,
    job_id: UUID,
) -> tuple[OfflineDiarization, str]:
    """Diarize a capture: channel-aware for a mic/system file, else mono.

    A failure anywhere in the channel path falls back to the mono path on
    the mixdown — a channel-analysis bug must never cost the user their
    speakers. A failure of the mono path itself propagates.
    """
    if stereo is not None:
        try:
            diar = await asyncio.to_thread(
                diarize_dual,
                stereo[:, 0],
                stereo[:, 1],
                diarizer=state.diarizer,
                hints=hints,
                segmenter=_channel_segmenter(state),
            )
            _dual_jobs.add(1, {"outcome": "dual"})
            return diar, "mic_system"
        except DiarizationUnavailableError:
            # The engine itself is down (shape B: the endpoint). The mono
            # path would upload the whole recording again to the same
            # dead endpoint, and this fallback is for channel-analysis
            # bugs, not for the diarizer being unreachable.
            raise
        except Exception as exc:  # noqa: BLE001 — any channel-path failure
            _dual_jobs.add(1, {"outcome": "mono_fallback"})
            logger.warning(
                "diarization.dual_fallback",
                extra={"job_id": str(job_id), "error_class": type(exc).__name__},
            )
            diar = await asyncio.to_thread(state.diarizer.diarize, pcm, 16_000, hints=hints)
            return diar, "mono_fallback"
    diar = await asyncio.to_thread(state.diarizer.diarize, pcm, 16_000, hints=hints)
    return diar, "mono"


def _channel_segmenter(state: WorkerState) -> Any:
    """Silero VAD for the channel analysis, built once per worker, lazily."""
    if state.channel_segmenter is None:
        state.channel_segmenter = SileroSegmenter()
    return state.channel_segmenter


def _channel_name(output: TranscriptionOutput, local_name: str | None) -> tuple[str, str] | None:
    """(label, name) when exactly one speaker is local and spoke enough."""
    name = " ".join((local_name or "").split())[:80]
    if not name:
        return None
    local = [label for label, side in output.speaker_sides.items() if side == "local"]
    if len(local) != 1:
        return None
    spoken = sum(
        (sum(w.end_ms - w.start_ms for w in seg.words) if seg.words else seg.end_ms - seg.start_ms)
        for seg in output.segments
        if seg.speaker == local[0]
    )
    return (local[0], name) if spoken >= CHANNEL_NAME_MIN_SPEECH_MS else None


def _hints(payload: JobEnqueuePayload) -> DiarizationHints:
    return DiarizationHints(
        num_speakers=payload.num_speakers, max_speakers=payload.max_speakers
    ).validated()


def _record_diarization_metrics(stats: DiarizationStats, *, audio_seconds: float) -> None:
    _diarized_jobs.add(1)
    _diarization_speakers.record(stats.speakers, {"engine": stats.engine})
    _diarization_seconds.record(stats.seconds, {"engine": stats.engine})
    if audio_seconds > 0:
        _diarization_audio_ratio.record(stats.seconds / audio_seconds, {"engine": stats.engine})
    _diarization_unknown_share.record(stats.unknown_share)
    if stats.clusters_dropped:
        _diarization_clusters_dropped.add(stats.clusters_dropped)


async def _run_shadow(
    shadow: Diarizer,
    pcm: np.ndarray,
    payload: JobEnqueuePayload,
    primary: OfflineDiarization,
    *,
    job_id: UUID,
) -> None:
    """Run the shadow engine on the same audio and hints; keep only counts.

    Its labels are discarded here, never stored or returned. Any failure is
    logged and swallowed: a shadow must not be able to fail a job.
    """
    t0 = time.monotonic()
    try:
        await shadow.ensure_loaded()
        result = await asyncio.to_thread(shadow.diarize, pcm, 16_000, hints=_hints(payload))
    except Exception as exc:  # noqa: BLE001 — the shadow is advisory, always
        logger.warning(
            "diarization.shadow_failed",
            extra={
                "job_id": str(job_id),
                "engine": shadow.engine,
                "error_class": type(exc).__name__,
            },
        )
        return
    seconds = time.monotonic() - t0
    speakers_primary = len(primary.speakers)
    speakers_shadow = len(result.speakers)
    _shadow_delta.record(
        speakers_shadow - speakers_primary,
        {"primary": primary.engine, "shadow": shadow.engine},
    )
    logger.info(
        "diarization.shadow",
        extra={
            "job_id": str(job_id),
            "primary_engine": primary.engine,
            "shadow_engine": shadow.engine,
            "speakers_primary": speakers_primary,
            "speakers_shadow": speakers_shadow,
            "seconds_shadow": round(seconds, 3),
        },
    )


def _split_segment_by_speaker(seg: Segment, diar: OfflineDiarization) -> list[Segment]:
    if not seg.words:
        return [
            seg.model_copy(
                update={
                    "speaker": diar.attribute(int(seg.start_ms), int(seg.end_ms)),
                    "speaker_uncertain": False,
                }
            )
        ]

    raw: list[str | None] = [diar.attribute(int(w.start_ms), int(w.end_ms)) for w in seg.words]
    labels = _smooth_labels(raw)
    # A word whose label smoothing supplied or changed: the piece holding
    # it is marked uncertain (Sprint 30) — likeliest place for a correction.
    smoothed = [r != lab and lab is not None for r, lab in zip(raw, labels, strict=True)]
    if all(label == labels[0] for label in labels):
        return [seg.model_copy(update={"speaker": labels[0], "speaker_uncertain": any(smoothed)})]

    # The segment text is Whisper's own rendering (punctuation, spacing);
    # once split, each piece is rebuilt from its words. Whisper's word
    # texts carry their punctuation, so joining with spaces reproduces
    # the original for space-delimited languages; languages written
    # without spaces are joined the way the original text was.
    joiner = " " if " " in seg.text.strip() else ""
    pieces: list[Segment] = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i < len(labels) and labels[i] == labels[start]:
            continue
        words = seg.words[start:i]
        probs = [w.probability for w in words]
        pieces.append(
            Segment(
                text=joiner.join(w.text for w in words).strip(),
                start_ms=words[0].start_ms,
                end_ms=max(w.end_ms for w in words),
                words=list(words),
                avg_confidence=max(0.0, min(1.0, sum(probs) / len(probs))),
                speaker=labels[start],
                speaker_uncertain=any(smoothed[start:i]),
            )
        )
        start = i
    return [p for p in pieces if p.text]


def _smooth_labels(labels: list[str | None]) -> list[str | None]:
    """Fill unattributed words from agreeing neighbours; fold one-word
    islands between two runs of the same speaker."""
    out = list(labels)
    n = len(out)
    # Pass 1: None runs whose neighbours agree (or with one known
    # neighbour at either edge of the segment) take that label.
    i = 0
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        before = out[i - 1] if i > 0 else None
        after = out[j] if j < n else None
        fill = before if (after is None or before == after) else (after if before is None else None)
        if fill is not None:
            for k in range(i, j):
                out[k] = fill
        i = j
    # Pass 2: a single word labelled X between two words labelled Y is Y.
    for k in range(1, n - 1):
        if out[k] != out[k - 1] and out[k - 1] == out[k + 1] and out[k - 1] is not None:
            out[k] = out[k - 1]
    return out


# ── Re-labelling (Sprint 29, ``task="rediarize"``) ─────────────────────


def revision_key(tenant_id: UUID, job_id: UUID, rev: int) -> str:
    """Object key of the artifact a re-run writes. Deterministic per
    ``target_rev``: a redelivery overwrites the same object."""
    return f"{tenant_id}/{job_id}.r{rev}.json.enc"


def key_from_uri(uri: str) -> str:
    """``minio://bucket/<key>`` → ``<key>``."""
    return uri.split("://", 1)[-1].split("/", 1)[1]


# A name follows its speaker into the new labelling only when the new
# speaker holds at least this much of the old one's speech.
NAME_CARRY_MIN_SHARE = 0.6


async def _rediarize_one(state: WorkerState, payload: JobEnqueuePayload) -> None:
    """New speaker labels for a complete job, from the stored audio and the
    stored words. No ASR pass: the words and their timings are already in
    the transcript; only who said them is recomputed.

    The job's ``status`` stays ``complete`` throughout. Idempotent under
    redelivery: the claim is conditional on the revision this run moves
    FROM, the artifact key is deterministic per ``target_rev``, and the
    final swap re-checks the revision under a row lock — so a duplicate
    delivery that arrives after completion does nothing, and one that
    arrives after a crash finishes the job the first delivery started.
    """
    tenant_id, job_id = payload.tenant_id, payload.job_id
    target_rev = payload.target_rev
    request_id = payload.rediarize_id
    if request_id is None:
        # No request to answer for: nothing on the row can be claimed.
        raise _NonRetryableError(str(JobErrorKind.BAD_PAYLOAD), "rediarize without rediarize_id")
    if target_rev is None or target_rev < 2:
        await _mark_rediarize_failed(
            state, tenant_id, job_id, request_id=request_id, kind=str(JobErrorKind.BAD_PAYLOAD)
        )
        raise _NonRetryableError(str(JobErrorKind.BAD_PAYLOAD), "rediarize without a target_rev")
    t0 = time.monotonic()

    # Claimed only for THIS request (a stale message for an earlier one
    # finds another id and skips). `running` is claimable too: that is a
    # redelivery of this same request after its worker died.
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        claimed = await conn.fetchrow(
            """
            UPDATE transcription_jobs
            SET diarization_status='running', diarization_updated_at=now()
            WHERE id = $1 AND status = 'complete'
              AND diarization_status IN ('queued','running')
              AND diarization_rev = $2
              AND diarization_request_id = $3
            RETURNING result_storage_uri, capture_context
            """,
            job_id,
            target_rev - 1,
            request_id,
        )
    if claimed is None:
        # Already done (duplicate delivery), superseded, or the row moved on.
        logger.info("processor.rediarize_skip", extra={"job_id": str(job_id)})
        return

    async def fail(kind: JobErrorKind, detail: str) -> _JobError:
        err = _classified(kind, detail)
        if isinstance(err, _NonRetryableError):
            await _mark_rediarize_failed(
                state, tenant_id, job_id, request_id=request_id, kind=str(kind)
            )
            logger.warning(
                "processor.rediarize_failed",
                extra={"job_id": str(job_id), "error_kind": str(kind), "detail": detail[:200]},
            )
        return err

    if not claimed["result_storage_uri"]:
        raise await fail(JobErrorKind.AUDIO_MISSING, "job has no stored transcript")
    current_key = key_from_uri(str(claimed["result_storage_uri"]))

    try:
        audio_bytes = await state.audio_store.get(
            key=f"{tenant_id}/{payload.audio_id}.enc",
            tenant_id=tenant_id,
            aad=payload.audio_id.bytes,
        )
    except ObjectNotFoundError as exc:
        raise await fail(JobErrorKind.AUDIO_MISSING, str(exc)) from exc
    except CryptoError as exc:
        raise await fail(JobErrorKind.DECRYPT_FAILED, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — S3 transport
        raise await fail(JobErrorKind.STORAGE_UNAVAILABLE, str(exc)) from exc
    try:
        current = TranscriptionOutput.model_validate_json(
            await state.transcript_store.get(key=current_key, tenant_id=tenant_id, aad=job_id.bytes)
        )
    except ObjectNotFoundError as exc:
        raise await fail(JobErrorKind.AUDIO_MISSING, f"transcript gone: {exc}") from exc
    except CryptoError as exc:
        raise await fail(JobErrorKind.DECRYPT_FAILED, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise await fail(JobErrorKind.STORAGE_UNAVAILABLE, str(exc)) from exc
    # A dual-channel capture re-runs dual-channel (the layout travels on
    # the job's capture context, Sprint 31).
    layout = _parse_names(claimed["capture_context"]).get("channel_layout", "mono")
    try:
        stereo, pcm = await _decode_capture(audio_bytes, layout)
    except AudioDecodeError as exc:
        raise await fail(JobErrorKind.CORRUPT_AUDIO, str(exc)) from exc

    try:
        await state.diarizer.ensure_loaded()
    except DiarizationUnavailableError as exc:
        _diarizer_unavailable.add(1, {"engine": state.diarizer.engine})
        raise await fail(JobErrorKind.DIARIZATION_UNAVAILABLE, str(exc)) from exc
    diar_t0 = time.monotonic()
    try:
        diar, used_layout = await _diarize_capture(
            state, pcm, stereo, _hints(payload), job_id=job_id
        )
    except Exception as exc:  # noqa: BLE001 — deterministic for a recording
        raise await fail(JobErrorKind.DIARIZATION_FAILED, str(exc)) from exc

    stripped = current.model_copy(
        update={
            "segments": [
                s.model_copy(update={"speaker": None, "speaker_uncertain": False})
                for s in current.segments
            ]
        }
    )
    relabelled = _apply_diarization(stripped, diar)
    stats = _diarization_stats(
        relabelled, diar, time.monotonic() - diar_t0, channel_layout=used_layout
    )
    relabelled = relabelled.model_copy(
        update={"metadata": relabelled.metadata.model_copy(update={"diarization": stats})}
    )
    _record_diarization_metrics(stats, audio_seconds=pcm.shape[0] / 16_000.0)
    mapping = carry_over_mapping(current.segments, relabelled.segments)

    new_key = revision_key(tenant_id, job_id, target_rev)
    try:
        await state.transcript_store.put(
            key=new_key,
            plaintext=relabelled.model_dump_json().encode("utf-8"),
            tenant_id=tenant_id,
            aad=job_id.bytes,
        )
    except Exception as exc:  # noqa: BLE001
        raise await fail(JobErrorKind.RESULT_STORE_FAILED, str(exc)) from exc

    try:
        async with tenant_connection(state.app_pool, tenant_id) as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT diarization_rev, result_storage_uri, previous_result_storage_uri,
                       speaker_names, speaker_name_sources, diarization_request_id
                FROM transcription_jobs WHERE id = $1 FOR UPDATE
                """,
                job_id,
            )
            if (
                row is None
                or int(row["diarization_rev"]) != target_rev - 1
                or row["diarization_request_id"] != request_id
            ):
                # Another delivery finished first; its revision stands.
                return
            # Names as they are NOW (a rename during the run counts).
            names = _parse_names(row["speaker_names"])
            carried = {mapping[old]: name for old, name in names.items() if old in mapping}
            # Provenance follows its name — and "cleared" follows the
            # speaker, so a channel name a person removed never returns.
            sources = _parse_names(row.get("speaker_name_sources"))
            carried_sources = {
                mapping[old]: source for old, source in sources.items() if old in mapping
            }
            await conn.execute(
                """
                UPDATE transcription_jobs
                SET previous_result_storage_uri = result_storage_uri,
                    previous_speaker_names = speaker_names,
                    result_storage_uri = $2,
                    diarization_rev = $3,
                    diarization_status = 'complete',
                    diarization_error = NULL,
                    diarization_updated_at = now(),
                    metadata = $4::jsonb,
                    speaker_names = $5::jsonb,
                    speaker_name_sources = $6::jsonb
                WHERE id = $1
                """,
                job_id,
                f"minio://{state.transcript_store.bucket}/{new_key}",
                target_rev,
                json.dumps(relabelled.metadata.model_dump(mode="json")),
                json.dumps(carried),
                json.dumps(carried_sources),
            )
            superseded = row["previous_result_storage_uri"]
    except Exception as exc:  # noqa: BLE001
        raise await fail(JobErrorKind.DB_UNAVAILABLE, str(exc)) from exc

    # Keep exactly one previous revision. Best effort: an orphan is a
    # storage cost, not a correctness problem, and erasure lists by prefix.
    if superseded and key_from_uri(str(superseded)) not in {new_key, current_key}:
        with contextlib.suppress(Exception):
            await state.transcript_store.delete(key=key_from_uri(str(superseded)))

    seconds = time.monotonic() - t0
    _rediarize_total.add(1, {"outcome": "complete"})
    _rediarize_seconds.record(seconds)
    await state.audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.REDIARIZE_COMPLETED,
        target_kind="asr_job",
        target_id=str(job_id),
        payload={
            "speakers_before": len(current.speakers),
            "speakers_after": len(relabelled.speakers),
            "engine": diar.engine,
        },
        severity=Severity.INFO,
    )


def carry_over_mapping(before: list[Segment], after: list[Segment]) -> dict[str, str]:
    """Old label → new label, for the labels whose names may follow.

    Both lists hold the SAME words (a re-run re-attributes, it never
    re-transcribes), so speech time is matched word by word. A label maps
    to the new label that took the most of its speech, and only when that
    is at least :data:`NAME_CARRY_MIN_SHARE` of it — and of the new label's
    speech too; two old labels landing on one new label (a merge) both lose
    the right to name it — a name is never guessed between two people.
    """
    before_words = _word_labels(before)
    after_words = _word_labels(after)
    overlap: dict[str, dict[str, int]] = {}
    spoken: dict[str, int] = {}
    received: dict[str, int] = {}
    for (span, old), (_, new) in zip(before_words, after_words, strict=False):
        if new is not None:
            received[new] = received.get(new, 0) + span
        if old is None:
            continue
        spoken[old] = spoken.get(old, 0) + span
        if new is not None:
            overlap.setdefault(old, {})
            overlap[old][new] = overlap[old].get(new, 0) + span
    best: dict[str, str] = {}
    for old, targets in overlap.items():
        new, ms = max(targets.items(), key=lambda kv: (kv[1], kv[0]))
        # Both ways: the old speaker mostly became `new`, AND `new` is mostly
        # the old speaker — otherwise the name would land on someone else's
        # voice as much as on theirs.
        if (
            spoken[old]
            and ms / spoken[old] >= NAME_CARRY_MIN_SHARE
            and ms / received[new] >= NAME_CARRY_MIN_SHARE
        ):
            best[old] = new
    claimed: dict[str, int] = {}
    for new in best.values():
        claimed[new] = claimed.get(new, 0) + 1
    return {old: new for old, new in best.items() if claimed[new] == 1}


def _word_labels(segments: list[Segment]) -> list[tuple[int, str | None]]:
    """(duration_ms, speaker) per word, in order; a wordless segment counts
    as one "word" so the two sides still line up."""
    out: list[tuple[int, str | None]] = []
    for seg in segments:
        if seg.words:
            out.extend((w.end_ms - w.start_ms, seg.speaker) for w in seg.words)
        else:
            out.append((seg.end_ms - seg.start_ms, seg.speaker))
    return out


def _parse_names(raw: object) -> dict[str, str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v}


def _remote(diarizer: Any) -> bool:
    """Does this engine run on another host? (shape B, ADR-0052)"""
    return bool(getattr(diarizer, "remote", False))


def _remote_diarization_skipped(
    kind: JobErrorKind, state: WorkerState, *, job_id: UUID, exc: Exception
) -> str:
    """A remote diarizer failed: log it and let the transcript through.

    With the engine in-process, a diarizer that cannot run means a broken
    deployment and the job fails loudly. On a remote engine the same
    outage is somebody else's bad afternoon, and failing the job would
    throw away a transcript we already have. The row remembers the
    failure (``diarization_status='failed'``) and the clients turn that
    into a re-run offer.
    """
    if kind is JobErrorKind.DIARIZATION_FAILED:
        # The load path already counted itself; count the call failures
        # too, so DiarizationEngineUnavailable fires for an endpoint that
        # answers but cannot diarize — otherwise a broken endpoint is
        # visible only as transcripts quietly missing their speakers.
        _diarizer_unavailable.add(1, {"engine": state.diarizer.engine})
    logger.warning(
        "asr.diarization_skipped_remote",
        extra={
            "job_id": str(job_id),
            "engine": state.diarizer.engine,
            "error_kind": kind.value,
            "error_class": type(exc).__name__,
        },
    )
    return str(kind.value)


async def _mark_rediarize_failed(
    state: WorkerState, tenant_id: UUID, job_id: UUID, *, request_id: UUID, kind: str
) -> None:
    """The re-run failed; the job, its transcript and its labels did not.

    Only THIS request's run: a stale delivery must not fail a newer one, and
    a write that matched nothing is neither counted nor audited."""
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        failed = await conn.fetchrow(
            """
            UPDATE transcription_jobs
            SET diarization_status='failed', diarization_error=$2, diarization_updated_at=now()
            WHERE id = $1 AND diarization_status IN ('queued','running')
              AND diarization_request_id = $3
            RETURNING id
            """,
            job_id,
            kind,
            request_id,
        )
    if failed is None:
        return
    _rediarize_total.add(1, {"outcome": "failed"})
    await state.audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.REDIARIZE_FAILED,
        target_kind="asr_job",
        target_id=str(job_id),
        payload={"error_kind": kind},
        severity=Severity.WARN,
    )


def _dier(
    state: WorkerState, tenant_id: UUID, job_id: UUID, *, requester_sub: UUID
) -> Callable[[JobErrorKind, str], Awaitable[_JobError]]:
    """Build the ``die(kind, detail)`` used by every classified failure.

    Returns (rather than raises) the exception so call sites read
    ``raise await die(...) from exc`` and keep the original traceback
    chained — the detail column is the only place the underlying ffmpeg or
    CUDA text survives, and losing the ``__cause__`` would cost the log its
    stack.

    Terminal kinds are written to the row here, once, before the raise;
    retryable kinds are not, because the job has not finished failing.
    """

    async def die(kind: JobErrorKind, detail: str) -> _JobError:
        err = _classified(kind, detail)
        if isinstance(err, _NonRetryableError):
            await _mark_failed(
                state,
                tenant_id,
                job_id,
                kind=str(kind),
                detail=detail,
                requester_sub=requester_sub,
            )
        return err

    return die


def _cancel_poller(
    state: WorkerState, tenant_id: UUID, job_id: UUID
) -> Callable[[], Awaitable[bool]]:
    """`should_cancel` for the engine, rate-limited to one query a second.

    VAD can cut a long consultation into hundreds of speech runs, and a
    round trip per run would spend more time asking whether to stop than
    stopping saves. A second of extra inference is not worth a query storm.
    """
    last = 0.0
    answer = False

    async def poll() -> bool:
        nonlocal last, answer
        now = time.monotonic()
        if answer or now - last < _CANCEL_POLL_SECONDS:
            return answer
        last = now
        answer = await _is_cancelled(state, tenant_id, job_id)
        return answer

    return poll


async def _is_cancelled(state: WorkerState, tenant_id: UUID, job_id: UUID) -> bool:
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        row = await conn.fetchrow(
            "SELECT cancel_requested FROM transcription_jobs WHERE id = $1",
            job_id,
        )
    return bool(row and row["cancel_requested"])


async def _mark_cancelled(state: WorkerState, tenant_id: UUID, job_id: UUID) -> None:
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET status='cancelled', finished_at=now()
            WHERE id = $1 AND status NOT IN ('complete','failed','cancelled')
            """,
            job_id,
        )
    await state.audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.JOB_CANCELLED,
        target_kind="asr_job",
        target_id=str(job_id),
        payload={"actor": "worker"},
        severity=Severity.INFO,
    )


async def _mark_failed(
    state: WorkerState,
    tenant_id: UUID,
    job_id: UUID,
    *,
    kind: str,
    detail: str,
    requester_sub: UUID,
) -> None:
    """Terminal-failure path. Every failure funnels through here.

    `requester_sub` is threaded in rather than re-SELECTed: the row is
    about to be UPDATEd anyway, and a second query for a value the caller
    already holds in `payload` is a round trip for nothing.
    """
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET status='failed', error_kind=$2, error_detail=$3, finished_at=now()
            WHERE id = $1
            """,
            job_id,
            kind,
            detail[:1024],
        )
    await state.audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.TRANSCRIPTION_FAILED,
        target_kind="asr_job",
        target_id=str(job_id),
        payload={"error_kind": kind, "detail": detail[:200]},
        severity=Severity.ERROR,
    )

    # `kind` only, never `detail` — see emit_transcription_failed.
    await emit_transcription_failed(
        state.redis,
        tenant_id=tenant_id,
        job_id=job_id,
        requester_sub=requester_sub,
        error_kind=kind,
    )


class _CudaOOMError(RuntimeError):
    pass


def _looks_like_oom(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "cuda out of memory" in msg or "outofmemory" in msg:
        return True
    try:
        import torch

        return isinstance(exc, torch.cuda.OutOfMemoryError)  # type: ignore[attr-defined]
    except Exception:
        return False


def _release_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
