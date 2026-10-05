"""Roster guard + count confidence (Sprint 29 B-3), for any engine.

Both engines overcount the same way: a cough, a door, a far-field echo or
a laugh across the room becomes a "speaker" with a few seconds of speech.
The guard runs on an engine's chunk-level evidence before it becomes an
:class:`~diarization.offline.OfflineDiarization`:

**Floor.** A speaker whose speech is below
``max(min_speaker_speech_ms, min_speaker_share × total)`` is dissolved.
Where the engine can say what the speaker sounded like (a centroid), the
dissolved speech moves to the nearest kept speaker when they are alike
enough (cosine ≥ ``reassign_min_cosine``); otherwise it becomes
unattributed. With an exact count from a person the floor is OFF — a
human's count wins, and a quiet participant is still a participant.

**Count confidence.** ``"low"`` when the roster looks shaky: a kept
speaker holds under 5 % of the speech, a dissolved one held 2 % or more
(something real may have been folded away), or more than a quarter of the
speech overlaps. Otherwise ``"high"``. A word, not a number: nothing here
is calibrated enough to be a probability.

Centroids exist only in memory for the duration of one call; nothing here
keeps, returns or logs them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .attribution import UNKNOWN, SpeakerSegment
from .protocol import NO_HINTS, DiarizationHints

CountConfidence = Literal["high", "low"]

# count_confidence thresholds (Sprint 29 B-3). Shares of attributed speech.
LOW_KEPT_SHARE = 0.05
LOW_DISSOLVED_SHARE = 0.02
LOW_OVERLAP_SHARE = 0.25


@dataclass(frozen=True)
class RosterGuardConfig:
    """Floor knobs. Both zero → the guard never dissolves anything.

    Defaults are the values the Sprint 28 grid pointed at (≈ 8 s / 3 %);
    the worker passes ``MDX_DIAR_MIN_SPEAKER_SPEECH_MS`` /
    ``MDX_DIAR_MIN_SPEAKER_SHARE``.
    """

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
    """Apply the floor to engine labels and grade the resulting count.

    ``segments`` carry the engine's own labels (``UNKNOWN`` allowed);
    returned segments keep them — renumbering to ``SPEAKER_N`` happens
    afterwards, so numbering follows the roster that survived.
    """
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
            # Nothing reached the floor (a short memo). Keep the biggest
            # voice so the recording still has a speaker.
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
        # A count a person stated is not ours to doubt.
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
