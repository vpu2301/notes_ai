"""Offline diarization: PCM → Silero regions → ≤1.2 s chunks → ECAPA embeddings → average-linkage
agglomeration over the whole recording (ADR-0034/0045) → neutral ``SPEAKER_N`` turns.

``UNKNOWN`` evidence counts for attribution coverage but is never a turn: ambiguous audio yields ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .attribution import UNKNOWN, AttributionPolicy, SpeakerSegment, attribute_word
from .chunking import chunk_spans
from .clustering import ClusteringConfig, _confidence
from .embedder import EcapaEmbedder
from .protocol import NO_HINTS, DiarizationHints
from .roster import CountConfidence, RosterGuardConfig, RosterOutcome, guard_roster
from .vad import SileroSegmenter

SAMPLE_RATE_HZ = 16_000

ENGINE_ID = "legacy-ecapa-ahc"
ENGINE_VERSION = "spkrec-ecapa-voxceleb@0f99f2d"


@dataclass(frozen=True)
class OfflineClusteringConfig:
    """Agglomerative clustering knobs: ``link_threshold`` is the same-voice/cross-voice cosine boundary (ADR-0034);
    ``centroid_merge_threshold`` folds a voice's outlier side clusters back; the rest floors and caps the roster."""

    link_threshold: float = 0.45
    centroid_merge_threshold: float = 0.60
    max_speakers: int = 8
    # Minimum chunks (≈ seconds) and share of all chunks for a cluster to count as a speaker.
    min_speaker_chunks: int = 2
    min_speaker_share: float = 0.01
    # Floor in ms of speech; 0 disables it.
    min_speaker_speech_ms: int = 0
    # Chunks shorter than this are scored but do not form clusters; 0 = all do.
    cluster_chunk_min_ms: int = 0
    # Per-chunk scoring: below the floor or within the margin of the runner-up → UNKNOWN.
    assign_floor: float = 0.45
    ambiguity_margin: float = 0.08
    margin_scale: float = 0.30
    # Above this many chunks (n×n matrix) clusters are learnt on an evenly spaced sample.
    max_cluster_chunks: int = 1500
    # With an exact count, still join same-voice centroids so an overstated count cannot invent speakers.
    hint_same_voice_merge: bool = True


@dataclass(frozen=True)
class OfflineDiarizationConfig:
    # Mirrors the streaming DiarizationConfig (ADR-0034 calibration).
    chunk_target_ms: int = 1200
    chunk_min_ms: int = 250
    # Same-speaker chunks within this gap merge into one turn.
    turn_merge_gap_ms: int = 1000
    # ``attribute()`` floor: below it the answer is None.
    min_confidence: float = 0.20
    # Streaming calibration for callers that read it here; the batch clusterer uses ``offline_clustering``.
    clustering: ClusteringConfig = field(default_factory=ClusteringConfig)
    offline_clustering: OfflineClusteringConfig = field(default_factory=OfflineClusteringConfig)
    attribution: AttributionPolicy = field(default_factory=AttributionPolicy)


@dataclass(frozen=True)
class ClusterStats:
    """Why the clusterer produced the roster it did (no labels, no content)."""

    chunks: int = 0
    clusters_raw: int = 0  # after agglomeration
    clusters_after_merge: int = 0  # after the centroid merge
    clusters_dropped: int = 0  # below the speaker floor or over the cap


@dataclass(frozen=True)
class SpeakerTurn:
    """One contiguous stretch of a single speaker (absolute ms)."""

    start_ms: int
    end_ms: int
    speaker: str  # "SPEAKER_1".."SPEAKER_N"


