"""The diar-server wire format, imported by both client and server so they cannot drift.

Request: 16 kHz audio (lossless FLAC or WAV), hints, roster policy. Reply: labelled spans, overlaps, counts.
Embeddings are biometric data and have no field here.
"""

from __future__ import annotations

import io
import wave
from typing import Any

import numpy as np

from .attribution import UNKNOWN, SpeakerSegment
from .offline import ClusterStats, OfflineDiarization, OfflineDiarizationConfig
from .protocol import DiarizationHints
from .roster import RosterOutcome

SAMPLE_RATE_HZ = 16_000
DIARIZATIONS_PATH = "/v1/audio/diarizations"
HEALTH_PATH = "/health"
# Read first by the server: a managed gateway consumes `Authorization` itself.
TOKEN_HEADER = "X-MDX-Diar-Token"
# Bumped when a field changes meaning; an unknown version is refused, not guessed.
WIRE_VERSION = 1


def encode_audio(pcm: np.ndarray) -> tuple[str, bytes]:
    """(filename, bytes) for the multipart upload — FLAC, else WAV."""
    samples = np.ascontiguousarray(pcm, dtype=np.float32)
    try:
        import soundfile  # noqa: PLC0415 — optional, checked at call time
    except ImportError:
        return "audio.wav", _wav_bytes(samples)
    buffer = io.BytesIO()
    soundfile.write(buffer, samples, SAMPLE_RATE_HZ, format="FLAC", subtype="PCM_16")
    return "audio.flac", buffer.getvalue()


def _wav_bytes(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE_HZ)
        handle.writeframes(pcm16.tobytes())
    return buffer.getvalue()


def audio_seconds(data: bytes) -> float:
    """Duration from the header alone, read before decoding (a compressible upload can decode to gigabytes)."""
    try:
        import soundfile  # noqa: PLC0415
    except ImportError:
        with wave.open(io.BytesIO(data), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate() or SAMPLE_RATE_HZ)
    info = soundfile.info(io.BytesIO(data))
    return float(info.frames) / float(info.samplerate or SAMPLE_RATE_HZ)


def decode_audio(data: bytes) -> np.ndarray:
    """Server side: uploaded FLAC/WAV → mono float32 PCM at 16 kHz."""
    try:
        import soundfile  # noqa: PLC0415 — the server image always has it
    except ImportError:
        return _wav_pcm(data)
    samples, rate = soundfile.read(io.BytesIO(data), dtype="float32", always_2d=True)
    if rate != SAMPLE_RATE_HZ:
        raise ValueError(f"audio must be {SAMPLE_RATE_HZ} Hz mono, got {rate} Hz")
    return np.asarray(samples[:, 0], dtype=np.float32)


