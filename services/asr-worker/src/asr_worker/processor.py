"""Job processor: queue message → decode → ASR → diarize → encrypted result → row.

Failure kinds come from :mod:`asr_models.errors`; the spec's ``retryable`` decides
redelivery vs. recording on the row. Invariant: the row reaches a terminal status
before the message is acked. Cancellation is a request flag on the row, polled at
four points (before claim, after decode, between chunks, before store).
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
    Diagnostics,
    DiarizationStats,
    DroppedSegment,
    JobEnqueuePayload,
    JobErrorKind,
    LoopEvent,
    SecondPass,
    Segment,
    TranscriptionMetadata,
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

from . import audit_kinds, chunks, guards, quality, shadow, vad
from . import coverage as cov
from .audio_io import AudioDecodeError, decode_to_pcm, mixdown
from .config import settings
from .echo import guard_segments
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
# Per-job ratio so the p95 (budget 0.25) is of the ratio itself.
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
_prompt_echo_words = _meter.create_counter(
    "mdx_asr_prompt_echo_words_total",
    description="Words removed as prompt echo by the lexical guard (Sprint I2 T3)",
    unit="1",
)
_prompt_echo_segments_dropped = _meter.create_counter(
    "mdx_asr_prompt_echo_segments_dropped_total",
    description="Segments left empty by the prompt-echo guard and dropped (Sprint I2 T3)",
    unit="1",
)
_uncovered_speech_ms = _meter.create_counter(
    "mdx_asr_uncovered_speech_ms_total",
    description="Speech with no transcript, by gap cause (Sprint F1)",
    unit="1",
)
_speech_ms = _meter.create_counter(
    "mdx_asr_speech_ms_total",
    description="Speech heard by VAD in completed jobs; the uncovered share's denominator (Sprint F1)",
    unit="1",
)
_second_pass_total = _meter.create_counter(
    "mdx_asr_second_pass_total",
    description="Speech runs decoded a second time without the prompt, by cause and outcome (Sprint F1)",
    unit="1",
)
_coverage_share = _meter.create_histogram(
    "mdx_asr_coverage_share",
    description="Share of a job's speech the transcript covers (Sprint F1)",
    unit="1",
    explicit_bucket_boundaries_advisory=[0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 1.0],
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
                # Row already says failed; ack so it is not redelivered.
                logger.info(
                    "processor.non_retryable",
                    extra={"reason": exc.kind, "detail": str(exc)},
                )
                await consumer.ack(msg)
            except _RetryableError as exc:
                # Row stays `running` on purpose; only exhaustion is terminal.
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
    """Hand a retryable failure back to the queue; a DLQ'd message must also fail the row."""
    dead_lettered = await consumer.fail(msg, error_kind=exc.kind)
    if not dead_lettered:
        return
    ids = _identify(msg)
    if ids is None:
        return
    tenant_id, job_id, requester_sub = ids
    request_id = _rediarize_request(msg)
    if request_id is not None:
        # Fails the re-run only; the job and its labels are untouched.
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
    # If the DB is what's failing this write fails too; the reaper is the backstop.
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


# Cancel poll interval; checked between VAD chunks, so granularity is the coarser of the two.
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
    """Exception for ``kind``; retry policy comes from the spec, never the raise site."""
    spec = spec_for(str(kind))
    cls = _RetryableError if spec is not None and spec.retryable else _NonRetryableError
    return cls(str(kind), detail)