class OfflineDiarization:
    """What every :class:`~diarization.protocol.Diarizer` returns: chronological ``turns``, ``speakers`` in
    first-appearance order, ``attribute`` by majority overlap. Numbers and labels only, never an embedding."""

    def __init__(
        self,
        *,
        segments: list[SpeakerSegment],
        display_names: dict[str, str],
        duration_ms: int,
        config: OfflineDiarizationConfig,
        stats: ClusterStats | None = None,
        engine: str = ENGINE_ID,
        engine_version: str = ENGINE_VERSION,
        hints: DiarizationHints = NO_HINTS,
        roster: RosterOutcome | None = None,
        overlap_ms: list[tuple[int, int]] | None = None,
    ) -> None:
        self.stats = stats or ClusterStats()
        self.engine = engine
        self.engine_version = engine_version
        self.hints = hints
        self.roster = roster
        self.overlap_ms: list[tuple[int, int]] = list(overlap_ms or [])
        # Dual-channel captures only: display label → "local" | "remote", plus the channel summary.
        self.sides: dict[str, str] = {}
        self.channel: Any = None
        self._segments = segments
        self._display_names = display_names
        self._duration_ms = duration_ms
        self._config = config
        self.turns: list[SpeakerTurn] = _merge_turns(
            segments, display_names, gap_ms=config.turn_merge_gap_ms
        )
        self.speakers: list[str] = _first_appearance([t.speaker for t in self.turns])

    def attribute(self, start_ms: int, end_ms: int) -> str | None:
        """Majority-overlap speaker for a span; ``None`` below coverage, majority or ``min_confidence``."""
        label, confidence = attribute_word(
            start_ms,
            end_ms,
            self._segments,
            # A span past the nominal end (decoder rounding) must not read as "pending".
            diarized_until_ms=max(self._duration_ms, end_ms),
            policy=self._config.attribution,
        )
        if label is None or label == UNKNOWN:
            return None
        if confidence is None or confidence < self._config.min_confidence:
            return None
        return self._display_names.get(label)

    @property
    def count_confidence(self) -> CountConfidence | None:
        return self.roster.count_confidence if self.roster else None

    @property
    def duration_ms(self) -> int:
        """Length of the recording this timeline covers."""
        return self._duration_ms

    @property
    def segments(self) -> list[SpeakerSegment]:
        """Chunk-level evidence with display labels (``UNKNOWN`` kept)."""
        return [
            SpeakerSegment(
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                label=self._display_names.get(s.label, UNKNOWN),
                confidence=s.confidence,
            )
            for s in self._segments
        ]


def diarize_offline(
    pcm: np.ndarray,
    sample_rate_hz: int,
    *,
    embedder: EcapaEmbedder,
    segmenter: SileroSegmenter,
    config: OfflineDiarizationConfig | None = None,
    hints: DiarizationHints = NO_HINTS,
    roster: RosterGuardConfig | None = None,
) -> OfflineDiarization:
    """Diarize a whole 16 kHz float32 mono recording (other rates raise); ``roster=None`` = guard floor off."""
    if sample_rate_hz != SAMPLE_RATE_HZ:
        raise ValueError(
            f"diarize_offline requires {SAMPLE_RATE_HZ} Hz mono PCM, got {sample_rate_hz} Hz"
        )
    cfg = config or OfflineDiarizationConfig()
    spans, embeddings = embed_chunks(pcm, embedder=embedder, segmenter=segmenter, config=cfg)
    duration_ms = int(pcm.shape[0] * 1000 / SAMPLE_RATE_HZ)
    return diarize_embeddings(
        spans, embeddings, duration_ms=duration_ms, config=cfg, hints=hints, roster=roster
    )


def embed_chunks(
    pcm: np.ndarray,
    *,
    embedder: EcapaEmbedder,
    segmenter: SileroSegmenter,
    config: OfflineDiarizationConfig,
) -> tuple[list[tuple[int, int]], list[np.ndarray]]:
    """VAD → chunking → one embedding per chunk (split from clustering so the eval grid can re-cluster)."""
    spans: list[tuple[int, int]] = []
    embeddings: list[np.ndarray] = []
    for region_start, region_end in segmenter.speech_regions(pcm):
        for c_start, c_end in chunk_spans(
            region_start, region_end, config.chunk_target_ms, config.chunk_min_ms
        ):
            lo = c_start * SAMPLE_RATE_HZ // 1000
            hi = c_end * SAMPLE_RATE_HZ // 1000
            chunk_pcm = pcm[max(0, lo) : hi]
            if chunk_pcm.shape[0] < config.chunk_min_ms * SAMPLE_RATE_HZ // 1000:
                continue
            spans.append((c_start, c_end))
            embeddings.append(np.asarray(embedder.embed(chunk_pcm), dtype=np.float64).ravel())
    return spans, embeddings


