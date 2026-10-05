"""Per-session streaming diarization (ADR-0034).

PCM window → Silero speech regions → frontier-clipped chunks → ECAPA embedding
→ clustering → SpeakerSegments on a session-absolute timeline. The frontier
guarantees each millisecond is embedded once. ``attribute()`` reports words as
pending until the clusterer has bootstrapped; earlier chunks are relabeled then.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

import numpy as np

from diarization.attribution import (
    AttributionPolicy,
    SpeakerSegment,
    attribute_word,
)
from diarization.chunking import chunk_spans
from diarization.clustering import ClusteringConfig, OnlineSpeakerClusterer
from diarization.embedder import EcapaEmbedder
from diarization.vad import SileroSegmenter

SAMPLE_RATE_HZ = 16_000
UNKNOWN = "UNKNOWN"

__all__ = [
    "DiarizationConfig",
    "DiarizationStream",
    "SpeakerSegment",
]


@dataclass(frozen=True)
class DiarizationConfig:
    chunk_target_ms: int = 1200
    chunk_min_ms: int = 250
    # Single-voice session starts labeling S1 after this much audio.
    single_speaker_after_ms: int = 15_000
    clustering: ClusteringConfig = field(default_factory=ClusteringConfig)
    attribution: AttributionPolicy = field(default_factory=AttributionPolicy)


class DiarizationStream:
    """One per conversation session; not thread-safe, called from the window loop only."""

    def __init__(
        self,
        *,
        embedder: EcapaEmbedder,
        segmenter: SileroSegmenter,
        config: DiarizationConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._segmenter = segmenter
        self._config = config or DiarizationConfig()
        self._clusterer = OnlineSpeakerClusterer(self._config.clustering)
        self.segments: list[SpeakerSegment] = []
        self.diarized_until_ms: int = 0
        self.last_window_seconds: float = 0.0
        self.relabeled_total: int = 0

    @property
    def speaker_count(self) -> int:
        return self._clusterer.speaker_count

    @property
    def bootstrapped(self) -> bool:
        return self._clusterer.bootstrapped

    def process_window(self, pcm: np.ndarray, *, window_start_ms: int) -> list[SpeakerSegment]:
        """Diarize the not-yet-seen tail of ``pcm``; returns new segments (relabels mutate in place)."""
        t0 = time.perf_counter()
        cfg = self._config
        window_end_ms = window_start_ms + int(pcm.shape[0] * 1000 / SAMPLE_RATE_HZ)
        new: list[SpeakerSegment] = []

        for rel_start, rel_end in self._segmenter.speech_regions(pcm):
            abs_start = window_start_ms + rel_start
            abs_end = window_start_ms + rel_end
            start = max(abs_start, self.diarized_until_ms)  # frontier clip
            if abs_end <= start:
                continue
            if abs_end - start < cfg.chunk_min_ms:
                # Tiny tail of a region embedded last window: extend it instead of guessing.
                if self.segments and start - self.segments[-1].end_ms <= 150:
                    prev = self.segments[-1]
                    self.segments[-1] = replace(prev, end_ms=abs_end)
                continue
            for c_start, c_end in chunk_spans(
                start, abs_end, cfg.chunk_target_ms, cfg.chunk_min_ms
            ):
                lo = (c_start - window_start_ms) * SAMPLE_RATE_HZ // 1000
                hi = (c_end - window_start_ms) * SAMPLE_RATE_HZ // 1000
                chunk_pcm = pcm[max(0, lo) : hi]
                if chunk_pcm.shape[0] < cfg.chunk_min_ms * SAMPLE_RATE_HZ // 1000:
                    continue
                assignment, relabels = self._clusterer.observe(self._embedder.embed(chunk_pcm))
                for r in relabels:
                    old = self.segments[r.chunk_index]
                    self.segments[r.chunk_index] = replace(
                        old, label=r.label, confidence=r.confidence
                    )
                    self.relabeled_total += 1
                seg = SpeakerSegment(
                    start_ms=c_start,
                    end_ms=c_end,
                    label=assignment.label,
                    confidence=round(assignment.confidence, 4),
                )
                self.segments.append(seg)  # 1:1 with clusterer chunk indices (relabels)
                new.append(seg)

        self.diarized_until_ms = max(self.diarized_until_ms, window_end_ms)
        self.last_window_seconds = time.perf_counter() - t0
        return new

    def attribute(self, start_ms: int, end_ms: int) -> tuple[str | None, float | None]:
        """Speaker for a word timing; ``None`` until the speaker inventory is trustworthy."""
        if (
            not self._clusterer.bootstrapped
            and self.diarized_until_ms < self._config.single_speaker_after_ms
        ):
            return None, None
        return attribute_word(
            start_ms,
            end_ms,
            self.segments,
            diarized_until_ms=self.diarized_until_ms,
            policy=self._config.attribution,
        )
