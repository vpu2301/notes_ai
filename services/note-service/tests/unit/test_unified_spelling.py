"""The note is built from the unified view asr-service's spelling overlay
produces: quotes carry the unified spelling, and ``meeting_doc.entities`` tier
(a) finds the name the recording spells.
"""

from __future__ import annotations

from note_service.domain.meeting_doc import entities, support, windows

# What /result returns once the overlay is applied (raw: "Andala", "Handela").
UNIFIED = {
    "language": "de",
    "turns": [
        {"speaker": "SPEAKER_1", "name": "Erzähler", "start_ms": 0, "end_ms": 5000,
         "paragraphs": ["Heute geht es um Handala und seine Geschichte."]},
        {"speaker": "SPEAKER_2", "name": "Gast", "start_ms": 5000, "end_ms": 9000,
         "paragraphs": ["Die Figur Handala wurde 1969 erfunden."]},
        {"speaker": "SPEAKER_1", "name": "Erzähler", "start_ms": 9000, "end_ms": 12000,
         "paragraphs": ["Viele kennen Handala aus Karikaturen."]},
    ],
}  # fmt: skip


def test_a_quote_from_the_unified_view_carries_the_unified_spelling() -> None:
    turns = windows.turns_from_result(UNIFIED)
    quotes = [t.text for t in turns]
    assert all("Handala" in q for q in quotes)
    assert not any(v in q for q in quotes for v in ("Andala", "Handela"))


def test_tier_a_corrects_a_line_that_still_says_a_variant() -> None:
    names = support.recording_names([t.text for t in windows.turns_from_result(UNIFIED)])
    assert "Handala" in names
    corrected, applied, _marked = entities.correct(
        "Andala wurde zum Symbol.", recording_names=names
    )
    assert corrected == "Handala wurde zum Symbol."
    assert [(c.surface, c.canonical) for c in applied] == [("Andala", "Handala")]