def diarize_embeddings(
    spans: list[tuple[int, int]],
    embeddings: list[np.ndarray],
    *,
    duration_ms: int,
    config: OfflineDiarizationConfig,
    hints: DiarizationHints = NO_HINTS,
    roster: RosterGuardConfig | None = None,
) -> OfflineDiarization:
    """Cluster chunk embeddings into the diarized timeline."""
    hints = hints.validated()
    labels, confidences, stats = cluster_embeddings_with_stats(
        embeddings,
        config.offline_clustering,
        durations_ms=[e - s for s, e in spans],
        num_speakers=hints.num_speakers,
        max_speakers=hints.max_speakers,
    )
    segments = [
        SpeakerSegment(start_ms=s, end_ms=e, label=label, confidence=round(conf, 4))
        for (s, e), label, conf in zip(spans, labels, confidences, strict=True)
    ]
    # Centroids live for this call only.
    outcome = guard_roster(
        segments,
        config=roster or _NO_FLOOR,
        hints=hints,
        centroids=_label_centroids(labels, embeddings),
    )
    segments = outcome.segments
    return OfflineDiarization(
        segments=segments,
        display_names=_assign_display_names(segments),
        duration_ms=duration_ms,
        config=config,
        stats=stats,
        hints=hints,
        roster=outcome,
    )


# Floor off: grades the count, dissolves nothing.
_NO_FLOOR = RosterGuardConfig(min_speaker_speech_ms=0, min_speaker_share=0.0)


def _label_centroids(labels: list[str], embeddings: list[np.ndarray]) -> dict[str, np.ndarray]:
    grouped: dict[str, list[np.ndarray]] = {}
    for label, vector in zip(labels, embeddings, strict=True):
        if label != UNKNOWN:
            grouped.setdefault(label, []).append(vector)
    return {label: np.mean(np.stack(vs), axis=0) for label, vs in grouped.items()}


# ── Clustering ──────────────────────────────────────────────────────


def cluster_embeddings(
    embeddings: list[np.ndarray], cfg: OfflineClusteringConfig
) -> tuple[list[str], list[float]]:
    """Label every chunk ``S1..Sk`` (or ``UNKNOWN``) with a confidence.

    Agglomerate at ``link_threshold`` → merge near-identical centroids → dissolve dust, cap the roster →
    score every chunk against the survivors (floor + margin → UNKNOWN). Deterministic; numbered by first appearance.
    """
    labels, confidences, _ = cluster_embeddings_with_stats(embeddings, cfg)
    return labels, confidences


