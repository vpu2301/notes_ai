"""A passage in another language is excluded by code, from
the ASR's own per-segment language, and the extractor sees it tagged."""

from __future__ import annotations

from note_service.domain.meeting_doc import pipeline, verify, windows
from note_service.domain.meeting_doc.windows import Turn, Window


def _turn(number: int, text: str, start: int, language: str | None = None) -> Turn:
    return Turn(
        index=number,
        speaker_label="SPEAKER_1",
        speaker_name="Mitchell",
        text=text,
        start_ms=start,
        end_ms=start + 4_000,
        line=number,
        language=language,
    )


ENGLISH = "The flybridge has the second helm and the tender garage takes a Williams 345."
UKRAINIAN = "Що це таке? Відчини двері, будь ласка, і подивись на другий пульт."


def test_turns_from_the_result_view_carry_the_language_only_when_it_differs() -> None:
    result = {
        "language": "en",
        "turns": [
            {
                "speaker": "SPEAKER_1",
                "name": "M",
                "start_ms": 0,
                "end_ms": 4000,
                "paragraphs": [ENGLISH],
            },
            {
                "speaker": "SPEAKER_1",
                "name": "M",
                "start_ms": 5000,
                "end_ms": 9000,
                "paragraphs": [UKRAINIAN],
                "language": "uk",
            },
            {
                "speaker": "SPEAKER_1",
                "name": "M",
                "start_ms": 10000,
                "end_ms": 12000,
                "paragraphs": ["More"],
                "language": "en",
            },
        ],
    }
    turns = windows.turns_from_result(result)
    assert [t.language for t in turns] == [None, "uk", None]


def test_segments_in_another_language_are_not_merged_into_the_neighbouring_turn() -> None:
    result = {
        "language": "en",
        "segments": [
            {"speaker": "SPEAKER_1", "text": "one", "start_ms": 0, "end_ms": 1000},
            {
                "speaker": "SPEAKER_1",
                "text": "два",
                "start_ms": 1000,
                "end_ms": 2000,
                "language": "uk",
            },
            {"speaker": "SPEAKER_1", "text": "three", "start_ms": 2000, "end_ms": 3000},
        ],
    }
    turns = windows.turns_from_result(result)
    assert [(t.text, t.language) for t in turns] == [("one", None), ("два", "uk"), ("three", None)]


def test_the_window_tags_the_line_for_the_extractor() -> None:
    window = Window(index=0, turns=(_turn(0, ENGLISH, 0), _turn(1, UKRAINIAN, 5_000, "uk")))
    lines = window.render().splitlines()
    assert lines[0].startswith("[0] Mitchell (00:00): The flybridge")
    assert lines[1].startswith("[1] Mitchell (00:05): [uk] Що це таке?")


def test_the_language_field_confirms_the_exclusion_without_the_heuristic() -> None:
    # Too short for the script heuristic (< 20 words): the field decides.
    piece = _turn(1, "Так, добре.", 5_000, "uk")
    window = Window(index=0, turns=(_turn(0, ENGLISH, 0), piece))
    confirmed, advisory = verify.confirm_noise(
        [(1, "other_language")], window=window, language="en"
    )
    assert [e.line for e in confirmed] == [1] and advisory == []
    # Same words, no field: the heuristic alone cannot prove it.
    unlabelled = Window(index=0, turns=(_turn(0, ENGLISH, 0), _turn(1, "Так, добре.", 5_000)))
    confirmed, advisory = verify.confirm_noise(
        [(1, "other_language")], window=unlabelled, language="en"
    )
    assert confirmed == [] and advisory == ["other_language"]


def test_the_field_never_confirms_the_recordings_own_language() -> None:
    window = Window(index=0, turns=(_turn(0, ENGLISH, 0, "en"),))
    confirmed, _ = verify.confirm_noise([(0, "other_language")], window=window, language="en")
    assert confirmed == []


def test_code_flags_other_language_lines_whether_or_not_the_model_did() -> None:
    window = Window(index=0, turns=(_turn(0, ENGLISH, 0), _turn(1, UKRAINIAN, 5_000, "uk")))
    assert pipeline._language_lines(window, "en") == [(1, 5_000, 9_000, "other_language")]
    assert pipeline._language_lines(window, "uk") == []


def test_split_pieces_keep_the_turns_language() -> None:
    long = Turn(
        index=0,
        speaker_label="S",
        speaker_name=None,
        text=(UKRAINIAN + " ") * 60,
        start_ms=0,
        end_ms=60_000,
        language="uk",
    )
    pieces = windows.split_long_turn(long)
    assert len(pieces) > 1 and all(p.language == "uk" for p in pieces)


# ── T3: quotes verify against the displayed and the raw text ──


def test_normalise_quote_drops_the_fillers_the_display_hides() -> None:
    import json
    from pathlib import Path

    from note_service.domain.meeting_doc.verify import FILLERS, normalise_quote

    fixture = json.loads(
        (
            Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "nlp" / "fillers.json"
        ).read_text("utf-8")
    )
    assert frozenset().union(*(set(v) for v in fixture["fillers"].values())) == FILLERS
    raw = "uh so this is, um, the swim platform. Uh-huh."
    shown = "So this is, the swim platform."
    assert normalise_quote(raw) == normalise_quote(shown) == "so this is the swim platform"
    assert normalise_quote("I'll er go") == "i'll go"
