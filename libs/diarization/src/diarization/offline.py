"""Offline diarization of a full decoded recording (Ambient Capture v1).

Batch counterpart of dictation-service's streaming diarizer, built from
the same primitives so the two paths cannot drift:

    full PCM → Silero speech regions → ≤1.2 s chunks → ECAPA embeddings
    → the SAME deterministic clusterer, fed in stream order
    → contiguous speaker turns + a majority-overlap ``attribute()`` helper

Chunking (1200/250 ms) and clustering thresholds mirror the streaming
``DiarizationConfig`` on purpose: they were calibrated once (ADR-0034)
and a recording diarized live and re-diarized in batch should agree.

Labels are neutral ``SPEAKER_1..N`` in first-appearance order (AMBIENT
spec §5); the clusterer's internal S1/S2 vocabulary never leaves this
module. ``UNKNOWN`` evidence stays on the internal timeline (it still
counts as coverage for attribution) but is never surfaced as a turn —
ambiguous audio yields ``None``, never a guess.

Pilot cap: like the streaming path, the clusterer distinguishes at most
2 speakers; a third voice lands unattributed (documented limitation).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .attribution import UNKNOWN, AttributionPolicy, SpeakerSegment, attribute_word
from .chunking import chunk_spans
from .clustering import ClusteringConfig, OnlineSpeakerClusterer
from .embedder import EcapaEmbedder
from .vad import SileroSegmenter

SAMPLE_RATE_HZ = 16_000


@dataclass(frozen=True)
class OfflineDiarizationConfig:
    # Chunking of VAD speech regions before embedding — mirrors the
    # streaming DiarizationConfig (ADR-0034 calibration).
    chunk_target_ms: int = 1200
    chunk_min_ms: int = 250
    # Adjacent same-speaker chunks separated by at most this much silence
    # merge into one turn; a longer gap starts a new turn even for the
    # same speaker (a turn is "kept talking", not "spoke again later").
    turn_merge_gap_ms: int = 1000
    # ``attribute()`` floor: below this overlap-weighted confidence the
    # answer is None — an uncertain label on a meeting transcript is
    # worse than no label.
    min_confidence: float = 0.20
    clustering: ClusteringConfig = field(default_factory=ClusteringConfig)
    attribution: AttributionPolicy = field(default_factory=AttributionPolicy)


@dataclass(frozen=True)
class SpeakerTurn:
    """One contiguous stretch of a single speaker (absolute ms)."""

    start_ms: int
    end_ms: int
    speaker: str  # "SPEAKER_1".."SPEAKER_N"


class OfflineDiarization:
    """Result of :func:`diarize_offline`: the turn list plus attribution.

    ``turns``     — contiguous, non-overlapping, chronological.
    ``speakers``  — distinct labels in first-appearance order.
    ``attribute`` — majority-overlap speaker for a transcript span.
    """

    def __init__(
        self,
        *,
        segments: list[SpeakerSegment],
        display_names: dict[str, str],
        duration_ms: int,
        config: OfflineDiarizationConfig,
    ) -> None:
        self._segments = segments
        self._display_names = display_names
        self._duration_ms = duration_ms
        self._config = config
        self.turns: list[SpeakerTurn] = _merge_turns(
            segments, display_names, gap_ms=config.turn_merge_gap_ms
        )
        self.speakers: list[str] = _first_appearance([t.speaker for t in self.turns])

    def attribute(self, start_ms: int, end_ms: int) -> str | None:
        """Speaker for a transcript span, or ``None``.

        Majority overlap against the diarized timeline (same policy as
        streaming word attribution): ``None`` when coverage is below the
        floor, when no speaker owns a clear majority, or when the
        overlap-weighted confidence is under ``min_confidence``.
        """
        label, confidence = attribute_word(
            start_ms,
            end_ms,
            self._segments,
            # Everything is diarized offline; a span past the nominal end
            # (decoder rounding) must not read as "pending".
            diarized_until_ms=max(self._duration_ms, end_ms),
            policy=self._config.attribution,
        )
        if label is None or label == UNKNOWN:
            return None
        if confidence is None or confidence < self._config.min_confidence:
            return None
        return self._display_names.get(label)


def diarize_offline(
    pcm: np.ndarray,
    sample_rate_hz: int,
    *,
    embedder: EcapaEmbedder,
    segmenter: SileroSegmenter,
    config: OfflineDiarizationConfig | None = None,
) -> OfflineDiarization:
    """Diarize a whole recording of float32 mono PCM.

    The models are 16 kHz-only; callers own resampling (the batch worker
    already decodes to 16 kHz for Whisper), so any other rate raises
    rather than silently mislabeling time.
    """
    if sample_rate_hz != SAMPLE_RATE_HZ:
        raise ValueError(
            f"diarize_offline requires {SAMPLE_RATE_HZ} Hz mono PCM, got {sample_rate_hz} Hz"
        )
    cfg = config or OfflineDiarizationConfig()
    duration_ms = int(pcm.shape[0] * 1000 / SAMPLE_RATE_HZ)

    clusterer = OnlineSpeakerClusterer(cfg.clustering)
    segments: list[SpeakerSegment] = []
    for region_start, region_end in segmenter.speech_regions(pcm):
        for c_start, c_end in chunk_spans(
            region_start, region_end, cfg.chunk_target_ms, cfg.chunk_min_ms
        ):
            lo = c_start * SAMPLE_RATE_HZ // 1000
            hi = c_end * SAMPLE_RATE_HZ // 1000
            chunk_pcm = pcm[max(0, lo) : hi]
            if chunk_pcm.shape[0] < cfg.chunk_min_ms * SAMPLE_RATE_HZ // 1000:
                continue
            assignment, relabels = clusterer.observe(embedder.embed(chunk_pcm))
            # Retrospective corrections when the 2-way split lands: same
            # 1:1 chunk-index bookkeeping as the streaming timeline.
            for r in relabels:
                old = segments[r.chunk_index]
                segments[r.chunk_index] = SpeakerSegment(
                    start_ms=old.start_ms,
                    end_ms=old.end_ms,
                    label=r.label,
                    confidence=round(r.confidence, 4),
                )
            segments.append(
                SpeakerSegment(
                    start_ms=c_start,
                    end_ms=c_end,
                    label=assignment.label,
                    confidence=round(assignment.confidence, 4),
                )
            )

    display_names = _assign_display_names(segments)
    return OfflineDiarization(
        segments=segments,
        display_names=display_names,
        duration_ms=duration_ms,
        config=cfg,
    )


def _assign_display_names(segments: list[SpeakerSegment]) -> dict[str, str]:
    """Raw label → ``SPEAKER_N``, numbered by first appearance in time.

    First-appearance numbering (rather than copying the digit out of
    S1/S2) keeps the promise in the wire contract: SPEAKER_1 is whoever
    spoke first, even if bootstrap re-scoring made an S2 chunk the
    earliest confidently-labeled one.
    """
    names: dict[str, str] = {}
    for seg in segments:
        if seg.label == UNKNOWN or seg.label in names:
            continue
        names[seg.label] = f"SPEAKER_{len(names) + 1}"
    return names


def _merge_turns(
    segments: list[SpeakerSegment],
    display_names: dict[str, str],
    *,
    gap_ms: int,
) -> list[SpeakerTurn]:
    turns: list[SpeakerTurn] = []
    for seg in segments:
        speaker = display_names.get(seg.label)
        if speaker is None:  # UNKNOWN evidence never becomes a turn
            continue
        if turns and turns[-1].speaker == speaker and seg.start_ms - turns[-1].end_ms <= gap_ms:
            turns[-1] = SpeakerTurn(
                start_ms=turns[-1].start_ms,
                end_ms=max(turns[-1].end_ms, seg.end_ms),
                speaker=speaker,
            )
        else:
            turns.append(SpeakerTurn(start_ms=seg.start_ms, end_ms=seg.end_ms, speaker=speaker))
    return turns


def _first_appearance(labels: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for label in labels:
        seen.setdefault(label)
    return list(seen)
