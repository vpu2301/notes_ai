"""Sprint 30: turns in artifact index space, and which turns are uncertain."""

from __future__ import annotations

from asr_models import EnrichedSegment, build_turns


def _seg(
    speaker: str | None, start: int, end: int, *, artifact: list[int], **kw: object
) -> EnrichedSegment:
    return EnrichedSegment(
        text="x.",
        raw_text="x.",
        start_ms=start,
        end_ms=end,
        avg_confidence=0.9,
        speaker=speaker,
        artifact_index=artifact[0],
        artifact_indices=artifact,
        **kw,  # type: ignore[arg-type]
    )


def test_turn_indices_are_artifact_indices_not_positions() -> None:
    segments = [
        _seg("SPEAKER_1", 0, 1000, artifact=[0, 1]),  # absorbed a punctuation segment
        _seg("SPEAKER_2", 1000, 2000, artifact=[2]),
    ]

    turns = build_turns(segments)

    assert [t.segment_indices for t in turns] == [[0, 1], [2]]


def test_overlap_smoothing_and_absorption_make_a_turn_uncertain() -> None:
    segments = [
        _seg("SPEAKER_1", 0, 1000, artifact=[0]),
        _seg("SPEAKER_2", 1000, 2000, artifact=[1]),
        _seg("SPEAKER_1", 2000, 3000, artifact=[2], speaker_uncertain=True),
        _seg("SPEAKER_2", 3000, 4000, artifact=[3]),
        _seg(None, 4000, 4500, artifact=[4]),
        _seg("SPEAKER_2", 4500, 5000, artifact=[5]),
    ]

    turns = build_turns(segments, overlap_ms=[(1500, 1600)])

    assert [(t.speaker, t.uncertain) for t in turns] == [
        ("SPEAKER_1", False),
        ("SPEAKER_2", True),  # people talked over each other
        ("SPEAKER_1", True),  # label smoothed by the worker
        ("SPEAKER_2", True),  # absorbed an unattributed segment
    ]


def test_segments_without_artifact_indices_use_their_position() -> None:
    plain = EnrichedSegment(text="a", raw_text="a", start_ms=0, end_ms=1, avg_confidence=0.9)

    assert build_turns([plain])[0].segment_indices == [0]
