"""Sprint I2 T4: a turn is never in two languages."""

from __future__ import annotations

from asr_models import Segment, build_turns


def _seg(text: str, start: int, speaker: str | None = "SPEAKER_1", language: str | None = None):
    return Segment(
        text=text,
        start_ms=start,
        end_ms=start + 900,
        avg_confidence=0.9,
        speaker=speaker,
        language=language,
    )


def test_a_speaker_run_breaks_where_the_language_changes() -> None:
    turns = build_turns(
        [
            _seg("We looked at the flybridge.", 0),
            _seg("Що це таке?", 1_000, language="uk"),
            _seg("Відчини двері, будь ласка.", 2_000, language="uk"),
            _seg("And the tender garage.", 3_000),
        ]
    )
    assert [(t.language, t.paragraphs) for t in turns] == [
        (None, ["We looked at the flybridge."]),
        ("uk", ["Що це таке? Відчини двері, будь ласка."]),
        (None, ["And the tender garage."]),
    ]
    assert all(t.speaker == "SPEAKER_1" for t in turns)
    assert [t.segment_indices for t in turns] == [[0], [1, 2], [3]]


def test_without_languages_the_structure_is_unchanged() -> None:
    turns = build_turns([_seg("one", 0), _seg("two", 1_000)])
    assert len(turns) == 1 and turns[0].language is None