def _wav_pcm(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE_HZ:
            raise ValueError(f"audio must be {SAMPLE_RATE_HZ} Hz mono")
        if handle.getsampwidth() != 2:
            raise ValueError("WAV must be 16-bit")
        frames = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()
    pcm16 = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        pcm16 = pcm16.reshape(-1, channels)[:, 0]
    return (pcm16.astype(np.float32) / 32768.0).copy()


def hint_fields(hints: DiarizationHints) -> dict[str, str]:
    """Hints as multipart form fields (only the ones a person gave)."""
    return {
        name: str(value)
        for name, value in (
            ("num_speakers", hints.num_speakers),
            ("min_speakers", hints.min_speakers),
            ("max_speakers", hints.max_speakers),
        )
        if value is not None
    }


def to_payload(diar: OfflineDiarization, *, model_id: str, seconds: float) -> dict[str, Any]:
    """``OfflineDiarization`` → JSON body, labels and numbers only.

    Segments carry DISPLAY labels, so ``display_names`` is the identity map EXCEPT ``UNKNOWN``: an entry for it
    would turn unattributed evidence into a speaker called UNKNOWN with a turn of its own.
    """
    roster = diar.roster
    stats = diar.stats
    segments = diar.segments
    return {
        "wire_version": WIRE_VERSION,
        "model_id": model_id,
        "engine": diar.engine,
        "engine_version": diar.engine_version,
        "seconds": round(seconds, 3),
        "duration_ms": diar.duration_ms,
        "segments": [
            {
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "speaker": s.label,
                "confidence": round(float(s.confidence), 4),
            }
            for s in segments
        ],
        "display_names": {s.label: s.label for s in segments if s.label != UNKNOWN},
        "overlap_ms": [[a, b] for a, b in diar.overlap_ms],
        "stats": {
            "chunks": stats.chunks,
            "clusters_raw": stats.clusters_raw,
            "clusters_after_merge": stats.clusters_after_merge,
            "clusters_dropped": stats.clusters_dropped,
        },
        "roster": {
            "speakers_kept": roster.speakers_kept if roster else 0,
            "speakers_dissolved": roster.speakers_dissolved if roster else 0,
            "count_confidence": roster.count_confidence if roster else "high",
            "overlap_share": roster.overlap_share if roster else 0.0,
            "reasons": list(roster.reasons) if roster else [],
        },
    }


class WirePayloadError(ValueError):
    """The server answered with something this client cannot read."""


def from_payload(
    payload: Any, *, hints: DiarizationHints, config: OfflineDiarizationConfig
) -> OfflineDiarization:
    """JSON body → the structure the worker's word attribution consumes."""
    if not isinstance(payload, dict):
        raise WirePayloadError("diarization reply is not an object")
    version = payload.get("wire_version")
    if version != WIRE_VERSION:
        raise WirePayloadError(
            f"unsupported wire_version {version!r} (this client reads {WIRE_VERSION})"
        )
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        raise WirePayloadError("diarization reply carries no segments[]")
    segments = [_segment(item) for item in raw_segments]
    stats = payload.get("stats") or {}
    roster = payload.get("roster") or {}
    display = payload.get("display_names") or {}
    if not isinstance(display, dict):
        raise WirePayloadError("display_names must be an object")
    # A server that names UNKNOWN must not make it a speaker here (see `to_payload`).
    display = {k: v for k, v in display.items() if k != UNKNOWN}
    return OfflineDiarization(
        segments=segments,
        display_names={str(k): str(v) for k, v in display.items()},
        duration_ms=_int(payload.get("duration_ms"), "duration_ms"),
        config=config,
        stats=ClusterStats(
            chunks=_int(stats.get("chunks", len(segments)), "stats.chunks"),
            clusters_raw=_int(stats.get("clusters_raw", 0), "stats.clusters_raw"),
            clusters_after_merge=_int(
                stats.get("clusters_after_merge", 0), "stats.clusters_after_merge"
            ),
            clusters_dropped=_int(stats.get("clusters_dropped", 0), "stats.clusters_dropped"),
        ),
        engine=str(payload.get("engine") or "unknown"),
        engine_version=str(payload.get("engine_version") or "unknown"),
        hints=hints,
        roster=RosterOutcome(
            segments=segments,
            speakers_kept=_int(roster.get("speakers_kept", 0), "roster.speakers_kept"),
            speakers_dissolved=_int(
                roster.get("speakers_dissolved", 0), "roster.speakers_dissolved"
            ),
            count_confidence="low" if roster.get("count_confidence") == "low" else "high",
            overlap_share=float(roster.get("overlap_share") or 0.0),
            reasons=tuple(str(r) for r in roster.get("reasons") or ()),
        ),
        overlap_ms=[
            (_int(span[0], "overlap_ms"), _int(span[1], "overlap_ms"))
            for span in payload.get("overlap_ms") or []
            if isinstance(span, (list, tuple)) and len(span) == 2
        ],
    )


def _segment(item: Any) -> SpeakerSegment:
    if not isinstance(item, dict):
        raise WirePayloadError("segment is not an object")
    speaker = item.get("speaker")
    if not isinstance(speaker, str) or not speaker:
        raise WirePayloadError("segment without a speaker label")
    confidence = item.get("confidence", 1.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise WirePayloadError("segment confidence is not a number") from exc
    return SpeakerSegment(
        start_ms=_int(item.get("start_ms"), "segment.start_ms"),
        end_ms=_int(item.get("end_ms"), "segment.end_ms"),
        label=speaker,
        confidence=max(0.0, min(1.0, confidence)),
    )


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WirePayloadError(f"{field} is not a number")
    return int(value)
