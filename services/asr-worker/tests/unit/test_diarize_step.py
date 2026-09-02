"""The diarize=true batch step: attribution merge + failure classification.

The heavy pipeline (VAD → embeddings → clustering) is covered in
libs/diarization; here the worker-side promises are held:

* every segment gets the diarizer's answer for its span — including
  ``None`` when the diarizer declines — and the roster rides along;
* an unavailable speaker model is retryable (another worker may have the
  weights), a diarizer crash on decoded samples is terminal (determinism:
  a redelivery redoes a full Whisper pass to reach the same crash).
"""

from __future__ import annotations

import pytest

from asr_models import JobErrorKind
from asr_models.output import Segment, TranscriptionMetadata, TranscriptionOutput
from asr_worker.processor import (
    _apply_diarization,
    _classified,
    _NonRetryableError,
    _RetryableError,
)


class _StubDiarization:
    """Answers attribute() from a fixed span→label table."""

    def __init__(self, spans: dict[tuple[int, int], str | None], speakers: list[str]) -> None:
        self._spans = spans
        self.speakers = speakers

    def attribute(self, start_ms: int, end_ms: int) -> str | None:
        return self._spans.get((start_ms, end_ms))


def _output(segments: list[Segment]) -> TranscriptionOutput:
    return TranscriptionOutput(
        language="en",
        segments=segments,
        metadata=TranscriptionMetadata(
            model="tiny",
            vad_seconds_speech=1.0,
            infer_seconds=0.5,
            beam_size=5,
        ),
    )


def test_apply_diarization_attributes_each_segment_and_keeps_roster() -> None:
    out = _output(
        [
            Segment(text="hello", start_ms=0, end_ms=1000, avg_confidence=0.9),
            Segment(text="hi there", start_ms=1200, end_ms=2400, avg_confidence=0.9),
            Segment(text="mm", start_ms=2500, end_ms=2600, avg_confidence=0.5),
        ]
    )
    diar = _StubDiarization(
        spans={
            (0, 1000): "SPEAKER_1",
            (1200, 2400): "SPEAKER_2",
            # (2500, 2600) absent → attribution declined → None
        },
        speakers=["SPEAKER_1", "SPEAKER_2"],
    )

    got = _apply_diarization(out, diar)  # type: ignore[arg-type]

    assert [s.speaker for s in got.segments] == ["SPEAKER_1", "SPEAKER_2", None]
    assert got.speakers == ["SPEAKER_1", "SPEAKER_2"]
    # The original output is untouched (model_copy, not mutation).
    assert all(s.speaker is None for s in out.segments)
    assert out.speakers == []


def test_apply_diarization_without_speech_evidence_yields_empty_roster() -> None:
    out = _output([Segment(text="hum", start_ms=0, end_ms=400, avg_confidence=0.4)])
    diar = _StubDiarization(spans={}, speakers=[])

    got = _apply_diarization(out, diar)  # type: ignore[arg-type]

    assert got.speakers == []
    assert got.segments[0].speaker is None


@pytest.mark.parametrize(
    "kind,expected",
    [
        (JobErrorKind.DIARIZATION_UNAVAILABLE, _RetryableError),
        (JobErrorKind.DIARIZATION_FAILED, _NonRetryableError),
    ],
)
def test_diarization_failure_classification(kind: JobErrorKind, expected: type) -> None:
    assert isinstance(_classified(kind, "detail"), expected)
