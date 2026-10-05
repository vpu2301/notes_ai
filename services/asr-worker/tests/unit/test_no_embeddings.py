"""Speaker embeddings are biometric data: none may leave ``diarize()``.

Sprint 29 B-8 / acceptance 5. Both engines see embeddings (legacy: one
per chunk; v2: one centroid per speaker) and both feed them to the roster
guard. This drives a real labelling of each engine through the worker's
own attribution and stats, then scans everything that is stored or
emitted for anything vector-shaped: no list of more than 32 floats,
anywhere, at any depth.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from asr_models.output import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker.processor import _apply_diarization, _diarization_stats
from diarization import (
    DiarizationHints,
    OfflineDiarizationConfig,
    RosterGuardConfig,
    diarize_embeddings,
)
from diarization.pyannote_engine import PipelineResult, to_diarization

MAX_FLOATS = 32
DIM = 192  # ECAPA's embedding size — and roughly pyannote's


def _vectors_in(value: Any, path: str = "$") -> list[str]:
    """Paths of every list holding more than MAX_FLOATS floats."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found += _vectors_in(child, f"{path}.{key}")
    elif isinstance(value, list):
        floats = [v for v in value if isinstance(v, float)]
        if len(floats) > MAX_FLOATS:
            found.append(path)
        for i, child in enumerate(value):
            found += _vectors_in(child, f"{path}[{i}]")
    return found


def _voice(axis: int, n: int) -> list[np.ndarray]:
    out = []
    for i in range(n):
        v = np.zeros(DIM)
        v[axis] = math.sqrt(0.95)
        v[100 + i % 50] = math.sqrt(0.05)
        out.append(v)
    return out


def _transcript(seconds: int) -> TranscriptionOutput:
    words = [
        WordTiming(text=f"w{t}", start_ms=t * 1000, end_ms=t * 1000 + 900, probability=0.9)
        for t in range(seconds)
    ]
    return TranscriptionOutput(
        language="en",
        segments=[
            Segment(
                text=" ".join(w.text for w in words),
                start_ms=0,
                end_ms=seconds * 1000,
                words=words,
                avg_confidence=0.9,
            )
        ],
        metadata=TranscriptionMetadata(
            model="tiny", vad_seconds_speech=float(seconds), infer_seconds=1.0, beam_size=5
        ),
    )


def _stored(output: TranscriptionOutput, diar: Any) -> dict[str, Any]:
    labelled = _apply_diarization(output, diar)
    stats = _diarization_stats(labelled, diar, 0.5)
    labelled = labelled.model_copy(
        update={"metadata": labelled.metadata.model_copy(update={"diarization": stats})}
    )
    return json.loads(labelled.model_dump_json())


def test_a_legacy_labelling_stores_no_vectors() -> None:
    vectors = _voice(0, 40) + _voice(1, 3) + _voice(2, 40)
    spans = [(i * 1000, (i + 1) * 1000) for i in range(len(vectors))]
    diar = diarize_embeddings(
        spans,
        vectors,
        duration_ms=len(vectors) * 1000,
        config=OfflineDiarizationConfig(),
        hints=DiarizationHints(),
        roster=RosterGuardConfig(),
    )

    artifact = _stored(_transcript(len(vectors)), diar)

    assert diar.roster is not None and diar.roster.speakers_dissolved == 1, "the guard used them"
    assert _vectors_in(artifact) == []
    assert all(not isinstance(v, np.ndarray) for v in vars(diar).values())


def test_a_v2_labelling_stores_no_vectors() -> None:
    rng = np.random.default_rng(0)
    centroids = {label: rng.normal(size=DIM) for label in ("S0", "S1", "S2")}
    result = PipelineResult(
        exclusive=[(0.0, 40.0, "S0"), (40.0, 43.0, "S1"), (43.0, 80.0, "S2")],
        overlaps=[(39.5, 40.5)],
        centroids=centroids,
    )
    diar = to_diarization(
        result,
        duration_ms=80_000,
        hints=DiarizationHints(),
        roster=RosterGuardConfig(),
        config=OfflineDiarizationConfig(),
        engine_version="test",
    )

    artifact = _stored(_transcript(80), diar)

    assert _vectors_in(artifact) == []
    assert all(not isinstance(v, np.ndarray) for v in vars(diar).values())
    assert all(not isinstance(v, dict) or not v for v in vars(diar.roster).values())


def test_the_scanner_would_catch_a_leaked_embedding() -> None:
    leaked = {"metadata": {"diarization": {"centroid": [0.1] * DIM}}}

    assert _vectors_in(leaked) == ["$.metadata.diarization.centroid"]
