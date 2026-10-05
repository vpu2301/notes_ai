"""Session finalization: flush windower, package + upload audio, persist transcript.

Idempotent: a second finalize on a finalized session short-circuits.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import struct
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from audit import AuditWriter, Severity
from crypto import Envelope
from db import tenant_connection
from storage import EncryptedObjectStore
from storage.object_store import ObjectHeader, header_metadata_for_row

from .. import audit_kinds
from ..config import settings
from ..domain import repository
from ..session.manager import SessionContext
from ..session.state import SessionState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    audio_file_id: UUID | None
    truncated: bool
    transcript_segments: int
    # Reported because the ring buffer is closed by the time this returns.
    duration_ms: int
    # Persisted (post-NLP) transcript for the conversation draft path.
    transcript: list[dict[str, Any]] | None = None


async def finalize_session(
    *,
    ctx: SessionContext,
    app_pool: object,  # asyncpg.Pool — Any to avoid an import cycle
    audit_writer: AuditWriter,
    audio_store: EncryptedObjectStore,
    envelope: Envelope,
    reason: str = "normal",
    purge_audio: bool = False,
    nlp_client: Any | None = None,
) -> FinalizeResult:
    """Idempotently finalize a session.

    ``purge_audio`` (ADR-0018): audio never reaches object storage and the
    in-memory PCM is zeroed before the buffer is freed.
    """
    pcm = _flush_buffer(ctx)
    pcm_bytes_len = pcm.nbytes
    duration_ms = pcm.shape[0] * 1000 // 16_000

    # Ring wrapped: audio_file shorter than buffer.total_ms.
    truncated = False
    if ctx.buffer is not None:
        truncated = ctx.buffer.total_ms > duration_ms

    audio_file_id: UUID | None = None
    object_store_disabled = audio_store.is_disabled
    skip_persist = object_store_disabled or purge_audio
    if pcm_bytes_len > 0 and not skip_persist:
        wav_bytes = _pcm_to_wav(pcm)
        audio_file_id = uuid4()
        storage_key = f"dictations/{ctx.tenant_id}/{ctx.session_id}.wav.enc"
        try:
            header = await audio_store.put(
                key=storage_key,
                plaintext=wav_bytes,
                tenant_id=ctx.tenant_id,
                aad=ctx.session_id.bytes,
            )
        except Exception as exc:  # noqa: BLE001
            from storage import ObjectStoreDisabledError

            if isinstance(exc, ObjectStoreDisabledError):
                # Race: env flipped between is_disabled check and put.
                object_store_disabled = True
                audio_file_id = None
            else:
                raise

        if not object_store_disabled:
            async with tenant_connection(app_pool, ctx.tenant_id) as conn:
                await conn.execute(
                    """
                    INSERT INTO audio_files
                        (id, tenant_id, uploader_sub, mime_type, size_bytes,
                         duration_ms, sha256, envelope_metadata, storage_uri, status)
                    VALUES ($1,$2,$3,'audio/wav',$4,$5,$6,$7::jsonb,$8,'stored')
                    """,
                    audio_file_id,
                    ctx.tenant_id,
                    ctx.user_id,
                    len(wav_bytes),
                    duration_ms,
                    hashlib.sha256(wav_bytes).digest(),
                    # asyncpg binds jsonb from a JSON string, not a dict.
                    json.dumps(_header_to_json(header)),
                    f"minio://{audio_store.bucket}/{storage_key}",
                )

        await audit_writer.write_event(
            tenant_id=ctx.tenant_id,
            kind=audit_kinds.AUDIO_UPLOADED,
            actor_sub=ctx.user_id,
            target_kind="audio",
            target_id=str(audio_file_id),
            payload={
                "session_id": str(ctx.session_id),
                "duration_ms": duration_ms,
                "size_bytes": len(wav_bytes),
            },
            severity=Severity.INFO,
        )

    if truncated:
        await audit_writer.write_event(
            tenant_id=ctx.tenant_id,
            kind=audit_kinds.AUDIO_TRUNCATED,
            actor_sub=ctx.user_id,
            target_kind="dictation_session",
            target_id=str(ctx.session_id),
            payload={
                "observed_ms": ctx.buffer.total_ms if ctx.buffer else 0,
                "stored_ms": duration_ms,
            },
            severity=Severity.WARN,
        )

    # Commit still-provisional words now (no inference) or lose them.
    _flush_provisional_tail(ctx)

    transcript_jsonb = _transcript_to_jsonb(ctx)

    # NLP failure degrades to the raw transcript, never blocks finalize.
    if nlp_client is not None and transcript_jsonb:
        enriched = await _enrich_with_nlp(ctx, transcript_jsonb, nlp_client)
        if enriched is not None:
            transcript_jsonb = enriched
        else:
            await audit_writer.write_event(
                tenant_id=ctx.tenant_id,
                kind=audit_kinds.NLP_TIMEOUT,
                actor_sub=ctx.user_id,
                target_kind="dictation_session",
                target_id=str(ctx.session_id),
                payload={"segments": len(transcript_jsonb), "mode": ctx.mode},
                severity=Severity.WARN,
            )

    # VAD-derived speech time for conversation; dictation keeps the approximation.
    total_speech_ms = duration_ms
    if ctx.mode == "conversation" and ctx.diarization is not None:
        total_speech_ms = sum(s.end_ms - s.start_ms for s in ctx.diarization.segments)

    async with tenant_connection(app_pool, ctx.tenant_id) as conn:
        await repository.write_finalized(
            conn,
            session_id=ctx.session_id,
            audio_file_id=audio_file_id,
            transcript_jsonb=transcript_jsonb,
            total_audio_ms=duration_ms,
            total_speech_ms=total_speech_ms,
            avg_partial_latency_ms=_avg(ctx.partial_latencies_ms),
            avg_final_latency_ms=_avg(ctx.final_latencies_ms),
            rtf=None,
            network_drop_count=ctx.network_drop_count,
            truncated=truncated,
        )

    await audit_writer.write_event(
        tenant_id=ctx.tenant_id,
        kind=audit_kinds.SESSION_FINALIZED,
        actor_sub=ctx.user_id,
        target_kind="dictation_session",
        target_id=str(ctx.session_id),
        payload={
            "reason": reason,
            "duration_ms": duration_ms,
            "audio_file_id": str(audio_file_id) if audio_file_id else None,
            "segments": len(transcript_jsonb),
            "truncated": truncated,
        },
        severity=Severity.INFO,
    )

    # ADR-0018: zero the decrypted PCM so no plaintext audio lingers.
    if skip_persist:
        if pcm.size:
            pcm[:] = 0.0
        logger.info(
            "dictation.audio.purged session_id=%s reason=%s purge_flag=%s store_disabled=%s",
            ctx.session_id,
            reason,
            purge_audio,
            object_store_disabled,
        )

    if ctx.buffer is not None:
        ctx.buffer.close()
        ctx.buffer = None
    ctx.decoder = None
    ctx.state = SessionState.FINALIZED

    return FinalizeResult(
        audio_file_id=audio_file_id,
        truncated=truncated,
        transcript_segments=len(transcript_jsonb),
        duration_ms=duration_ms,
        transcript=transcript_jsonb,
    )


def _flush_buffer(ctx: SessionContext) -> np.ndarray:
    """Read the session buffer as a contiguous float32 ndarray (most-recent ring length if wrapped)."""
    if ctx.buffer is None:
        return np.zeros(0, dtype=np.float32)
    total = ctx.buffer.total_samples
    ring_samples = ctx.buffer._ring_samples  # private but stable
    start = max(0, total - ring_samples)
    samples: np.ndarray = ctx.buffer.read(start, total)
    return samples


def _pcm_to_wav(pcm: np.ndarray) -> bytes:
    """Wrap a float32 mono 16 kHz PCM array in a minimal WAV container."""
    samples = np.clip(pcm, -1.0, 1.0)
    int16 = (samples * 32767.0).astype(np.int16)
    raw = int16.tobytes()
    buf = io.BytesIO()
    # RIFF/WAVE header for 16-bit PCM mono 16 kHz.
    sample_rate = 16_000
    channels = 1
    bits = 16
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + len(raw)))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))  # PCM
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", bits))
    buf.write(b"data")
    buf.write(struct.pack("<I", len(raw)))
    buf.write(raw)
    return buf.getvalue()


def _flush_provisional_tail(ctx: SessionContext) -> None:
    """Promote the windower's remaining provisional words; best-effort, never raises."""
    windower = getattr(ctx, "windower", None)
    if windower is None:
        return
    try:
        tail = windower.flush_provisional()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "finalize.provisional_flush_failed",
            extra={"session_id": str(ctx.session_id), "error_class": type(exc).__name__},
        )
        return
    if not tail:
        return
    ctx.finalized_segments.extend(tail)
    logger.info(
        "finalize.provisional_flushed",
        extra={
            "session_id": str(ctx.session_id),
            "segments": len(tail),
            "words": sum(len(s.words or []) for s in tail),
        },
    )


