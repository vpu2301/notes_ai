"""v2 engine: pyannote ``speaker-diarization-community-1``, in-process from a digest-verified local dir.

Rules: refuse to load unless ``PYANNOTE_METRICS_ENABLED=false`` and ``HF_HUB_OFFLINE=1`` (pyannote 4.x phones
home by default); in-memory waveform only; exclusive timeline with overlaps at confidence 0.5; embeddings are
biometric and never leave the call. pyannote/torch are imported lazily so the mapping is testable without them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .attribution import SpeakerSegment
from .engine import DiarizationUnavailableError
from .integrity import verify_model_dir
from .offline import (
    SAMPLE_RATE_HZ,
    ClusterStats,
    OfflineDiarization,
    OfflineDiarizationConfig,
    _assign_display_names,
)
from .protocol import DiarizationHints
from .roster import RosterGuardConfig, guard_roster

logger = logging.getLogger(__name__)

ENGINE_ID = "pyannote-community-1"
# Confidence of the exclusive label where two voices overlapped.
OVERLAP_CONFIDENCE = 0.5
# An exact count forces that many clusters; same-voice centroids are rejoined so a count can only
# yield FEWER speakers. PROVISIONAL: not calibrated on community-1 embeddings (ADR-0052).
SAME_VOICE_COSINE = 0.75


@dataclass(frozen=True)
class PipelineResult:
    """What is kept from pyannote's ``DiarizeOutput`` (seconds); ``centroids`` per label, in memory only."""

    exclusive: Sequence[tuple[float, float, str]]
    overlaps: Sequence[tuple[float, float]]
    centroids: Mapping[str, np.ndarray] | None = None


def to_diarization(
    result: PipelineResult,
    *,
    duration_ms: int,
    hints: DiarizationHints,
    roster: RosterGuardConfig | None,
    config: OfflineDiarizationConfig,
    engine_version: str,
) -> OfflineDiarization:
    """pyannote output → the structure the worker's attribution consumes."""
    overlap_ms = _merge_spans(
        [(round(a * 1000), round(b * 1000)) for a, b in result.overlaps if b > a]
    )
    same_voice = _same_voice_labels(result.centroids) if hints.exact and result.centroids else {}
    segments: list[SpeakerSegment] = []
    for start_s, end_s, label in sorted(result.exclusive):
        start, end = round(start_s * 1000), round(end_s * 1000)
        if end <= start:
            continue
        label = same_voice.get(str(label), str(label))
        segments.extend(_split_on_overlap(start, end, label, overlap_ms))
    outcome = guard_roster(
        segments,
        config=roster or RosterGuardConfig(min_speaker_speech_ms=0, min_speaker_share=0.0),
        hints=hints,
        centroids=result.centroids,
        overlap_ms=overlap_ms,
    )
    raw_speakers = len({s.label for s in segments})
    return OfflineDiarization(
        segments=outcome.segments,
        display_names=_assign_display_names(outcome.segments),
        duration_ms=duration_ms,
        config=config,
        # Legacy vocabulary: one "chunk" per exclusive segment; no separate merge step, the guard drops.
        stats=ClusterStats(
            chunks=len(segments),
            clusters_raw=raw_speakers,
            clusters_after_merge=raw_speakers,
            clusters_dropped=outcome.speakers_dissolved,
        ),
        engine=ENGINE_ID,
        engine_version=engine_version,
        hints=hints,
        roster=outcome,
        overlap_ms=overlap_ms,
    )


