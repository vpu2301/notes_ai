"""Cheap energy-based VAD for the committer's silence-boundary signal (no Silero per window)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE_HZ: int = 16_000
FRAME_MS: int = 20
SAMPLES_PER_FRAME: int = SAMPLE_RATE_HZ * FRAME_MS // 1000


@dataclass(frozen=True, slots=True)
class VadConfig:
    energy_threshold: float = 0.005  # normalised RMS
    # 240 ms: natural pauses run ~200-450 ms, so 500 ms never fired and nothing committed.
    min_silence_frames: int = 12
    smooth_frames: int = 3


_DEFAULT_VAD_CONFIG = VadConfig()


def last_silence_boundary_ms(
    pcm: np.ndarray, *, end_ms: int, config: VadConfig = _DEFAULT_VAD_CONFIG
) -> int | None:
    """Most recent speech→silence boundary in ``pcm`` (session clock, ``end_ms`` = end of pcm), or None."""
    if pcm.size < SAMPLES_PER_FRAME:
        return None
    n_frames = pcm.size // SAMPLES_PER_FRAME
    frames = pcm[: n_frames * SAMPLES_PER_FRAME].reshape(n_frames, SAMPLES_PER_FRAME)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    is_silence = (rms < config.energy_threshold).astype(np.int8)

    run = 0
    boundary_frame: int | None = None
    for i in range(n_frames - 1, -1, -1):
        if is_silence[i]:
            run += 1
            if run >= config.min_silence_frames:
                boundary_frame = i  # start of the silence run
                break
        else:
            run = 0
    if boundary_frame is None:
        return None
    # Convert frame index to ms within pcm.
    frame_ms = boundary_frame * FRAME_MS
    pcm_duration_ms = n_frames * FRAME_MS
    return end_ms - (pcm_duration_ms - frame_ms)