async def _process_one(state: WorkerState, msg: Message) -> None:
    try:
        payload = JobEnqueuePayload.model_validate_json(msg.value.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — decode or schema, same dead end
        # Version skew: deterministic, so straight to the DLQ.
        logger.error("processor.bad_payload", extra={"error": str(exc)})
        raise _NonRetryableError(
            str(JobErrorKind.BAD_PAYLOAD), f"{type(exc).__name__}: {exc}"
        ) from exc
    tenant_id = payload.tenant_id
    job_id = payload.job_id

    # Before the complete→skip guard: a re-run targets a complete job.
    if payload.task == "rediarize":
        await _rediarize_one(state, payload)
        return

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
    # `die` records terminal kinds on the row before raising; retryable kinds leave it `running`.
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
            raise await die(JobErrorKind.AUDIO_MISSING, str(exc)) from exc
        except CryptoError as exc:
            raise await die(JobErrorKind.DECRYPT_FAILED, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — S3 transport
            raise await die(JobErrorKind.STORAGE_UNAVAILABLE, str(exc)) from exc

        try:
            stereo, pcm = await _decode_capture(audio_bytes, payload.channel_layout)
        except AudioDecodeError as exc:
            raise await die(JobErrorKind.CORRUPT_AUDIO, str(exc)) from exc

        audio_seconds = pcm.shape[0] / 16_000.0
        _audio_duration_seconds.record(audio_seconds)

        # Whisper hallucinates on empty input; never store that as `complete`.
        if audio_seconds <= 0:
            raise await die(JobErrorKind.NO_SPEECH, "decoded audio contains no samples")

        if await _is_cancelled(state, tenant_id, job_id):
            await _mark_cancelled(state, tenant_id, job_id)
            return

        if not state.engine.is_loaded:
            raise await die(JobErrorKind.MODEL_UNAVAILABLE, "whisper model is not loaded")

        max_infer = max(
            60.0,
            audio_seconds * settings.asr_max_inference_seconds_multiplier,
        )
        # One budget for both decode passes.
        deadline = time.monotonic() + max_infer
        should_cancel = _cancel_poller(state, tenant_id, job_id)
        try:
            output: TranscriptionOutput = await decode_recording(
                state,
                pcm,
                stereo=stereo,
                language=payload.language,
                prompt=payload.vocabulary_hint,
                first_frame_offset_ms=payload.first_frame_offset_ms,
                timeout=max_infer,
                deadline=deadline,
                should_cancel=should_cancel,
                job_id=job_id,
            )
        except TranscriptionCancelledError:
            await _mark_cancelled(state, tenant_id, job_id)
            return
        except TimeoutError:
            raise await die(JobErrorKind.TIMEOUT, f"inference exceeded {max_infer:.1f}s") from None
        except ProviderError as exc:
            # Retryable backend kinds re-queue as MODEL_UNAVAILABLE; the rest fail hard,
            # kind only (no content).
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

        # Shadow ASR runs alongside diarization; bounded, numbers only.
        shadow_task: asyncio.Task[Any] | None = None
        if getattr(state, "shadow_asr", None) is not None and output.segments and shadow.sampled():
            shadow_task = asyncio.create_task(
                shadow.run(
                    state.shadow_asr,
                    redis=state.redis,
                    decode=decode_recording,
                    primary=output,
                    audio_seconds=audio_seconds,
                    decode_kwargs={
                        "pcm": pcm,
                        "stereo": stereo,
                        "language": payload.language,
                        "prompt": payload.vocabulary_hint,
                        "first_frame_offset_ms": payload.first_frame_offset_ms,
                        "timeout": max_infer,
                        "deadline": time.monotonic() + max_infer,
                        "should_cancel": None,
                        "job_id": job_id,
                    },
                )
            )

        # A zero-segment `complete` transcript is indistinguishable from a lost dictation.
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
        # Remote diarizer failure: transcript still completes, row carries why.
        diarization_error: str | None = None
        if payload.diarize:
            # After the transcript exists, so a diarizer failure classifies as diarization_*.
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
            # Clock stops before word attribution (budget is the diarizer's alone).
            diar_seconds = time.monotonic() - diar_t0
            output = _apply_diarization(output, diar)
            stats = _diarization_stats(output, diar, diar_seconds, channel_layout=layout)
            output = output.model_copy(
                update={"metadata": output.metadata.model_copy(update={"diarization": stats})}
            )
            _record_diarization_metrics(stats, audio_seconds=audio_seconds)

        # A cancel that landed during the last chunk must not become `complete`.
        if await _is_cancelled(state, tenant_id, job_id):
            await _mark_cancelled(state, tenant_id, job_id)
            return

        if shadow_task is not None:
            shadow_diag = await shadow.bounded(shadow_task)
            if shadow_diag is not None:
                output = output.model_copy(
                    update={
                        "diagnostics": output.diagnostics.model_copy(update={"shadow": shadow_diag})
                    }
                )

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
            # Retryable: redoing inference beats a `complete` row pointing at a missing object.
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
                        -- Numbers only, for the admin dashboard (0067).
                        quality=$6::jsonb,
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
                    # Language lives on the row: clients pick the template from it.
                    output.language,
                    diarization_error,
                    json.dumps(quality.summarize(output, audio_seconds=audio_seconds)),
                )
                await conn.execute(
                    "UPDATE audio_files SET status='transcribed' WHERE id = $1",
                    payload.audio_id,
                )
                named = _channel_name(output, payload.local_speaker_name)
                if named is not None:
                    # ADR-0053: sole local speaker is the owner; a label a person set
                    # or cleared is left alone.
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
            # Transcript stored, bookkeeping failed; a retry overwrites the same key.
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

        # After the status UPDATE and audit write, outside tenant_connection.
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
        # After completion: the shadow engine can neither change nor delay the result.
        if diar is not None and state.shadow_diarizer is not None:
            await _run_shadow(state.shadow_diarizer, pcm, payload, diar, job_id=job_id)
    except _JobError:
        raise
    except Exception as exc:
        # CUDA OOM is terminal, to avoid hammering the GPU.
        if _looks_like_oom(exc):
            _oom_counter.add(1)
            err = await die(JobErrorKind.GPU_OOM, str(exc))
            _release_cuda_cache()
            raise err from exc
        raise


async def decode_recording(
    state: Any,
    pcm: np.ndarray,
    *,
    stereo: np.ndarray | None,
    language: str,
    prompt: str | None,
    first_frame_offset_ms: int | None,
    timeout: float,
    deadline: float,
    should_cancel: Any,
    job_id: UUID,
) -> TranscriptionOutput:
    """The one audio→transcript path, shared by the job and the eval harness.

    VAD → chunk plan → backend decode → guards → prompt-echo guard → coverage
    second pass → non-speech markers. Raises what the engine raises; ``deadline``
    bounds both decodes together.
    """
    provider = state.engine
    heard = await asyncio.to_thread(
        vad.speech_runs,
        pcm,
        stereo=stereo,
        pad_ms=settings.asr_vad_pad_ms,
        floor=settings.asr_vad_floor_enabled,
        floor_threshold=settings.asr_vad_floor_threshold,
        floor_max_speech_share=settings.asr_vad_floor_max_speech_share,
    )

    async def decode() -> TranscriptionOutput:
        if not hasattr(provider, "transcribe_runs"):
            out: TranscriptionOutput = await provider.transcribe(
                pcm, language=language, prompt=prompt, should_cancel=should_cancel
            )
            return out
        lid = await chunks.identifier_for(provider)
        planned = await chunks.plan(
            pcm, heard.runs, language=language, lid=lid, should_cancel=should_cancel
        )
        if planned.runs:
            out = await provider.transcribe_runs(
                pcm,
                planned.runs,
                language=planned.language,
                prompt=prompt,
                should_cancel=should_cancel,
                group_seconds=settings.asr_http_group_seconds,
            )
        else:
            out = TranscriptionOutput(
                language=planned.language,
                segments=[],
                metadata=TranscriptionMetadata(
                    model=provider.model_name,
                    vad_seconds_speech=0.0,
                    infer_seconds=0.0,
                    beam_size=1,
                ),
            )
        return out.model_copy(
            update={
                "language": planned.language,
                "language_detected": planned.language_detected,
                "language_probability": planned.language_probability
                if planned.language_detected
                else out.language_probability,
                "diagnostics": out.diagnostics.model_copy(
                    update={
                        "other_language_chunks": planned.other_language_runs,
                        "language_id": planned.language_id,
                    }
                ),
            }
        )

    output = await asyncio.wait_for(decode(), timeout=timeout)
    gated = guards.apply(output, heard.runs)
    output = gated.output
    # Prompt echo removed for every backend; an all-echo transcript files as `no_speech`.
    output = _guarded(output, prompt, job_id=job_id)
    # Runs the first decode lost (and loops) are decoded again without the prompt.
    output = await _covered(
        state,
        output,
        pcm=pcm,
        stereo=stereo,
        prompt=prompt,
        first_frame_offset_ms=first_frame_offset_ms,
        deadline=deadline,
        should_cancel=should_cancel,
        job_id=job_id,
        heard=heard,
        loop_ranges=gated.loop_ranges,
    )
    if heard.stub:
        return output
    return output.model_copy(update={"noise": chunks.nonspeech_regions(pcm, heard.runs)})


def _guarded(
    output: TranscriptionOutput, prompt: str | None, *, job_id: UUID
) -> TranscriptionOutput:
    """Prompt echo removed and recorded in diagnostics; the log gets counts, never words."""
    segments, spans, dropped = guard_segments(output.segments, prompt)
    if not spans:
        return output
    words = sum(s.words for s in spans)
    _prompt_echo_words.add(words)
    if dropped:
        _prompt_echo_segments_dropped.add(dropped)
    logger.info(
        "whisper.prompt_echo_stripped",
        extra={
            "job_id": str(job_id),
            "spans": len(spans),
            "words": words,
            "segments_dropped": dropped,
            "first_start_ms": spans[0].start_ms,
        },
    )
    diagnostics = output.diagnostics.model_copy(
        update={
            "prompt_echo": [*output.diagnostics.prompt_echo, *spans],
            "prompt_echo_segments_dropped": output.diagnostics.prompt_echo_segments_dropped
            + dropped,
        }
    )
    return output.model_copy(update={"segments": segments, "diagnostics": diagnostics})


async def _covered(
    state: WorkerState,
    output: TranscriptionOutput,
    *,
    pcm: np.ndarray,
    stereo: np.ndarray | None,
    prompt: str | None,
    first_frame_offset_ms: int | None,
    deadline: float,
    should_cancel: Any,
    job_id: UUID,
    heard: vad.SpeechRuns | None = None,
    loop_ranges: list[tuple[int, int]] | None = None,
) -> TranscriptionOutput:
    """Measure speech coverage, re-decode lost runs without the prompt, name remaining gaps.

    Never fails the job (a VAD error leaves the transcript as is); cancellation propagates."""
    try:
        if heard is None:
            heard = await asyncio.to_thread(
                vad.speech_runs,
                pcm,
                stereo=stereo,
                floor=settings.asr_vad_floor_enabled,
                floor_threshold=settings.asr_vad_floor_threshold,
                floor_max_speech_share=settings.asr_vad_floor_max_speech_share,
            )
    except Exception as exc:  # noqa: BLE001 — diagnostics must not cost the transcript
        logger.warning(
            "asr.coverage_vad_failed",
            extra={"job_id": str(job_id), "error_class": type(exc).__name__},
        )
        return output
    runs = heard.runs
    segments = list(output.segments)
    spans = list(output.diagnostics.prompt_echo)
    seg_diagnostics = list(output.diagnostics.segments)
    loops = list(loop_ranges or [])
    loop_events: list[LoopEvent] = list(output.diagnostics.loops)
    second_drops: list[DroppedSegment] = []
    failed = output.diagnostics.backend_errors
    outcomes: dict[tuple[int, int], cov.RunOutcome] = {}
    by_cause: dict[str, int] = {}
    chunks = 0
    recovered = 0
    timed_out = False
    prev_end = 0
    second_pass_on = settings.asr_second_pass_enabled and not heard.stub
    for run in runs:
        outcome = cov.RunOutcome(
            run=run,
            echo_removed=cov.echo_words_in(run, spans) > 0,
            other_language=cov.run_language(run, segments) is not None,
            backend_error=any(e.start_ms < run.end_ms and run.start_ms < e.end_ms for e in failed),
        )
        outcomes[(run.start_ms, run.end_ms)] = outcome
        slice_start = max(run.start_ms - settings.asr_vad_pad_ms, prev_end, 0)
        prev_end = run.end_ms
        in_loop: list[tuple[int, int]] = [
            r for r in loops if r[0] < run.end_ms and run.start_ms < r[1]
        ]
        if in_loop:
            cause: str | None = cov.LOOP_CAUSE if second_pass_on else None
            if cause is None:
                loop_events.extend(
                    LoopEvent(start_ms=a, end_ms=b, outcome="second_pass_off") for a, b in in_loop
                )
                for r in in_loop:
                    loops.remove(r)
                continue
        else:
            cause = cov.second_pass_cause(run, segments, spans) if second_pass_on else None
        if cause is None:
            continue

        def loop_outcome(
            result: str, cause: str = cause, in_loop: list[tuple[int, int]] = in_loop
        ) -> None:
            if cause != cov.LOOP_CAUSE:
                return
            for r in in_loop:
                if r in loops:
                    loops.remove(r)
                    loop_events.append(LoopEvent(start_ms=r[0], end_ms=r[1], outcome=result))  # type: ignore[arg-type]

        remaining = deadline - time.monotonic()
        if timed_out or remaining <= 1.0:
            timed_out = True
            by_cause[cov.TIMEOUT_CAUSE] = by_cause.get(cov.TIMEOUT_CAUSE, 0) + 1
            _second_pass_total.add(1, {"cause": cov.TIMEOUT_CAUSE, "outcome": "empty"})
            loop_outcome("second_pass_failed")
            continue
        failed_here = next(
            (e for e in failed if e.start_ms < run.end_ms and run.start_ms < e.end_ms), None
        )
        language = (
            (failed_here.language if failed_here else None)
            or cov.run_language(run, segments)
            or output.language
        )
        chunk = pcm[int(slice_start * 16) : int(run.end_ms * 16)]
        try:
            second = await asyncio.wait_for(
                state.engine.transcribe(
                    chunk,
                    language=language,
                    prompt=None,
                    should_cancel=should_cancel,
                    second_pass=True,
                ),
                timeout=remaining,
            )
        except TimeoutError:
            timed_out = True
            by_cause[cov.TIMEOUT_CAUSE] = by_cause.get(cov.TIMEOUT_CAUSE, 0) + 1
            _second_pass_total.add(1, {"cause": cov.TIMEOUT_CAUSE, "outcome": "empty"})
            loop_outcome("second_pass_failed")
            continue
        except ProviderError as exc:
            logger.warning(
                "asr.second_pass_failed",
                extra={"job_id": str(job_id), "start_ms": run.start_ms, "kind": str(exc.kind)},
            )
            _second_pass_total.add(1, {"cause": cause, "outcome": "empty"})
            loop_outcome("second_pass_failed")
            continue
        chunks += 1
        by_cause[cause] = by_cause.get(cause, 0) + 1
        fresh = cov.shift(second.segments, slice_start)
        # Second decode goes through the same gates.
        fresh_diags = [
            d.model_copy(
                update={"start_ms": d.start_ms + slice_start, "end_ms": d.end_ms + slice_start}
            )
            for d in second.diagnostics.segments
        ]
        regated = guards.apply(
            second.model_copy(
                update={
                    "segments": fresh,
                    "diagnostics": Diagnostics(segments=fresh_diags),
                }
            ),
            runs,
        )
        fresh = list(regated.output.segments)
        second_drops.extend(regated.output.diagnostics.dropped_segments)
        # Echo guard applies even to the prompt-free decode.
        fresh, fresh_spans, _ = guard_segments(fresh, prompt)
        first_words = cov.words_in(run, segments)
        second_words = cov.words_in(run, fresh)
        outcome.second_pass_words = second_words
        if second_words > first_words and cov.confident(fresh):
            segments = cov.splice(segments, slice_start, run.end_ms, fresh)
            spans.extend(fresh_spans)
            # Spliced decode's diagnostics, on the recording's clock.
            seg_diagnostics.extend(
                d.model_copy(
                    update={
                        "start_ms": d.start_ms + slice_start,
                        "end_ms": d.end_ms + slice_start,
                        "second_pass": True,
                    }
                )
                for d in second.diagnostics.segments
            )
            recovered += second_words - first_words
            _second_pass_total.add(1, {"cause": cause, "outcome": "recovered"})
            loop_outcome("recovered")
        else:
            _second_pass_total.add(1, {"cause": cause, "outcome": "empty"})
            loop_outcome("kept_truncated")

    coverage = cov.measure(
        runs,
        segments,
        outcomes,
        first_frame_offset_ms=first_frame_offset_ms,
        stub=heard.stub,
    )
    _speech_ms.add(coverage.speech_ms)
    for gap in coverage.gaps:
        _uncovered_speech_ms.add(gap.end_ms - gap.start_ms, {"cause": gap.cause})
    _coverage_share.record(coverage.share)
    logger.info(
        "asr.coverage",
        extra={
            "job_id": str(job_id),
            "speech_ms": coverage.speech_ms,
            "transcribed_ms": coverage.transcribed_ms,
            "first_speech_ms": coverage.first_speech_ms,
            "first_segment_ms": coverage.first_segment_ms,
            "gaps": len(coverage.gaps),
            "floor_pass": heard.floor_used,
            "second_pass_chunks": chunks,
            "recovered_words": recovered,
        },
    )
    diagnostics = output.diagnostics.model_copy(
        update={
            "prompt_echo": spans,
            "coverage": coverage,
            "second_pass": SecondPass(chunks=chunks, recovered_words=recovered, by_cause=by_cause),
            "segments": sorted(seg_diagnostics, key=lambda d: (d.start_ms, d.second_pass)),
            "loops": [
                *loop_events,
                # Loops no second pass reached: kept as truncated.
                *(LoopEvent(start_ms=a, end_ms=b, outcome="kept_truncated") for a, b in loops),
            ],
            "dropped_segments": [*output.diagnostics.dropped_segments, *second_drops],
        }
    )
    metadata = output.metadata.model_copy(update={"coverage_share": round(coverage.share, 4)})
    return output.model_copy(
        update={"segments": segments, "diagnostics": diagnostics, "metadata": metadata}
    )


def _apply_diarization(
    output: TranscriptionOutput, diar: OfflineDiarization
) -> TranscriptionOutput:
    """Speaker-attribute per word (segments span turns), splitting segments at speaker changes.

    Unattributable words stay ``speaker=None``; ``speakers`` is the first-appearance
    roster of labels that reached a segment.
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
            "overlap_ms": list(getattr(diar, "overlap_ms", []) or []),
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
    """Roster stats: clusterer counts, speech per speaker, unlabelled speech."""
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


# Minimum local-side speech before the sole local speaker is named after the owner.
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
    """Diarize: channel-aware for mic/system, else mono; channel-path bugs fall back to mono."""
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
            # Engine down: the mono fallback would hit the same dead endpoint.
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
    """Shadow diarizer on the same audio; counts only, failures swallowed."""
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
    # A piece holding a smoothed label is marked uncertain.
    smoothed = [r != lab and lab is not None for r, lab in zip(raw, labels, strict=True)]
    if all(label == labels[0] for label in labels):
        return [seg.model_copy(update={"speaker": labels[0], "speaker_uncertain": any(smoothed)})]

    # Word texts carry their punctuation; join the way the original text was.
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
    # Pass 1: None runs take the label of agreeing (or sole) neighbours.
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


# ── Re-labelling (``task="rediarize"``) ─────────────────────────────────


def revision_key(tenant_id: UUID, job_id: UUID, rev: int) -> str:
    """Object key a re-run writes; deterministic per ``rev`` so a redelivery overwrites it."""
    return f"{tenant_id}/{job_id}.r{rev}.json.enc"


def key_from_uri(uri: str) -> str:
    """``minio://bucket/<key>`` → ``<key>``."""
    return uri.split("://", 1)[-1].split("/", 1)[1]


# A name follows its speaker only when the new label holds this share of the old one's speech.
NAME_CARRY_MIN_SHARE = 0.6


async def _rediarize_one(state: WorkerState, payload: JobEnqueuePayload) -> None:
    """Re-label a complete job's stored words (no ASR pass); ``status`` stays ``complete``.

    Idempotent under redelivery: claim conditional on the FROM revision, key
    deterministic per ``target_rev``, final swap re-checks under a row lock.
    """
    tenant_id, job_id = payload.tenant_id, payload.job_id
    target_rev = payload.target_rev
    request_id = payload.rediarize_id
    if request_id is None:
        raise _NonRetryableError(str(JobErrorKind.BAD_PAYLOAD), "rediarize without rediarize_id")
    if target_rev is None or target_rev < 2:
        await _mark_rediarize_failed(
            state, tenant_id, job_id, request_id=request_id, kind=str(JobErrorKind.BAD_PAYLOAD)
        )
        raise _NonRetryableError(str(JobErrorKind.BAD_PAYLOAD), "rediarize without a target_rev")
    t0 = time.monotonic()

    # Claim is per request id; `running` is claimable (redelivery after a dead worker).
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
    # Layout travels on the job's capture context.
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
                return
            # Names as of now (a rename during the run counts).
            names = _parse_names(row["speaker_names"])
            carried = {mapping[old]: name for old, name in names.items() if old in mapping}
            # Provenance follows its name; "cleared" follows the speaker.
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
                    speaker_name_sources = $6::jsonb,
                    -- The speaker numbers changed; the rest is carried over.
                    quality = CASE WHEN quality IS NULL THEN NULL
                                   ELSE quality || $7::jsonb END
                WHERE id = $1
                """,
                job_id,
                f"minio://{state.transcript_store.bucket}/{new_key}",
                target_rev,
                json.dumps(relabelled.metadata.model_dump(mode="json")),
                json.dumps(carried),
                json.dumps(carried_sources),
                json.dumps(quality.speaker_numbers(relabelled)),
            )
            superseded = row["previous_result_storage_uri"]
    except Exception as exc:  # noqa: BLE001
        raise await fail(JobErrorKind.DB_UNAVAILABLE, str(exc)) from exc

    # Keep one previous revision; best effort (erasure lists by prefix).
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
    """Old label → new label where a name may follow (both lists hold the same words).

    Needs :data:`NAME_CARRY_MIN_SHARE` in both directions; a merge names nobody.
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
    """(duration_ms, speaker) per word; a wordless segment counts as one word."""
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
    """Remote diarizer failed: log, mark ``diarization_status='failed'``, keep the transcript."""
    if kind is JobErrorKind.DIARIZATION_FAILED:
        # Count call failures too: the alert must fire for an endpoint that
        # answers but cannot diarize.
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
    """Fail this request's re-run only; a no-match write is neither counted nor audited."""
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
    """Build ``die(kind, detail)``: returns the exception (so ``raise ... from exc`` chains).

    Terminal kinds are written to the row here; retryable kinds are not.
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
    """`should_cancel` for the engine, rate-limited to one query a second."""
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
    """Terminal-failure path; every failure funnels through here."""
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
