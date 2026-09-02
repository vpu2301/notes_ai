"""Offline diarizer tests with fake embedder/segmenter (no torch, no models).

Same synthetic vector geometry as test_clustering: voice A around e0,
voice B around ``0.2*e0 + sqrt(0.96)*e1`` (cross-voice cosine 0.19,
intra-voice 0.90) — comfortably on either side of ``split_threshold``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from diarization.offline import (
    SAMPLE_RATE_HZ,
    OfflineClusteringConfig,
    OfflineDiarizationConfig,
    cluster_embeddings,
    diarize_offline,
)

DIM = 7
_C = math.sqrt(0.95)
_S = math.sqrt(0.05)


class FakeEmbedder:
    def __init__(self, vectors: list[np.ndarray]) -> None:
        self._vectors = list(vectors)
        self.calls = 0

    def embed(self, pcm: np.ndarray) -> np.ndarray:
        v = self._vectors[self.calls]
        self.calls += 1
        return v


class FakeSegmenter:
    """One speech_regions() call over the whole buffer in the offline path."""

    def __init__(self, regions: list[tuple[int, int]]) -> None:
        self._regions = regions
        self.calls = 0

    def speech_regions(self, pcm: np.ndarray) -> list[tuple[int, int]]:
        self.calls += 1
        return self._regions


def _vec(base: np.ndarray, perturb_axis: int, sign: float = 1.0) -> np.ndarray:
    v = _C * base
    v[perturb_axis] += sign * _S
    return v.astype(np.float32)


def _voice_a(n: int) -> list[np.ndarray]:
    a = np.zeros(DIM)
    a[0] = 1.0
    return [_vec(a.copy(), 2, +1.0 if i % 2 == 0 else -1.0) for i in range(n)]


def _voice_b(n: int) -> list[np.ndarray]:
    b = np.zeros(DIM)
    b[0] = 0.2
    b[1] = math.sqrt(1.0 - 0.2 * 0.2)
    return [_vec(b.copy(), 4, +1.0 if i % 2 == 0 else -1.0) for i in range(n)]


def _pcm(ms: int) -> np.ndarray:
    return np.zeros(ms * SAMPLE_RATE_HZ // 1000, dtype=np.float32)


def test_two_voices_become_two_neutral_speakers_with_contiguous_turns() -> None:
    embedder = FakeEmbedder(_voice_a(2) + _voice_b(2))
    segmenter = FakeSegmenter([(0, 1000), (1000, 2000), (2000, 3000), (3000, 4000)])

    diar = diarize_offline(_pcm(4000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert segmenter.calls == 1
    assert embedder.calls == 4
    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    # Adjacent same-speaker chunks merge into contiguous turns.
    assert [(t.start_ms, t.end_ms, t.speaker) for t in diar.turns] == [
        (0, 2000, "SPEAKER_1"),
        (2000, 4000, "SPEAKER_2"),
    ]


def test_attribute_majority_overlap_and_straddle() -> None:
    embedder = FakeEmbedder(_voice_a(2) + _voice_b(2))
    segmenter = FakeSegmenter([(0, 1000), (1000, 2000), (2000, 3000), (3000, 4000)])
    diar = diarize_offline(_pcm(4000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert diar.attribute(100, 900) == "SPEAKER_1"
    assert diar.attribute(2100, 2900) == "SPEAKER_2"
    # A 50/50 straddle across the turn boundary owns no majority: None,
    # never a guess.
    assert diar.attribute(1500, 2500) is None
    # A span past the recording end is still attributed (rounding slack),
    # not treated as "pending" — offline has no frontier.
    assert diar.attribute(3200, 4100) == "SPEAKER_2"


def test_single_voice_is_one_speaker_one_turn() -> None:
    embedder = FakeEmbedder(_voice_a(4))
    segmenter = FakeSegmenter([(0, 1000), (1000, 2000), (2000, 3000), (3000, 4000)])
    diar = diarize_offline(_pcm(4000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert diar.speakers == ["SPEAKER_1"]
    assert [(t.start_ms, t.end_ms) for t in diar.turns] == [(0, 4000)]
    # Attribution works without a 2-way split ever landing (one voice in
    # the whole recording); the very first chunk carries zero confidence
    # by design, so probe a later span.
    assert diar.attribute(1100, 1900) == "SPEAKER_1"


def test_long_gap_starts_a_new_turn_for_the_same_speaker() -> None:
    embedder = FakeEmbedder(_voice_a(4))
    # 5 s of silence between the second and third chunk (> turn_merge_gap_ms).
    segmenter = FakeSegmenter([(0, 1000), (1000, 2000), (7000, 8000), (8000, 9000)])
    diar = diarize_offline(_pcm(9000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert diar.speakers == ["SPEAKER_1"]
    assert [(t.start_ms, t.end_ms) for t in diar.turns] == [(0, 2000), (7000, 9000)]


def test_no_speech_yields_no_speakers_and_no_attribution() -> None:
    embedder = FakeEmbedder([])
    segmenter = FakeSegmenter([])
    diar = diarize_offline(_pcm(4000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert diar.speakers == []
    assert diar.turns == []
    assert diar.attribute(0, 1000) is None


def test_long_region_is_chunked_before_embedding() -> None:
    embedder = FakeEmbedder(_voice_a(3))
    segmenter = FakeSegmenter([(0, 4000)])
    diar = diarize_offline(_pcm(4000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert embedder.calls == 3  # 4000 ms → 3 near-1200 ms chunks
    assert diar.speakers == ["SPEAKER_1"]


def test_rejects_non_16k_sample_rate() -> None:
    embedder = FakeEmbedder([])
    segmenter = FakeSegmenter([])
    with pytest.raises(ValueError, match="16000"):
        diarize_offline(_pcm(1000), 44_100, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]


def test_config_mirrors_streaming_calibration() -> None:
    cfg = OfflineDiarizationConfig()
    # These values were calibrated for the streaming diarizer (ADR-0034);
    # the offline path mirrors them so live and batch diarization agree.
    assert (cfg.chunk_target_ms, cfg.chunk_min_ms) == (1200, 250)
    assert cfg.clustering.split_threshold == 0.45
    assert cfg.attribution.majority_share == 0.65


# ── N-speaker agglomerative clustering (ADR-0043) ───────────────────


def _voice_c(n: int) -> list[np.ndarray]:
    c = np.zeros(DIM)
    c[3] = 1.0
    return [_vec(c.copy(), 5, +1.0 if i % 2 == 0 else -1.0) for i in range(n)]


def _regions(count: int, ms: int = 1000) -> list[tuple[int, int]]:
    return [(i * ms, (i + 1) * ms) for i in range(count)]


def test_three_voices_become_three_speakers_in_first_appearance_order() -> None:
    # host, guest 1, host, guest 2, guest 1 — the pilot's 2-slot clusterer
    # would have left one of the guests UNKNOWN.
    embedder = FakeEmbedder(_voice_a(2) + _voice_b(2) + _voice_a(2) + _voice_c(2) + _voice_b(2))
    segmenter = FakeSegmenter(_regions(10))

    diar = diarize_offline(_pcm(10_000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"]
    assert [(t.start_ms, t.end_ms, t.speaker) for t in diar.turns] == [
        (0, 2000, "SPEAKER_1"),
        (2000, 4000, "SPEAKER_2"),
        (4000, 6000, "SPEAKER_1"),
        (6000, 8000, "SPEAKER_3"),
        (8000, 10_000, "SPEAKER_2"),
    ]
    assert diar.attribute(6100, 7900) == "SPEAKER_3"


def test_a_single_stray_chunk_never_becomes_a_speaker() -> None:
    # One chunk of a third voice (a cough, a bystander) is below the
    # speaker floor: it is folded into the nearest real speaker if it is
    # close enough, otherwise it stays UNKNOWN — never SPEAKER_3.
    embedder = FakeEmbedder(_voice_a(3) + _voice_c(1) + _voice_b(3))
    segmenter = FakeSegmenter(_regions(7))

    diar = diarize_offline(_pcm(7000), SAMPLE_RATE_HZ, embedder=embedder, segmenter=segmenter)  # type: ignore[arg-type]

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.attribute(3100, 3900) is None


def test_roster_is_capped_at_max_speakers() -> None:
    cfg = OfflineDiarizationConfig(offline_clustering=OfflineClusteringConfig(max_speakers=2))
    embedder = FakeEmbedder(_voice_a(3) + _voice_b(3) + _voice_c(2))
    segmenter = FakeSegmenter(_regions(8))

    diar = diarize_offline(
        _pcm(8000),
        SAMPLE_RATE_HZ,
        embedder=embedder,
        segmenter=segmenter,
        config=cfg,  # type: ignore[arg-type]
    )

    # The two biggest clusters survive; the third voice lands UNKNOWN.
    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.attribute(6100, 7900) is None


def test_long_recordings_cluster_on_a_sample_and_score_every_chunk() -> None:
    cfg = OfflineDiarizationConfig(offline_clustering=OfflineClusteringConfig(max_cluster_chunks=6))
    pattern = _voice_a(5) + _voice_b(5) + _voice_a(5) + _voice_b(5)
    embedder = FakeEmbedder(pattern)
    segmenter = FakeSegmenter(_regions(20))

    diar = diarize_offline(
        _pcm(20_000),
        SAMPLE_RATE_HZ,
        embedder=embedder,
        segmenter=segmenter,
        config=cfg,  # type: ignore[arg-type]
    )

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert [(t.start_ms, t.end_ms, t.speaker) for t in diar.turns] == [
        (0, 5000, "SPEAKER_1"),
        (5000, 10_000, "SPEAKER_2"),
        (10_000, 15_000, "SPEAKER_1"),
        (15_000, 20_000, "SPEAKER_2"),
    ]


def test_clustering_is_deterministic() -> None:
    vectors = _voice_a(3) + _voice_b(3) + _voice_c(3) + _voice_a(2)
    first = cluster_embeddings(vectors, OfflineClusteringConfig())
    second = cluster_embeddings(list(vectors), OfflineClusteringConfig())
    assert first == second
    labels, confidences = first
    assert labels == ["S1"] * 3 + ["S2"] * 3 + ["S3"] * 3 + ["S1"] * 2
    assert all(c > 0.5 for c in confidences)


def test_cluster_embeddings_empty() -> None:
    assert cluster_embeddings([], OfflineClusteringConfig()) == ([], [])