def cluster_embeddings_with_stats(
    embeddings: list[np.ndarray],
    cfg: OfflineClusteringConfig,
    *,
    durations_ms: list[int] | None = None,
    num_speakers: int | None = None,
    max_speakers: int | None = None,
) -> tuple[list[str], list[float], ClusterStats]:
    """:func:`cluster_embeddings` plus its :class:`ClusterStats`.

    ``durations_ms`` enables the duration knobs. ``num_speakers=k`` merges to exactly k with no floor (a
    person's count wins); ``max_speakers`` merges until under the cap. Nothing is ever invented.
    """
    n = len(embeddings)
    if n == 0:
        return [], [], ClusterStats()
    if durations_ms is not None and len(durations_ms) != n:
        raise ValueError("durations_ms must have one entry per embedding")
    if num_speakers is None and max_speakers is not None:
        # A cap is a ceiling: an uncapped answer that already fits is returned unchanged.
        plain = cluster_embeddings_with_stats(embeddings, cfg, durations_ms=durations_ms)
        if len({label for label in plain[0] if label != UNKNOWN}) <= max_speakers:
            return plain
    matrix = _unit_rows(np.stack(embeddings))

    sample = _sample_indices(n, cfg.max_cluster_chunks)
    if durations_ms is not None and cfg.cluster_chunk_min_ms > 0:
        long_enough = np.array([durations_ms[i] >= cfg.cluster_chunk_min_ms for i in sample])
        if long_enough.any():
            sample = sample[long_enough]
    learn = matrix[sample]
    cap = min(cfg.max_speakers, max_speakers) if max_speakers is not None else None
    floor = max(cfg.min_speaker_chunks, int(np.ceil(cfg.min_speaker_share * len(sample))))
    if num_speakers is not None or cap is not None:
        # Drop dust (coughs, doors) before merging to k, or it survives while two real voices merge;
        # dust is judged AFTER the same-voice merge, since far-field audio fragments one speaker.
        natural = _merge_close_centroids(
            learn, _average_linkage(learn, cfg.link_threshold), cfg.centroid_merge_threshold
        )
        counts: dict[int, int] = {}
        for c in natural:
            counts[c] = counts.get(c, 0) + 1
        clean = np.array([counts[c] >= floor for c in natural])
        if clean.any():
            sample, learn = sample[clean], learn[clean]
    if num_speakers is None and cap is not None:
        assignments = _average_linkage(learn, cfg.link_threshold, target=cap)
    else:
        assignments = _average_linkage(learn, cfg.link_threshold, target=num_speakers)
    clusters_raw = len(set(assignments))
    # Also with a count: joining same-voice clusters keeps an overstated count from inventing speakers.
    if num_speakers is None or cfg.hint_same_voice_merge:
        assignments = _merge_close_centroids(learn, assignments, cfg.centroid_merge_threshold)
    clusters_after_merge = len(set(assignments))

    sizes: dict[int, int] = {}
    speech: dict[int, float] = {}
    for row, c in enumerate(assignments):
        sizes[c] = sizes.get(c, 0) + 1
        if durations_ms is not None:
            speech[c] = speech.get(c, 0.0) + durations_ms[int(sample[row])]
    # A sampled recording learns on a subset: scale sampled speech back up.
    speech_scale = n / len(sample)
    kept = [
        c
        for c, size in sizes.items()
        if num_speakers is not None
        or (
            size >= floor
            and (
                durations_ms is None
                or cfg.min_speaker_speech_ms <= 0
                or speech[c] * speech_scale >= cfg.min_speaker_speech_ms
            )
        )
    ]
    if not kept:
        # Nothing reached the floor (a tiny recording): keep the biggest cluster.
        kept = [max(sizes, key=lambda c: (sizes[c], -c))]
    kept.sort(key=lambda c: (-sizes[c], c))
    kept = kept[: num_speakers or cap or cfg.max_speakers]
    stats = ClusterStats(
        chunks=n,
        clusters_raw=clusters_raw,
        clusters_after_merge=clusters_after_merge,
        clusters_dropped=clusters_after_merge - len(kept),
    )

    centroids = _unit_rows(
        np.stack(
            [learn[[i for i, c in enumerate(assignments) if c == k]].mean(axis=0) for k in kept]
        )
    )

    sims = matrix @ centroids.T  # (n, k) cosine similarities
    labels: list[str] = []
    confidences: list[float] = []
    # Numbered by first appearance in time, not cluster size.
    numbering: dict[int, str] = {}
    for row in sims:
        order = np.argsort(-row, kind="stable")
        best_idx = int(order[0])
        best = float(row[best_idx])
        second = float(row[order[1]]) if row.shape[0] > 1 else 0.0
        if best < cfg.assign_floor or (row.shape[0] > 1 and best - second < cfg.ambiguity_margin):
            labels.append(UNKNOWN)
            confidences.append(0.0)
            continue
        if best_idx not in numbering:
            numbering[best_idx] = f"S{len(numbering) + 1}"
        labels.append(numbering[best_idx])
        confidences.append(_confidence(best, second, cfg.margin_scale))
    return labels, confidences, stats


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return np.asarray(matrix / norms)


