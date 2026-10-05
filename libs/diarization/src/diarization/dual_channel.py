"""Channel-aware diarization of a mic/system capture: each side is diarized separately, then merged per 20 ms
frame (``both`` frames go to the side louder relative to its running median and into ``overlap_ms``).

A remote voice can never carry a local label or the reverse: the merge makes it impossible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np

from .attribution import UNKNOWN, SpeakerSegment
from .channels import BOTH, FRAME_MS, LOCAL, REMOTE, ChannelActivity, Segmenter, analyse_channels
from .offline import (
    SAMPLE_RATE_HZ,
    ClusterStats,
    OfflineDiarization,
    OfflineDiarizationConfig,
    _assign_display_names,
)
from .protocol import DiarizationHints, Diarizer
from .roster import RosterOutcome

# A side with less speech than this is not diarized at all.
MIN_SIDE_SPEECH_S = 3.0
# Running-median span for the double-talk loudness decision.
_MEDIAN_FRAMES = 1500  # 30 s

Analyse = Callable[..., ChannelActivity]


def diarize_dual(
    mic: np.ndarray,
    system: np.ndarray,
    *,
    diarizer: Diarizer,
    hints: DiarizationHints,
    segmenter: Segmenter,
    config: OfflineDiarizationConfig | None = None,
    analyse: Analyse = analyse_channels,
) -> OfflineDiarization:
    """Diarize both sides and merge; raises on any failure (the worker falls back to ``mono_fallback``)."""
    cfg = config or OfflineDiarizationConfig()
    hints = hints.validated()
    n = min(len(mic), len(system))
    # The mic copy is masked in place for the local pass, never the caller's array.
    mic_f = _as_float(mic[:n]).copy() if mic.dtype != np.int16 else _as_float(mic[:n])
    sys_f = _as_float(system[:n])
    activity = analyse(mic_f, sys_f, segmenter=segmenter)
    frames = len(activity.side)
    duration_ms = int(n * 1000 / SAMPLE_RATE_HZ)

    local_diar: OfflineDiarization | None = None
    if activity.local_speech_s >= MIN_SIDE_SPEECH_S:
        local_diar = diarizer.diarize(
            _mask_remote_only(mic_f, activity), SAMPLE_RATE_HZ, hints=_side_hints(hints)
        )
    local_count = len(local_diar.speakers) if local_diar else 0

    remote_hints = _side_hints(hints)
    if hints.num_speakers is not None and (activity.leak_gain_db is None or local_count == 1):
        # Headphones or one person at the Mac: the count splits as local + the rest remote.
        rest = hints.num_speakers - local_count
        remote_hints = DiarizationHints(num_speakers=rest) if rest >= 1 else DiarizationHints()
    remote_diar: OfflineDiarization | None = None
    if activity.remote_speech_s >= MIN_SIDE_SPEECH_S:
        remote_diar = diarizer.diarize(sys_f, SAMPLE_RATE_HZ, hints=remote_hints)

    local_frames = _frame_labels(local_diar, frames, prefix="L")
    remote_frames = _frame_labels(remote_diar, frames, prefix="R")
    labels, overlap = _merge(activity, local_frames, remote_frames)
    segments = _frames_to_segments(labels)
    if hints.num_speakers is not None:
        segments = _trim_to(segments, hints.num_speakers)

    display = _assign_display_names(segments)
    sides = {display[raw]: ("local" if raw.startswith("L:") else "remote") for raw in display}
    source = local_diar or remote_diar
    diar = OfflineDiarization(
        segments=segments,
        display_names=display,
        duration_ms=duration_ms,
        config=cfg,
        stats=ClusterStats(
            chunks=len(segments),
            clusters_raw=len(display),
            clusters_after_merge=len(display),
            clusters_dropped=0,
        ),
        engine=source.engine if source else getattr(diarizer, "engine", "unknown"),
        engine_version=source.engine_version if source else getattr(diarizer, "engine_version", ""),
        hints=hints,
        roster=_roster(local_diar, remote_diar),
        overlap_ms=overlap,
    )
    diar.sides = sides
    diar.channel = ChannelSummary(
        leak_gain_db=activity.leak_gain_db,
        local_speakers=sum(1 for s in sides.values() if s == "local"),
        remote_speakers=sum(1 for s in sides.values() if s == "remote"),
        both_share=activity.both_share,
    )
    return diar


class ChannelSummary:
    """What the channel analysis contributes to ``DiarizationStats``."""

    def __init__(
        self,
        *,
        leak_gain_db: float | None,
        local_speakers: int,
        remote_speakers: int,
        both_share: float,
    ) -> None:
        self.leak_gain_db = leak_gain_db
        self.local_speakers = local_speakers
        self.remote_speakers = remote_speakers
        self.both_share = both_share


def _as_float(pcm: np.ndarray) -> np.ndarray:
    if pcm.dtype == np.int16:
        return pcm.astype(np.float32) / 32768.0
    return np.asarray(pcm, dtype=np.float32)


def _side_hints(hints: DiarizationHints) -> DiarizationHints:
    """Per-side hints: a person's count becomes a cap on each side (the split is unknown)."""
    if hints.num_speakers is not None:
        return DiarizationHints(max_speakers=hints.num_speakers)
    return DiarizationHints(max_speakers=hints.max_speakers)


