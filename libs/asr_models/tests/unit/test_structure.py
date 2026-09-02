"""Segments → speaker turns → paragraphs (``asr_models.structure``).

The structure rules are what every surface renders (web transcript tab,
macOS transcript tab, the note body), so they are pinned here once.
"""

from __future__ import annotations

from asr_models import EnrichedSegment, build_turns, default_speaker_name
from asr_models.structure import StructurePolicy


def _seg(text: str, start: int, end: int, speaker: str | None = None) -> EnrichedSegment:
    return EnrichedSegment(
        text=text, raw_text=text, start_ms=start, end_ms=end, avg_confidence=0.9, speaker=speaker
    )


def test_consecutive_same_speaker_segments_form_one_turn() -> None:
    turns = build_turns(
        [
            _seg("Let's start.", 0, 1000, "SPEAKER_1"),
            _seg("First the numbers.", 1000, 2500, "SPEAKER_1"),
            _seg("Which numbers?", 2600, 3400, "SPEAKER_2"),
        ]
    )
    assert [(t.speaker, t.name, t.paragraphs) for t in turns] == [
        ("SPEAKER_1", "Speaker 1", ["Let's start. First the numbers."]),
        ("SPEAKER_2", "Speaker 2", ["Which numbers?"]),
    ]
    assert turns[0].start_ms == 0 and turns[0].end_ms == 2500
    assert turns[0].segment_indices == [0, 1]
    assert turns[1].segment_indices == [2]


def test_custom_names_are_applied_and_defaults_fill_the_rest() -> None:
    turns = build_turns(
        [_seg("Hi.", 0, 500, "SPEAKER_1"), _seg("Hello.", 500, 1000, "SPEAKER_2")],
        speaker_names={"SPEAKER_2": "Olena"},
    )
    assert [t.name for t in turns] == ["Speaker 1", "Olena"]


def test_unattributed_gap_between_same_speaker_is_absorbed() -> None:
    turns = build_turns(
        [
            _seg("So the plan", 0, 900, "SPEAKER_1"),
            _seg("is basically", 900, 1400, None),
            _seg("to ship Friday.", 1400, 2300, "SPEAKER_1"),
        ]
    )
    assert len(turns) == 1
    assert turns[0].paragraphs == ["So the plan is basically to ship Friday."]


def test_unattributed_speech_between_different_speakers_stands_alone() -> None:
    turns = build_turns(
        [
            _seg("Any questions?", 0, 900, "SPEAKER_1"),
            _seg("(inaudible)", 900, 1400, None),
            _seg("Yes, one.", 1400, 2300, "SPEAKER_2"),
        ]
    )
    assert [(t.speaker, t.name) for t in turns] == [
        ("SPEAKER_1", "Speaker 1"),
        (None, None),
        ("SPEAKER_2", "Speaker 2"),
    ]


def test_undiarized_transcript_is_one_unattributed_turn_with_paragraphs() -> None:
    policy = StructurePolicy(pause_break_ms=1000, paragraph_min_chars=10)
    turns = build_turns(
        [
            _seg("Первый абзац здесь.", 0, 2000),
            _seg("Второй абзац после паузы.", 3500, 5000),
        ],
        policy=policy,
    )
    assert len(turns) == 1
    assert turns[0].speaker is None
    assert turns[0].paragraphs == ["Первый абзац здесь.", "Второй абзац после паузы."]


def test_long_monologue_breaks_at_sentence_ends_and_hard_limit() -> None:
    policy = StructurePolicy(
        pause_break_ms=10_000,
        paragraph_min_chars=10,
        paragraph_soft_chars=40,
        paragraph_hard_chars=80,
    )
    sentence = "This is a sentence of some length."  # 34 chars
    clause = "and it keeps going without a stop"  # 33 chars, no sentence end
    segs = [
        _seg(sentence, 0, 1000, "SPEAKER_1"),
        _seg(sentence, 1000, 2000, "SPEAKER_1"),  # 70 chars ≥ soft, ends sentence → break after
        _seg(clause, 2000, 3000, "SPEAKER_1"),
        _seg(clause, 3000, 4000, "SPEAKER_1"),
        _seg(clause, 4000, 5000, "SPEAKER_1"),  # 102 chars ≥ hard → break regardless
        _seg("Done.", 5000, 5500, "SPEAKER_1"),
    ]
    (turn,) = build_turns(segs, policy=policy)
    assert turn.paragraphs == [
        f"{sentence} {sentence}",
        f"{clause} {clause} {clause}",
        "Done.",
    ]


def test_short_pause_does_not_break_a_short_paragraph() -> None:
    turns = build_turns(
        [_seg("Yes.", 0, 300, "SPEAKER_1"), _seg("Agreed.", 4000, 4500, "SPEAKER_1")]
    )
    assert turns[0].paragraphs == ["Yes. Agreed."]


def test_empty_segments_are_skipped() -> None:
    assert build_turns([_seg("   ", 0, 100, "SPEAKER_1")]) == []
    assert build_turns([]) == []


def test_default_speaker_name() -> None:
    assert default_speaker_name("SPEAKER_1") == "Speaker 1"
    assert default_speaker_name("SPEAKER_12") == "Speaker 12"
    assert default_speaker_name("UNKNOWN") == "UNKNOWN"