def _transcript_to_jsonb(ctx: SessionContext) -> list[dict[str, Any]]:
    """Project finalized_segments → JSON-safe segment dicts.

    Conversation mode adds ``id``, ``speaker``/``speaker_confidence`` and
    ``speaker_name``; UNKNOWN and null labels survive into persistence.
    """
    conversation = ctx.mode == "conversation" and ctx.diarization is not None
    mapping: dict[str, str] = {}
    if conversation and ctx.speaker_naming is not None:
        mapping = dict(ctx.speaker_naming.current.mapping)

    out: list[dict[str, Any]] = []
    for seg in ctx.finalized_segments:
        doc: dict[str, Any] = {
            "text": seg.text,
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "avg_confidence": float(seg.avg_confidence),
            "words": [
                {
                    "text": w.text,
                    "start_ms": w.start_ms,
                    "end_ms": w.end_ms,
                    "probability": float(w.probability),
                }
                for w in (seg.words or [])
            ],
            "voice_command": None,  # filled by the NLP pass
        }
        if conversation:
            assert ctx.diarization is not None
            doc["id"] = str(uuid4())
            speaker, conf = ctx.diarization.attribute(int(seg.start_ms), int(seg.end_ms))
            doc["speaker"] = speaker
            doc["speaker_confidence"] = conf
            doc["speaker_name"] = mapping.get(speaker) if speaker else None
            for w, w_doc in zip(seg.words or [], doc["words"], strict=True):
                w_speaker, w_conf = ctx.diarization.attribute(int(w.start_ms), int(w.end_ms))
                w_doc["speaker"] = w_speaker
                w_doc["speaker_confidence"] = w_conf
        out.append(doc)
    return out