def _mask_remote_only(mic: np.ndarray, activity: ChannelActivity) -> np.ndarray:
    """The mic with leak-only frames silenced, IN PLACE when writeable (a second copy is ~460 MB on a 2-hour call)."""
    masked = mic if mic.flags.writeable else mic.copy()
    frame = SAMPLE_RATE_HZ * FRAME_MS // 1000
    for t in np.flatnonzero(activity.side == REMOTE):
        masked[t * frame : (t + 1) * frame] = 0.0
    return masked


def _frame_labels(diar: OfflineDiarization | None, frames: int, *, prefix: str) -> list[str | None]:
    out: list[str | None] = [None] * frames
    if diar is None:
        return out
    for seg in diar.segments:
        if seg.label == UNKNOWN:
            continue
        lo = max(0, seg.start_ms // FRAME_MS)
        hi = min(frames, -(-seg.end_ms // FRAME_MS))
        for t in range(lo, hi):
            out[t] = f"{prefix}:{seg.label}"
    return out


def _running_median(db: np.ndarray) -> np.ndarray:
    if len(db) == 0:
        return db
    out = np.empty_like(db)
    for start in range(0, len(db), _MEDIAN_FRAMES):
        block = db[start : start + _MEDIAN_FRAMES]
        out[start : start + _MEDIAN_FRAMES] = np.median(block)
    return out


def _merge(
    activity: ChannelActivity,
    local: list[str | None],
    remote: list[str | None],
) -> tuple[list[str | None], list[tuple[int, int]]]:
    """Per frame, the label of the side the frame belongs to."""
    mic_rel = activity.mic_db - _running_median(activity.mic_db)
    sys_rel = activity.system_db - _running_median(activity.system_db)
    labels: list[str | None] = [None] * len(activity.side)
    overlap: list[tuple[int, int]] = []
    for t, side in enumerate(activity.side):
        if side == LOCAL:
            labels[t] = local[t]
        elif side == REMOTE:
            labels[t] = remote[t]
        elif side == BOTH:
            first, second = (
                (local[t], remote[t])
                if len(mic_rel) > t and mic_rel[t] >= sys_rel[t]
                else (remote[t], local[t])
            )
            labels[t] = first or second
            start = t * FRAME_MS
            if overlap and overlap[-1][1] == start:
                overlap[-1] = (overlap[-1][0], start + FRAME_MS)
            else:
                overlap.append((start, start + FRAME_MS))
    return labels, overlap


def _frames_to_segments(labels: list[str | None]) -> list[SpeakerSegment]:
    segments: list[SpeakerSegment] = []
    t = 0
    while t < len(labels):
        label = labels[t]
        j = t
        while j < len(labels) and labels[j] == label:
            j += 1
        if label is not None:
            segments.append(
                SpeakerSegment(
                    start_ms=t * FRAME_MS, end_ms=j * FRAME_MS, label=label, confidence=1.0
                )
            )
        t = j
    return segments


def _trim_to(segments: list[SpeakerSegment], n: int) -> list[SpeakerSegment]:
    """Keep the ``n`` labels with the most speech; the rest become unattributed, never re-labelled."""
    speech: dict[str, int] = {}
    for s in segments:
        speech[s.label] = speech.get(s.label, 0) + (s.end_ms - s.start_ms)
    if len(speech) <= n:
        return segments
    keep = set(sorted(speech, key=lambda k: (-speech[k], k))[:n])
    return [s if s.label in keep else replace(s, label=UNKNOWN, confidence=0.0) for s in segments]


def _roster(*parts: OfflineDiarization | None) -> RosterOutcome | None:
    """Count confidence of the merged roster: low when either side's was."""
    outcomes = [p.roster for p in parts if p is not None and p.roster is not None]
    if not outcomes:
        return None
    low = [o for o in outcomes if o.count_confidence == "low"]
    base = low[0] if low else outcomes[0]
    return RosterOutcome(
        segments=[],
        speakers_kept=sum(o.speakers_kept for o in outcomes),
        speakers_dissolved=sum(o.speakers_dissolved for o in outcomes),
        count_confidence=base.count_confidence,
        overlap_share=max(o.overlap_share for o in outcomes),
        reasons=tuple(r for o in outcomes for r in o.reasons),
    )
