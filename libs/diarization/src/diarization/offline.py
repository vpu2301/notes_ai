"""Offline diarization of a full decoded recording (Ambient Capture v1).

Batch counterpart of dictation-service's streaming diarizer, built from
the same front-end primitives so the two paths cannot drift:

    full PCM → Silero speech regions → ≤1.2 s chunks → ECAPA embeddings
    → agglomerative clustering over the WHOLE recording
    → contiguous speaker turns + a majority-overlap ``attribute()`` helper

Chunking (1200/250 ms) mirrors the streaming ``DiarizationConfig``; it
was calibrated once (ADR-0034) and a recording diarized live and
re-diarized in batch should agree on where the chunks fall.

Clustering differs from the streaming path on purpose (ADR-0045). A live
session must decide speaker-by-speaker as audio arrives, so it runs an
online 2-slot clusterer; a batch job holds every embedding of the
recording up front and can afford a global answer: average-linkage
agglomerative clustering on cosine similarity, cut at the same
same-voice/cross-voice boundary the streaming thresholds encode. That
lifts the 2-speaker pilot cap — a podcast with a host and three guests
comes out as four speakers, not two speakers plus a lot of UNKNOWN.

Labels are neutral ``SPEAKER_1..N`` in first-appearance order (AMBIENT
spec §5). ``UNKNOWN`` evidence stays on the internal timeline (it still
counts as coverage for attribution) but is never surfaced as a turn —
ambiguous audio yields ``None``, never a guess.
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

# Recorded on every diarized job (``DiarizationStats``) so a result can
# always be traced to the engine that produced it.
ENGINE_ID = "legacy-ecapa-ahc"
ENGINE_VERSION = "spkrec-ecapa-voxceleb@0f99f2d"


@dataclass(frozen=True)
class OfflineClusteringConfig:
    """Agglomerative clustering knobs for the batch path.

    ``link_threshold`` is the average-linkage cosine at which two clusters
    stop being merged — the same boundary ADR-0034 measured between
    same-voice chunk similarities (≥ ~0.5) and cross-voice ones (≤ ~0.45).
    Chunk-to-chunk similarity is noisy (1.2 s of speech), so a speaker's
    outliers can end up in small side clusters; ``centroid_merge_threshold``
    folds those back — centroids average the noise out, so two clusters
    of one voice sit far above it while two voices stay well below.
    Everything else guards the roster: a "speaker" made of a few stray
    chunks is dissolved into the nearest real speaker (or left UNKNOWN),
    and the roster is capped so a recording full of crosstalk cannot
    explode into dozens of labels.
    """

    link_threshold: float = 0.45
    centroid_merge_threshold: float = 0.60
    max_speakers: int = 8
    # A cluster needs at least this many chunks (≈ seconds of speech) to
    # count as a speaker of its own (mirrors the streaming ``min_split_mass``)…
    min_speaker_chunks: int = 2
    # …and at least this share of all chunks: in a 40-minute recording a
    # voice heard for six seconds is a bystander, not a participant.
    min_speaker_share: float = 0.01
    # Floor in seconds of speech (sum of the cluster's chunk durations);
    # 0 disables it. A participant, not a cough (Sprint 28 B-4).
    min_speaker_speech_ms: int = 0
    # Chunks shorter than this are scored against the centroids but do
    # not take part in forming clusters; 0 = every chunk forms clusters.
    cluster_chunk_min_ms: int = 0
    # Per-chunk scoring against the final centroids (streaming vocabulary,
    # ADR-0034): below the floor vs every centroid → UNKNOWN; nearer than
    # the margin to the runner-up → UNKNOWN.
    assign_floor: float = 0.45
    ambiguity_margin: float = 0.08
    margin_scale: float = 0.30
    # Agglomeration holds an n×n similarity matrix. Above this many chunks
    # the clusters are learnt on an evenly spaced sample and every chunk
    # is then scored against the learnt centroids — a 3-hour recording
    # still finishes in seconds, deterministically.
    max_cluster_chunks: int = 1500
    # With an exact count from a person, still join clusters whose centroids
    # are the same voice (so an overstated count cannot invent speakers).
    # Off = the stated count is taken literally.
    hint_same_voice_merge: bool = True


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
    # Kept for callers that read the streaming calibration off this
    # config (chunk thresholds, split boundary); the batch clusterer
    # itself is configured by ``offline_clustering``.
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
    """Result of :func:`diarize_offline`: the turn list plus attribution.

    ``turns``     — contiguous, non-overlapping, chronological.
    ``speakers``  — distinct labels in first-appearance order.
    ``attribute`` — majority-overlap speaker for a transcript span.

    Every engine behind the :class:`~diarization.protocol.Diarizer` seam
    returns this shape (Sprint 29): ``engine``/``engine_version`` say who
    made it, ``hints`` what a person asked for, ``roster`` what the guard
    did, ``overlap_ms`` where two people spoke at once (empty for the
    legacy engine, which cannot tell). Numbers and labels only — never an
    embedding.
    """

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
        # Sprint 31, dual-channel captures only: display label → "local" |
        # "remote", and the channel analysis summary for the stats.
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
    """Diarize a whole recording of float32 mono PCM.

    The models are 16 kHz-only; callers own resampling (the batch worker
    already decodes to 16 kHz for Whisper), so any other rate raises
    rather than silently mislabeling time.

    ``hints`` steer the clusterer (exact count / cap); ``roster`` switches
    on the Sprint 29 roster guard — ``None`` keeps the Sprint 28 roster
    exactly (the eval baselines depend on that).
    """
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
    """VAD → chunking → one embedding per chunk. Split from clustering so
    the eval grid can re-cluster cached embeddings without re-embedding."""
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
    # Centroids live for this call only: the guard folds a dissolved
    # speaker into the voice it sounds like, then they are gone.
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


# The guard with its floor off: grades the count, dissolves nothing.
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
    """Label every chunk embedding ``S1..Sk`` (or ``UNKNOWN``) with a confidence.

    1. Average-linkage agglomerative clustering on cosine similarity,
       cut at ``link_threshold`` (learnt on an evenly spaced sample when
       the recording is long).
    2. Clusters whose centroids are still near-identical are merged
       (one voice that agglomeration split on chunk noise).
    3. Clusters too small to be a speaker are dissolved; the roster is
       capped at ``max_speakers`` (largest clusters win).
    4. Every chunk is scored against the surviving centroids with the
       streaming assignment rule (floor + ambiguity margin → UNKNOWN),
       which is also what folds dissolved-cluster chunks into their
       nearest real speaker.

    Deterministic: ties break on the lowest index (stream order), and
    speaker numbering follows first appearance. Returns internal ``S<n>``
    labels; the caller renders ``SPEAKER_<n>`` by first appearance.
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
    """:func:`cluster_embeddings` plus the :class:`ClusterStats` behind it.

    ``durations_ms`` (one per chunk) enables the duration-based knobs
    (``min_speaker_speech_ms``, ``cluster_chunk_min_ms``); without it
    they are ignored.

    Hints (Sprint 29), so both engines answer the same question:
    ``num_speakers=k`` agglomerates until exactly ``k`` clusters remain,
    whatever the threshold says, and keeps them all — no speaker floor (a
    person's count wins). The same-voice centroid merge still runs. ``max_speakers`` keeps
    merging past the threshold until the roster fits under the cap. Fewer
    chunks than ``k`` yields fewer speakers: nothing is invented.
    """
    n = len(embeddings)
    if n == 0:
        return [], [], ClusterStats()
    if durations_ms is not None and len(durations_ms) != n:
        raise ValueError("durations_ms must have one entry per embedding")
    if num_speakers is None and max_speakers is not None:
        # A cap is a ceiling, by construction: when the uncapped answer
        # already fits under it, that answer is returned unchanged. A
        # calendar cap can then never under-count what the engine got right
        # (Sprint 30 C2 — measured on the gold replay).
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
        # A count is a count of PEOPLE. Stray chunks (a cough, a door) are
        # dissimilar to everyone and would survive a merge-until-k run while
        # two real voices got merged instead. So find them first with the
        # ordinary threshold run, and let only the rest form the k clusters;
        # the stray chunks are still scored against the final centroids
        # below (nearest speaker, or UNKNOWN).
        # Dust is judged AFTER the same-voice merge: far-field audio splits
        # one real speaker into many small fragments that the merge joins
        # again, and judging before it threw real speech away (gold replay).
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
        # Only reached when the uncapped roster was over the cap: merge it
        # down among real speakers (the dust is out).
        assignments = _average_linkage(learn, cfg.link_threshold, target=cap)
    else:
        assignments = _average_linkage(learn, cfg.link_threshold, target=num_speakers)
    clusters_raw = len(set(assignments))
    # Runs with a count too: agglomerating down to k can leave one voice
    # split across clusters when the recording holds fewer than k people,
    # and this merge is what keeps an impossible count from inventing
    # speakers (it only joins clusters that are the same voice).
    if num_speakers is None or cfg.hint_same_voice_merge:
        assignments = _merge_close_centroids(learn, assignments, cfg.centroid_merge_threshold)
    clusters_after_merge = len(set(assignments))

    # Cluster sizes on the sample → drop dust, cap the roster.
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
        # Nothing reached the speaker floor (a tiny recording). Keep the
        # biggest cluster so a 2-second voice memo still has a speaker.
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
    # Speaker numbers follow first appearance in time, not cluster size.
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
    """Agglomerate rows of ``unit`` (L2-normalised) by average linkage on
    cosine similarity until the closest pair falls below ``threshold``.

    ``target`` replaces the threshold with a count: merge until exactly
    that many clusters remain. ``cap`` keeps merging below the threshold
    while more than ``cap`` clusters remain.

    Returns a cluster id per row. Lance–Williams update keeps the
    linkage exact without recomputing pair sums: the similarity between a
    merged cluster and any other is the size-weighted mean of its parts.
    Each row remembers its best partner, so an iteration costs O(n) plus
    the rows whose best partner was touched — O(n²) overall, not O(n³).
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
        # Weighted average of the two rows against everyone else.
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
        # Refresh best partners: the survivor, the dead row, every row
        # whose best partner was one of them, and any row for which the
        # survivor's new similarity now beats its old best.
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
    """Merge clusters whose centroids are at least ``threshold`` alike,
    closest pair first, until none are. Chunk-level agglomeration can
    leave one voice in a main cluster plus outlier side clusters; their
    centroids agree far more than two different voices ever do."""
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
    """Raw label → ``SPEAKER_N``, numbered by first appearance in time.

    The clusterer already numbers by first appearance, but this keeps the
    promise in the wire contract independent of how the labels were made:
    SPEAKER_1 is whoever spoke first.
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