def _sample_indices(n: int, cap: int) -> np.ndarray:
    if n <= cap:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, cap).round().astype(int))


def _average_linkage(
    unit: np.ndarray,
    threshold: float,
    *,
    target: int | None = None,
    cap: int | None = None,
) -> list[int]:
    """Average-linkage agglomeration of L2-normalised rows until the closest pair is below ``threshold``
    (``target`` = merge to exactly that many; ``cap`` = keep merging while over it). Returns a cluster id per row.

    Lance–Williams update (size-weighted mean) plus a best-partner cache: O(n²), not O(n³).
    """
    n = unit.shape[0]
    if n == 1:
        return [0]
    sim = unit @ unit.T
    np.fill_diagonal(sim, -np.inf)
    sizes = np.ones(n)
    alive = np.ones(n, dtype=bool)
    parent = np.arange(n)  # row → cluster representative
    members: dict[int, list[int]] = {i: [i] for i in range(n)}
    best_val = sim.max(axis=1)
    best_idx = sim.argmax(axis=1)

    while alive.sum() > 1:
        i = int(np.argmax(best_val))
        clusters = int(alive.sum())
        if target is not None:
            if clusters <= target:
                break
        elif best_val[i] < threshold and (cap is None or clusters <= cap):
            break
        j = int(best_idx[i])
        if i > j:
            i, j = j, i  # keep the lower index as the survivor (determinism)
        merged = (sim[i] * sizes[i] + sim[j] * sizes[j]) / (sizes[i] + sizes[j])
        sim[i, :] = merged
        sim[:, i] = merged
        sim[i, i] = -np.inf
        sim[j, :] = -np.inf
        sim[:, j] = -np.inf
        sizes[i] += sizes[j]
        alive[j] = False
        members[i].extend(members.pop(j))
        for row in members[i]:
            parent[row] = i
        # Refresh best partners for the survivor, the dead row, their dependants, and rows the survivor now beats.
        stale = (best_idx == i) | (best_idx == j)
        stale[i] = True
        stale[j] = True
        best_val[stale] = sim[stale].max(axis=1)
        best_idx[stale] = sim[stale].argmax(axis=1)
        improved = ~stale & (sim[:, i] > best_val)
        best_val[improved] = sim[improved, i]
        best_idx[improved] = i
        best_val[j] = -np.inf

    # Renumber clusters by their smallest member so ids are stable.
    ids: dict[int, int] = {}
    out: list[int] = []
    for row in range(n):
        rep = int(parent[row])
        if rep not in ids:
            ids[rep] = len(ids)
        out.append(ids[rep])
    return out


def _merge_close_centroids(unit: np.ndarray, assignments: list[int], threshold: float) -> list[int]:
    """Merge clusters whose centroids are at least ``threshold`` alike, closest pair first, until none are."""
    labels = list(assignments)
    while True:
        ids = sorted(set(labels))
        if len(ids) < 2:
            return labels
        centroids = _unit_rows(
            np.stack([unit[[i for i, c in enumerate(labels) if c == k]].mean(axis=0) for k in ids])
        )
        sims = centroids @ centroids.T
        np.fill_diagonal(sims, -np.inf)
        a, b = divmod(int(np.argmax(sims)), len(ids))
        if sims[a, b] < threshold:
            return labels
        keep, drop = (ids[a], ids[b]) if ids[a] < ids[b] else (ids[b], ids[a])
        labels = [keep if c == drop else c for c in labels]


# ── Post-processing ─────────────────────────────────────────────────


def _assign_display_names(segments: list[SpeakerSegment]) -> dict[str, str]:
    """Raw label → ``SPEAKER_N`` by first appearance in time, whatever the engine's own numbering."""
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
