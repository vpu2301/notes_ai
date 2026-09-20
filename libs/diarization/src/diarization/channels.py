"""Which side of a call is speaking, from a two-channel capture (Sprint 31).

The macOS app records channel 0 = this Mac's microphone and channel 1 =
system (call) audio, sample-aligned on one clock. The side a voice comes
from is then a strong prior: a remote participant can never be the local
one. The complication is the loudspeaker: without headphones the remote
voice also reaches the microphone — delayed, quieter, reverberant. This
module decides, per 20 ms frame, whether the microphone holds a LOCAL
talker or only that leak:

* **VAD per channel** (Silero, the existing segmenter).
* **Leak model**, per 5-minute window (a call can move from headphones to
  loudspeakers): the delay ``d`` (0–300 ms) maximising the normalised
  cross-correlation of the two RMS envelopes over frames where the system
  channel speaks; with a peak ≥ ``LEAK_MIN_CORRELATION`` the leak is real and
  its gain ``g`` is the median of ``mic_dB(t) − system_dB(t−d)`` there.
  Otherwise ``g`` is ``None`` (headphones).
* **Local** on frame *t* ⇔ mic VAD ∧ (no leak ∨ ``mic_dB(t) > system_dB(t−d) + g
  + LOCAL_MARGIN_DB``). **Remote** ⇔ system VAD. 100 ms hangover each.

No echo cancellation: an attribution rule robust to echo instead (ADR-0053).
The margin and correlation floor are starting values, to be tuned on the
``dual_channel`` gold recordings. Pure numpy; the segmenter is injected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np

SAMPLE_RATE_HZ = 16_000
FRAME_MS = 20
HANGOVER_FRAMES = 5  # 100 ms
LEAK_WINDOW_S = 300.0
LEAK_MAX_DELAY_MS = 300
LEAK_MIN_CORRELATION = 0.3
LOCAL_MARGIN_DB = 6.0
_SILENCE_DB = -120.0

NONE, LOCAL, REMOTE, BOTH = 0, 1, 2, 3
Side = Literal["local", "remote", "both", "none"]
_SIDE_NAMES: dict[int, Side] = {NONE: "none", LOCAL: "local", REMOTE: "remote", BOTH: "both"}


class Segmenter(Protocol):
    def speech_regions(self, pcm: np.ndarray) -> list[tuple[int, int]]: ...


@dataclass(frozen=True)
class LeakEstimate:
    start_frame: int
    end_frame: int
    gain_db: float | None
    delay_ms: int | None


@dataclass(frozen=True)
class ChannelActivity:
    frame_ms: int
    side: np.ndarray  # uint8 per frame: 0 none, 1 local, 2 remote, 3 both
    leak_gain_db: float | None  # None = no measurable leak (headphones)
    leak_delay_ms: int | None
    local_speech_s: float
    remote_speech_s: float
    mic_db: np.ndarray = field(repr=False, default_factory=lambda: np.zeros(0))
    system_db: np.ndarray = field(repr=False, default_factory=lambda: np.zeros(0))
    windows: tuple[LeakEstimate, ...] = ()

    @property
    def both_share(self) -> float:
        speaking = int(np.count_nonzero(self.side))
        return round(float(np.count_nonzero(self.side == BOTH)) / speaking, 4) if speaking else 0.0


def analyse_channels(
    mic: np.ndarray, system: np.ndarray, *, segmenter: Segmenter
) -> ChannelActivity:
    """Per-frame side of speech for a mic/system pair (16 kHz, equal length)."""
    n = min(len(mic), len(system))
    mic, system = _as_float(mic[:n]), _as_float(system[:n])
    frame = SAMPLE_RATE_HZ * FRAME_MS // 1000
    frames = n // frame
    mic_db = _frame_db(mic, frame, frames)
    sys_db = _frame_db(system, frame, frames)
    mic_vad = _vad_frames(segmenter.speech_regions(mic), frames)
    sys_vad = _vad_frames(segmenter.speech_regions(system), frames)

    windows = _leak_windows(mic_db, sys_db, sys_vad)
    local = mic_vad.copy()
    for w in windows:
        if w.gain_db is None or w.delay_ms is None:
            continue
        lag = w.delay_ms // FRAME_MS
        idx = np.arange(w.start_frame, w.end_frame)
        src = np.clip(idx - lag, 0, frames - 1)
        above_leak = mic_db[idx] > sys_db[src] + w.gain_db + LOCAL_MARGIN_DB
        local[idx] &= above_leak
    local = _hangover(local)
    remote = _hangover(sys_vad)

    side = np.zeros(frames, dtype=np.uint8)
    side[local & ~remote] = LOCAL
    side[remote & ~local] = REMOTE
    side[local & remote] = BOTH
    overall = _overall(windows)
    frame_s = FRAME_MS / 1000
    return ChannelActivity(
        frame_ms=FRAME_MS,
        side=side,
        leak_gain_db=overall.gain_db,
        leak_delay_ms=overall.delay_ms,
        local_speech_s=round(float(np.count_nonzero(side & LOCAL)) * frame_s, 2),
        remote_speech_s=round(float(np.count_nonzero(side & REMOTE)) * frame_s, 2),
        mic_db=mic_db,
        system_db=sys_db,
        windows=tuple(windows),
    )


def side_for_span(activity: ChannelActivity, start_ms: int, end_ms: int) -> Side:
    """Majority side over a word span; ``both`` on a local/remote tie."""
    lo = max(0, start_ms // activity.frame_ms)
    hi = max(lo + 1, -(-end_ms // activity.frame_ms))
    frames = activity.side[lo:hi]
    local = int(np.count_nonzero(frames == LOCAL))
    remote = int(np.count_nonzero(frames == REMOTE))
    both = int(np.count_nonzero(frames == BOTH))
    if local == remote == both == 0:
        return "none"
    if both >= max(local, remote) or local == remote:
        return "both"
    return "local" if local > remote else "remote"


# ── internals ─────────────────────────────────────────────────────────


def _as_float(pcm: np.ndarray) -> np.ndarray:
    if pcm.dtype == np.int16:
        return pcm.astype(np.float32) / 32768.0
    return np.asarray(pcm, dtype=np.float32)


def _frame_db(pcm: np.ndarray, frame: int, frames: int) -> np.ndarray:
    if frames == 0:
        return np.zeros(0)
    blocks = pcm[: frames * frame].reshape(frames, frame).astype(np.float64)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1))
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(rms)
    return np.maximum(db, _SILENCE_DB)


def _vad_frames(regions: list[tuple[int, int]], frames: int) -> np.ndarray:
    active = np.zeros(frames, dtype=bool)
    for start_ms, end_ms in regions:
        lo = max(0, start_ms // FRAME_MS)
        hi = min(frames, -(-end_ms // FRAME_MS))
        if hi > lo:
            active[lo:hi] = True
    return active


def _hangover(active: np.ndarray) -> np.ndarray:
    """Keep a frame active for HANGOVER_FRAMES after speech stops."""
    out = active.copy()
    for k in range(1, HANGOVER_FRAMES + 1):
        out[k:] |= active[:-k]
    return out


def _leak_windows(
    mic_db: np.ndarray, sys_db: np.ndarray, sys_vad: np.ndarray
) -> list[LeakEstimate]:
    frames = len(mic_db)
    step = int(LEAK_WINDOW_S * 1000 // FRAME_MS)
    return [
        _estimate_leak(mic_db, sys_db, sys_vad, start, min(frames, start + step))
        for start in range(0, max(frames, 1), step)
    ]


def _estimate_leak(
    mic_db: np.ndarray, sys_db: np.ndarray, sys_vad: np.ndarray, start: int, end: int
) -> LeakEstimate:
    none = LeakEstimate(start, end, None, None)
    max_lag = LEAK_MAX_DELAY_MS // FRAME_MS
    if end - start <= max_lag + 10:
        return none
    mic_env = _envelope(mic_db[start:end])
    sys_env = _envelope(sys_db[start:end])
    active = sys_vad[start:end]
    best_corr, best_lag = -1.0, 0
    for lag in range(max_lag + 1):
        # mic at t against system at t − lag, over frames where the system spoke.
        m = mic_env[lag:]
        s = sys_env[: len(sys_env) - lag]
        mask = active[: len(active) - lag]
        if int(np.count_nonzero(mask)) < 10:
            continue
        corr = _normalised_corr(m[mask], s[mask])
        if corr > best_corr:
            best_corr, best_lag = corr, lag
    if best_corr < LEAK_MIN_CORRELATION:
        return none
    idx = np.arange(start + best_lag, end)
    sel = sys_vad[idx - best_lag]
    if not sel.any():
        return none
    gain = float(np.median(mic_db[idx][sel] - sys_db[idx - best_lag][sel]))
    return LeakEstimate(start, end, round(gain, 2), best_lag * FRAME_MS)


def _envelope(db: np.ndarray) -> np.ndarray:
    """Linear amplitude envelope (dB is too compressed to correlate on)."""
    return np.power(10.0, db / 20.0)


def _normalised_corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b) / denom if denom > 0 else 0.0


def _overall(windows: list[LeakEstimate]) -> LeakEstimate:
    """One summary for stats: the median over windows that saw a leak."""
    leaky = [w for w in windows if w.gain_db is not None and w.delay_ms is not None]
    if not leaky:
        return LeakEstimate(0, 0, None, None)
    return LeakEstimate(
        0,
        0,
        round(float(np.median([w.gain_db for w in leaky])), 2),  # type: ignore[misc]
        int(np.median([w.delay_ms for w in leaky])),  # type: ignore[misc]
    )


SIDE_NAMES = _SIDE_NAMES
