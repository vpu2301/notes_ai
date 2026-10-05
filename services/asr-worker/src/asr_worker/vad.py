"""Silero VAD wrapper; speech runs capped at 30 s (Whisper's audio context)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    start_ms: int
    end_ms: int
    # Heard only by the floor pass.
    floor_only: bool = False


@dataclass(frozen=True, slots=True)
class SpeechRuns:
    """What VAD heard in a recording."""

    runs: list[SpeechSegment]
    # The floor pass ran.
    floor_used: bool = False
    # Silero is not installed: the whole file is one run.
    stub: bool = False


# Silero's own default; the floor pass lowers it.
DEFAULT_THRESHOLD = 0.5
# Below this, non-speech is silence, not a quiet voice under a louder one.
FLOOR_MIN_NON_SPEECH_DBFS = -45.0
_MERGE_GAP_MS = 500
_MAX_RUN_MS = 30_000


_model: object | None = None
_get_speech_timestamps: object | None = None


def _ensure_loaded() -> None:
    global _model, _get_speech_timestamps
    if _model is not None:
        return
    try:
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad

        _model = load_silero_vad()
        _get_speech_timestamps = get_speech_timestamps
        torch.set_grad_enabled(False)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "vad.silero_unavailable",
            extra={"error": str(exc), "error_class": type(exc).__name__},
        )
        _model = "stub"
        _get_speech_timestamps = "stub"


def is_stub() -> bool:
    _ensure_loaded()
    return _model == "stub"


def _silero_runs(
    audio_pcm: np.ndarray, sr: int, threshold: float = DEFAULT_THRESHOLD
) -> list[SpeechSegment]:
    """Silero's speech regions, runs < 500 ms apart merged, not capped."""
    import torch

    audio_tensor = torch.from_numpy(np.ascontiguousarray(audio_pcm, dtype=np.float32))
    ts = _get_speech_timestamps(  # type: ignore[misc,operator]
        audio_tensor,
        _model,
        sampling_rate=sr,
        threshold=threshold,
        min_speech_duration_ms=250,
        min_silence_duration_ms=500,
        return_seconds=False,
    )
    # ts is a list of {"start": int_samples, "end": int_samples}.
    out: list[SpeechSegment] = []
    for entry in ts:
        start_ms = int(entry["start"] / sr * 1000)
        end_ms = int(entry["end"] / sr * 1000)
        # Concatenate segments < 500 ms apart for fewer Whisper calls.
        if out and start_ms - out[-1].end_ms < _MERGE_GAP_MS:
            out[-1] = SpeechSegment(out[-1].start_ms, end_ms)
        else:
            out.append(SpeechSegment(start_ms, end_ms))
    return out


def pad_runs(runs: list[SpeechSegment], pad_ms: int) -> list[SpeechSegment]:
    """Start every run ``pad_ms`` earlier, never before 0 or inside the previous run."""
    if pad_ms <= 0:
        return list(runs)
    out: list[SpeechSegment] = []
    prev_end = 0
    for r in runs:
        start = max(r.start_ms - pad_ms, prev_end, 0)
        out.append(SpeechSegment(min(start, r.start_ms), r.end_ms, r.floor_only))
        prev_end = r.end_ms
    return out


def cap_runs(runs: list[SpeechSegment]) -> list[SpeechSegment]:
    """Split runs into pieces of at most 30 s — Whisper's audio context."""
    capped: list[SpeechSegment] = []
    for s in runs:
        cursor = s.start_ms
        while cursor < s.end_ms:
            end = min(cursor + _MAX_RUN_MS, s.end_ms)
            capped.append(SpeechSegment(cursor, end, s.floor_only))
            cursor = end
    return capped


def union_runs(ordinary: list[SpeechSegment], floor: list[SpeechSegment]) -> list[SpeechSegment]:
    """Both passes' runs merged; ``floor_only`` when no ordinary run is part of it."""
    tagged = sorted(
        [(r.start_ms, r.end_ms, False) for r in ordinary]
        + [(r.start_ms, r.end_ms, True) for r in floor]
    )
    out: list[SpeechSegment] = []
    for start, end, from_floor in tagged:
        if out and start - out[-1].end_ms < _MERGE_GAP_MS:
            last = out[-1]
            out[-1] = SpeechSegment(
                last.start_ms, max(last.end_ms, end), last.floor_only and from_floor
            )
        else:
            out.append(SpeechSegment(start, end, from_floor))
    return out


