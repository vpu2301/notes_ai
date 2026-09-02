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
from asr_models.output import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
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


# ── Word-level attribution: segments split where the speaker changes ──


class _TimelineDiarization:
    """Answers attribute() from a speaker timeline (ms ranges)."""

    def __init__(self, timeline: list[tuple[int, int, str]]) -> None:
        self._timeline = timeline
        self.speakers = []
        for _, _, label in timeline:
            if label not in self.speakers:
                self.speakers.append(label)

    def attribute(self, start_ms: int, end_ms: int) -> str | None:
        mid = (start_ms + end_ms) // 2
        for lo, hi, label in self._timeline:
            if lo <= mid < hi:
                return label
        return None


def _words(spec: list[tuple[str, int, int]], prob: float = 0.9) -> list[WordTiming]:
    return [WordTiming(text=t, start_ms=s, end_ms=e, probability=prob) for t, s, e in spec]


def test_segment_spanning_two_speakers_is_split_at_the_word_boundary() -> None:
    seg = Segment(
        text="So that's the plan. Sounds good.",
        start_ms=0,
        end_ms=3000,
        words=_words(
            [
                ("So", 0, 200),
                ("that's", 200, 500),
                ("the", 500, 700),
                ("plan.", 700, 1200),
                ("Sounds", 1800, 2300),
                ("good.", 2300, 3000),
            ]
        ),
        avg_confidence=0.9,
    )
    diar = _TimelineDiarization([(0, 1500, "SPEAKER_1"), (1500, 3000, "SPEAKER_2")])

    got = _apply_diarization(_output([seg]), diar)  # type: ignore[arg-type]

    assert [(s.speaker, s.text, s.start_ms, s.end_ms) for s in got.segments] == [
        ("SPEAKER_1", "So that's the plan.", 0, 1200),
        ("SPEAKER_2", "Sounds good.", 1800, 3000),
    ]
    assert [len(s.words) for s in got.segments] == [4, 2]
    assert got.speakers == ["SPEAKER_1", "SPEAKER_2"]


def test_unattributed_words_inherit_agreeing_neighbours_and_islands_fold() -> None:
    seg = Segment(
        text="one two three four five",
        start_ms=0,
        end_ms=5000,
        words=_words(
            [
                ("one", 0, 1000),
                ("two", 1000, 2000),
                ("three", 2000, 3000),
                ("four", 3000, 4000),
                ("five", 4000, 5000),
            ]
        ),
        avg_confidence=0.9,
    )
    # "two" unattributed (gap in the timeline); "four" a one-word island
    # of SPEAKER_2 inside SPEAKER_1's run → both smoothed to SPEAKER_1.
    diar = _TimelineDiarization(
        [
            (0, 1000, "SPEAKER_1"),
            (2000, 3000, "SPEAKER_1"),
            (3000, 4000, "SPEAKER_2"),
            (4000, 5000, "SPEAKER_1"),
        ]
    )

    got = _apply_diarization(_output([seg]), diar)  # type: ignore[arg-type]

    assert len(got.segments) == 1
    assert got.segments[0].speaker == "SPEAKER_1"
    assert got.segments[0].text == "one two three four five"
    assert got.speakers == ["SPEAKER_1"]


def test_leading_unattributed_words_take_the_following_speaker() -> None:
    seg = Segment(
        text="uh so yes",
        start_ms=0,
        end_ms=3000,
        words=_words([("uh", 0, 1000), ("so", 1000, 2000), ("yes", 2000, 3000)]),
        avg_confidence=0.9,
    )
    diar = _TimelineDiarization([(2000, 3000, "SPEAKER_2")])

    got = _apply_diarization(_output([seg]), diar)  # type: ignore[arg-type]

    assert [(s.speaker, s.text) for s in got.segments] == [("SPEAKER_2", "uh so yes")]


def test_segment_without_word_timings_falls_back_to_span_attribution() -> None:
    seg = Segment(text="hello there", start_ms=0, end_ms=1000, avg_confidence=0.9)
    diar = _TimelineDiarization([(0, 1000, "SPEAKER_1")])

    got = _apply_diarization(_output([seg]), diar)  # type: ignore[arg-type]

    assert [(s.speaker, s.text) for s in got.segments] == [("SPEAKER_1", "hello there")]


def test_roster_lists_only_speakers_that_reached_the_transcript() -> None:
    seg = Segment(text="hello", start_ms=0, end_ms=1000, avg_confidence=0.9)
    diar = _TimelineDiarization([(0, 1000, "SPEAKER_1"), (5000, 6000, "SPEAKER_2")])

    got = _apply_diarization(_output([seg]), diar)  # type: ignore[arg-type]

    assert got.speakers == ["SPEAKER_1"]