async def _enrich_with_nlp(
    ctx: SessionContext,
    transcript: list[dict[str, Any]],
    nlp_client: Any,
) -> list[dict[str, Any]] | None:
    """One batch NLP call; None on failure (caller keeps raw).

    Conversation disables voice_commands server-side so another
    participant's speech can never fire an editing operation.
    """
    payload = [
        {
            "text": seg["text"],
            "words": [
                {
                    "text": w["text"],
                    "start_s": w["start_ms"] / 1000.0,
                    "end_s": w["end_ms"] / 1000.0,
                    "probability": w["probability"],
                }
                for w in seg["words"]
            ],
        }
        for seg in transcript
    ]
    stages_disabled = ["voice_commands"] if ctx.mode == "conversation" else None
    resp = await nlp_client.process_segments_batch(
        segments=payload,
        language=ctx.language,
        stages_disabled=stages_disabled,
        bearer=ctx.bearer,
        timeout=settings.finalize_nlp_timeout_seconds,
    )
    if resp is None or len(resp.get("segments", [])) != len(transcript):
        return None
    enriched: list[dict[str, Any]] = []
    for seg, nlp_seg in zip(transcript, resp["segments"], strict=True):
        doc = dict(seg)
        text = str(nlp_seg.get("text", "")).strip()
        if text:
            doc["text"] = text
        commands = list(nlp_seg.get("voice_commands", []))
        operations = list(nlp_seg.get("operations", []))
        if ctx.mode == "conversation" and operations:
            # Defence in depth: stage was disabled; drop loudly.
            logger.error(
                "nlp.operations_in_conversation_mode_dropped",
                extra={"session_id": str(ctx.session_id), "count": len(operations)},
            )
            commands, operations = [], []
        if commands or operations:
            doc["voice_command"] = {"voice_commands": commands, "operations": operations}
        enriched.append(doc)
    return enriched


def _header_to_json(header: ObjectHeader) -> dict[str, str | int]:
    return header_metadata_for_row(header)


def _avg(xs: list[int]) -> int | None:
    return int(sum(xs) / len(xs)) if xs else None