def non_speech_dbfs(audio_pcm: np.ndarray, runs: list[SpeechSegment], sr: int) -> float | None:
    """RMS dBFS of everything VAD did not call speech; None when all is speech."""
    mask = np.ones(audio_pcm.shape[0], dtype=bool)
    per_ms = sr / 1000
    for r in runs:
        mask[int(r.start_ms * per_ms) : int(r.end_ms * per_ms)] = False
    rest = audio_pcm[mask]
    if rest.size == 0:
        return None
    rms = float(np.sqrt(np.mean(np.square(rest, dtype=np.float64))))
    return float(20.0 * np.log10(max(rms, 1e-10)))


def floor_applies(
    audio_pcm: np.ndarray, runs: list[SpeechSegment], sr: int, *, max_speech_share: float
) -> bool:
    """Little speech heard, but the rest is not silence either."""
    duration_ms = len(audio_pcm) / sr * 1000
    if duration_ms <= 0:
        return False
    speech_ms = sum(r.end_ms - r.start_ms for r in runs)
    if speech_ms / duration_ms >= max_speech_share:
        return False
    level = non_speech_dbfs(audio_pcm, runs, sr)
    return level is not None and level > FLOOR_MIN_NON_SPEECH_DBFS


def _channels(stereo: np.ndarray | None) -> list[np.ndarray]:
    if stereo is None or stereo.ndim != 2:
        return []
    scale = 1.0 / 32768.0 if stereo.dtype == np.int16 else 1.0
    return [stereo[:, k].astype(np.float32) * scale for k in range(stereo.shape[1])]


def speech_runs(
    audio_pcm: np.ndarray,
    *,
    stereo: np.ndarray | None = None,
    sr: int = 16_000,
    pad_ms: int = 0,
    floor: bool = False,
    floor_threshold: float = 0.35,
    floor_max_speech_share: float = 0.2,
) -> SpeechRuns:
    """VAD for a whole recording: ordinary pass, floor pass (per channel), union, pad, cap."""
    _ensure_loaded()
    if _model == "stub":
        duration_ms = int(len(audio_pcm) / sr * 1000)
        return SpeechRuns(runs=[SpeechSegment(0, max(1, duration_ms))], stub=True)
    ordinary = _silero_runs(audio_pcm, sr)
    runs = ordinary
    floor_used = False
    if floor and floor_applies(audio_pcm, ordinary, sr, max_speech_share=floor_max_speech_share):
        floor_used = True
        sources = _channels(stereo) or [audio_pcm]
        found: list[SpeechSegment] = []
        for channel in sources:
            found.extend(_silero_runs(channel, sr, threshold=floor_threshold))
        runs = union_runs(ordinary, found)
        logger.info(
            "vad.floor_pass",
            extra={
                "channels": len(sources),
                "ordinary_runs": len(ordinary),
                "floor_only_runs": sum(1 for r in runs if r.floor_only),
            },
        )
    runs = cap_runs(pad_runs(runs, pad_ms))
    if not runs:
        logger.info("vad.no_speech", extra={"audio_seconds": round(len(audio_pcm) / sr, 1)})
    return SpeechRuns(runs=runs, floor_used=floor_used)


def detect_speech(
    audio_pcm: np.ndarray, sr: int = 16_000, *, pad_ms: int = 0
) -> list[SpeechSegment]:
    """Speech regions; without Silero (dev fallback) one segment covers the whole audio."""
    _ensure_loaded()
    if _model == "stub":
        duration_ms = int(len(audio_pcm) / sr * 1000)
        return [SpeechSegment(0, max(1, duration_ms))]
    capped = cap_runs(pad_runs(_silero_runs(audio_pcm, sr), pad_ms))
    # No speech is an answer: Whisper given silence plus a prompt writes the prompt.
    if not capped:
        logger.info(
            "vad.no_speech",
            extra={"audio_seconds": round(len(audio_pcm) / sr, 1)},
        )
    return capped