class PyannoteDiarizer:
    engine = ENGINE_ID
    remote = False

    def __init__(
        self,
        *,
        model_dir: str,
        environ: Mapping[str, str],
        device: str = "cpu",
        pins: dict[str, str] | None = None,
        model_repo: str = "",
        model_revision: str = "",
        batch_size: int = 16,
        roster: RosterGuardConfig | None = None,
        offline_config: OfflineDiarizationConfig | None = None,
    ) -> None:
        self._model_dir = model_dir
        self._environ = environ
        self._device = device
        self._pins = pins or {}
        self._model_repo = model_repo
        self._model_revision = model_revision
        self._batch_size = batch_size
        self._roster = roster
        self._config = offline_config or OfflineDiarizationConfig()
        self._pipeline: Any = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None
        self.engine_version = f"community-1@{model_revision or 'unpinned'}"

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _environment_problem(self) -> str | None:
        """Why the process environment is unsafe to load pyannote in, if it is."""
        if self._environ.get("PYANNOTE_METRICS_ENABLED", "").strip().lower() not in {"false", "0"}:
            return "telemetry_not_disabled"
        if self._environ.get("HF_HUB_OFFLINE", "").strip().lower() not in {"1", "true"}:
            return "hub_not_offline"
        return None

    async def ensure_loaded(self) -> None:
        if self._pipeline is not None:
            return
        async with self._lock:
            if self._pipeline is not None:
                return
            problem = self._environment_problem()
            if problem is not None:
                self._last_error = problem
                logger.error("diarization.v2_refused", extra={"reason": problem})
                raise DiarizationUnavailableError(problem)
            try:
                await asyncio.to_thread(
                    verify_model_dir,
                    self._model_dir,
                    pins=self._pins,
                    repo=self._model_repo,
                    revision=self._model_revision,
                    required_files=("config.yaml",),
                )
                pipeline, version = await asyncio.to_thread(self._load)
            except Exception as exc:  # torch/pyannote errors are varied; fail loud, typed
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "diarization.load_failed",
                    extra={
                        "engine": ENGINE_ID,
                        "model_dir": self._model_dir,
                        "error_class": type(exc).__name__,
                    },
                )
                raise DiarizationUnavailableError(
                    f"{ENGINE_ID} failed to load from {self._model_dir}: {type(exc).__name__}"
                ) from exc
            self._pipeline = pipeline
            self.engine_version = version
            self._last_error = None
            logger.info(
                "diarization.loaded",
                extra={"engine": ENGINE_ID, "model_dir": self._model_dir, "device": self._device},
            )

    def _load(self) -> tuple[Any, str]:
        import pyannote.audio
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(self._model_dir)
        pipeline.to(torch.device(self._device))
        # Bounds memory on long recordings (MDX_DIAR_V2_BATCH).
        if hasattr(pipeline, "embedding_batch_size"):
            pipeline.embedding_batch_size = self._batch_size
        version = (
            f"community-1@{self._model_revision or 'unpinned'}"
            f"+pyannote.audio-{getattr(pyannote.audio, '__version__', 'unknown')}"
        )
        return pipeline, version

    def diarize(
        self,
        pcm: np.ndarray,
        sample_rate_hz: int,
        *,
        hints: DiarizationHints,
        roster: RosterGuardConfig | None = None,
    ) -> OfflineDiarization:
        """``roster`` overrides the floor for this call only (the server carries the caller's policy per request)."""
        if self._pipeline is None:
            raise DiarizationUnavailableError("diarizer not loaded; call ensure_loaded() first")
        if sample_rate_hz != SAMPLE_RATE_HZ:
            raise ValueError(f"{ENGINE_ID} requires {SAMPLE_RATE_HZ} Hz mono PCM")
        import torch

        hints = hints.validated()
        kwargs = {
            key: value
            for key, value in (
                ("num_speakers", hints.num_speakers),
                ("min_speakers", hints.min_speakers),
                ("max_speakers", hints.max_speakers),
            )
            if value is not None
        }
        waveform = torch.from_numpy(np.ascontiguousarray(pcm, dtype=np.float32))[None, :]
        output = self._pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE_HZ}, **kwargs)
        result = extract(output)
        del output  # the embeddings go with it
        return to_diarization(
            result,
            duration_ms=int(pcm.shape[0] * 1000 / SAMPLE_RATE_HZ),
            hints=hints,
            roster=roster if roster is not None else self._roster,
            config=self._config,
            engine_version=self.engine_version,
        )


def extract(output: Any) -> PipelineResult:
    """Read what we use off a pyannote.audio 4.0 ``DiarizeOutput``; centroids are dropped, not guessed, on a shape mismatch."""
    exclusive = [
        (float(seg.start), float(seg.end), str(label))
        for seg, _, label in output.exclusive_speaker_diarization.itertracks(yield_label=True)
    ]
    overlaps = [(float(r.start), float(r.end)) for r in output.speaker_diarization.get_overlap()]
    centroids: dict[str, np.ndarray] | None = None
    embeddings = getattr(output, "speaker_embeddings", None)
    labels = [str(label) for label in output.speaker_diarization.labels()]
    if embeddings is not None and getattr(embeddings, "shape", (0,))[0] == len(labels):
        centroids = {
            label: np.asarray(row, dtype=np.float64)
            for label, row in zip(labels, embeddings, strict=True)
            if np.all(np.isfinite(row))
        }
    return PipelineResult(exclusive=exclusive, overlaps=overlaps, centroids=centroids)


def _same_voice_labels(centroids: Mapping[str, np.ndarray]) -> dict[str, str]:
    """Label → the label it is the same voice as (closest pair first)."""
    groups = {label: [np.asarray(v, dtype=np.float64)] for label, v in centroids.items()}
    joined: dict[str, str] = {}
    while len(groups) > 1:
        labels = sorted(groups)
        means = np.stack([np.mean(groups[k], axis=0) for k in labels])
        norms = np.linalg.norm(means, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        unit = means / norms
        sims = unit @ unit.T
        np.fill_diagonal(sims, -np.inf)
        a, b = divmod(int(np.argmax(sims)), len(labels))
        if sims[a, b] < SAME_VOICE_COSINE:
            break
        keep, drop = labels[min(a, b)], labels[max(a, b)]
        groups[keep].extend(groups.pop(drop))
        joined[drop] = keep
        for k, v in list(joined.items()):
            if v == drop:
                joined[k] = keep
    return joined


def _split_on_overlap(
    start: int, end: int, label: str, overlap_ms: list[tuple[int, int]]
) -> list[SpeakerSegment]:
    pieces: list[SpeakerSegment] = []
    cursor = start
    for o_start, o_end in overlap_ms:
        if o_end <= cursor or o_start >= end:
            continue
        if o_start > cursor:
            pieces.append(
                SpeakerSegment(start_ms=cursor, end_ms=o_start, label=label, confidence=1.0)
            )
        stop = min(end, o_end)
        pieces.append(
            SpeakerSegment(
                start_ms=max(cursor, o_start),
                end_ms=stop,
                label=label,
                confidence=OVERLAP_CONFIDENCE,
            )
        )
        cursor = stop
    if cursor < end:
        pieces.append(SpeakerSegment(start_ms=cursor, end_ms=end, label=label, confidence=1.0))
    return pieces


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
