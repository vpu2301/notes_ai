"""Engine-agnostic roster guard: speakers below ``max(min_speaker_speech_ms, min_speaker_share × total)`` are
dissolved into the nearest kept voice (cosine ≥ ``reassign_min_cosine``) or made unattributed; the floor is OFF
with an exact count. ``count_confidence`` is "low" on a tiny kept speaker, a sizeable dissolved one, or heavy overlap.
Centroids live in memory for one call only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .attribution import UNKNOWN, SpeakerSegment
from .protocol import NO_HINTS, DiarizationHints

CountConfidence = Literal["high", "low"]

# count_confidence thresholds, as shares of attributed speech.
LOW_KEPT_SHARE = 0.05
LOW_DISSOLVED_SHARE = 0.02
LOW_OVERLAP_SHARE = 0.25


@dataclass(frozen=True)
class RosterGuardConfig:
    """Floor knobs (MDX_DIAR_MIN_SPEAKER_SPEECH_MS / MDX_DIAR_MIN_SPEAKER_SHARE); both zero = never dissolve."""

    min_speaker_speech_ms: int = 8000
    min_speaker_share: float = 0.03
    reassign_min_cosine: float = 0.5


@dataclass(frozen=True)
class RosterOutcome:
    segments: list[SpeakerSegment]
    speakers_kept: int
    speakers_dissolved: int
    count_confidence: CountConfidence
    overlap_share: float
    # Why the confidence is low (empty when high) — metric/log vocabulary.
    reasons: tuple[str, ...] = field(default_factory=tuple)


def guard_roster(
    segments: list[SpeakerSegment],
    *,
    config: RosterGuardConfig,
    hints: DiarizationHints = NO_HINTS,
    centroids: Mapping[str, np.ndarray] | None = None,
    overlap_ms: list[tuple[int, int]] | None = None,
) -> RosterOutcome:
    """Apply the floor to the engine's own labels and grade the count; renumbering happens afterwards."""
    speech = _speech_by_label(segments)
    attributed = sum(speech.values())
    overlap = _total_ms(overlap_ms or [])
    all_speech = sum(s.end_ms - s.start_ms for s in segments)
    overlap_share = round(overlap / all_speech, 4) if all_speech else 0.0

    dissolved: list[str] = []
    if not hints.exact and attributed > 0 and len(speech) > 1:
        floor = max(float(config.min_speaker_speech_ms), config.min_speaker_share * attributed)
        dissolved = [label for label, ms in speech.items() if ms < floor]
        if len(dissolved) == len(speech):
            # Nothing reached the floor (a short memo): keep the biggest voice.
            biggest = max(speech, key=lambda label: (speech[label], label))
            dissolved.remove(biggest)

    out = list(segments)
    if dissolved:
        kept = [label for label in speech if label not in dissolved]
        target = _reassignment(dissolved, kept, centroids, config.reassign_min_cosine)
        out = [
            s
            if s.label not in target
            else SpeakerSegment(
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                label=target[s.label] or UNKNOWN,
                confidence=s.confidence if target[s.label] else 0.0,
            )
            for s in segments
        ]

    kept_speech = _speech_by_label(out)
    reasons: list[str] = []
    if not hints.exact and attributed > 0:
        if any(ms / attributed < LOW_KEPT_SHARE for ms in kept_speech.values()):
            reasons.append("small_speaker")
        if any(speech[label] / attributed >= LOW_DISSOLVED_SHARE for label in dissolved):
            reasons.append("dissolved_speaker")
        if overlap_share > LOW_OVERLAP_SHARE:
            reasons.append("overlap")
    return RosterOutcome(
        segments=out,
        speakers_kept=len(kept_speech),
        speakers_dissolved=len(dissolved),
        count_confidence="low" if reasons else "high",
        overlap_share=overlap_share,
        reasons=tuple(reasons),
    )


def _reassignment(
    dissolved: list[str],
    kept: list[str],
    centroids: Mapping[str, np.ndarray] | None,
    min_cosine: float,
) -> dict[str, str | None]:
    """Dissolved label → nearest kept label, or ``None`` (unattributed)."""
    target: dict[str, str | None] = dict.fromkeys(dissolved)
    if not centroids or not kept:
        return target
    kept_with = [label for label in kept if label in centroids]
    if not kept_with:
        return target
    matrix = _unit(np.stack([np.asarray(centroids[k], dtype=np.float64) for k in kept_with]))
    for label in dissolved:
        if label not in centroids:
            continue
        sims = matrix @ _unit(np.asarray(centroids[label], dtype=np.float64)[None, :])[0]
        best = int(np.argmax(sims))
        if float(sims[best]) >= min_cosine:
            target[label] = kept_with[best]
    return target


def _speech_by_label(segments: list[SpeakerSegment]) -> dict[str, int]:
    speech: dict[str, int] = {}
    for s in segments:
        if s.label == UNKNOWN:
            continue
        speech[s.label] = speech.get(s.label, 0) + (s.end_ms - s.start_ms)
    return speech


def _total_ms(spans: list[tuple[int, int]]) -> int:
    """Union length of possibly overlapping spans."""
    total = 0
    end = -1
    for start, stop in sorted(spans):
        if stop <= end:
            continue
        total += stop - max(start, end)
        end = stop
    return total


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return np.asarray(matrix / norms)
