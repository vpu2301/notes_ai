"""Speaker attribution by majority overlap: UNKNOWN when ambiguous, ``None`` when not yet diarized (streaming only)."""

from __future__ import annotations

from dataclasses import dataclass

UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SpeakerSegment:
    """One diarized span on the timeline (absolute milliseconds)."""

    start_ms: int
    end_ms: int
    label: str  # "S1" | "S2" | "UNKNOWN"
    confidence: float


@dataclass(frozen=True)
class AttributionPolicy:
    # Minimum diarized coverage of a word's duration to attribute it at all.
    min_coverage: float = 0.30
    # Minimum share of the covered overlap the winner must own (a 50/50 straddle → UNKNOWN).
    majority_share: float = 0.65


DEFAULT_POLICY = AttributionPolicy()


def attribute_word(
    start_ms: int,
    end_ms: int,
    segments: list[SpeakerSegment],
    *,
    diarized_until_ms: int,
    policy: AttributionPolicy = DEFAULT_POLICY,
) -> tuple[str | None, float | None]:
    """``(None, None)`` past the diarized frontier; ``("UNKNOWN", 0.0)`` when ambiguous; else the majority winner
    with overlap-weighted mean confidence scaled by its share."""
    if end_ms > diarized_until_ms:
        return None, None
    duration = max(1, end_ms - start_ms)

    overlap_by_label: dict[str, float] = {}
    conf_weight_by_label: dict[str, float] = {}
    for seg in segments:
        lo = max(start_ms, seg.start_ms)
        hi = min(end_ms, seg.end_ms)
        if hi <= lo:
            continue
        share = (hi - lo) / duration
        overlap_by_label[seg.label] = overlap_by_label.get(seg.label, 0.0) + share
        conf_weight_by_label[seg.label] = (
            conf_weight_by_label.get(seg.label, 0.0) + share * seg.confidence
        )

    covered = sum(overlap_by_label.values())
    if covered < policy.min_coverage:
        return UNKNOWN, 0.0

    known = {k: v for k, v in overlap_by_label.items() if k != UNKNOWN}
    if not known:
        return UNKNOWN, 0.0
    winner = max(known, key=lambda k: known[k])
    if known[winner] / covered < policy.majority_share:
        return UNKNOWN, 0.0

    mean_conf = conf_weight_by_label[winner] / overlap_by_label[winner]
    confidence = float(max(0.0, min(1.0, mean_conf * (known[winner] / covered))))
    return winner, confidence
