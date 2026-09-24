"""Gold format v2 and its validator (Summary Engine v2, Q1 T2)."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "tests" / "fixtures" / "eval" / "notes"
_spec = importlib.util.spec_from_file_location(
    "notes_gold", REPO / "scripts" / "eval" / "notes_gold.py"
)
assert _spec is not None and _spec.loader is not None
notes_gold = importlib.util.module_from_spec(_spec)
sys.modules["notes_gold"] = notes_gold
_spec.loader.exec_module(notes_gold)


def _m06() -> dict[str, Any]:
    return json.loads((CORPUS / "m06_de_news_podcast.json").read_text("utf-8"))


def test_the_committed_corpus_is_valid_v1_and_v2_alike() -> None:
    assert notes_gold.validate_corpus(CORPUS) == []


def test_a_v1_file_is_a_valid_v2_file() -> None:
    v1 = json.loads((CORPUS / "m01_en_product_sync.json").read_text("utf-8"))
    v1.pop("recording_type", None)  # labelled in Q3; the v1 shape has no such key
    assert notes_gold.validate_meeting(v1, "m01") == []


def test_a_surface_form_the_asr_never_produced_is_one_problem_naming_its_index() -> None:
    meeting = _m06()
    meeting["gold"]["entities"][1]["surface_forms"].append("Bernd Wolzmann")
    problems = notes_gold.validate_meeting(meeting, "m06.json")
    assert problems == ["m06.json: entities[1].surface_forms[1] not in the transcript"]


def test_a_date_nobody_said_is_a_problem() -> None:
    meeting = _m06()
    meeting["gold"]["dates"].append({"text": "übermorgen", "resolved": "2026-09-24"})
    assert notes_gold.validate_meeting(meeting, "m06") == [
        "m06: dates[5].text not in the transcript"
    ]


def test_a_speaker_label_nobody_spoke_under_is_a_problem() -> None:
    meeting = _m06()
    meeting["gold"]["speakers"]["SPEAKER_9"] = "Nobody"
    assert notes_gold.validate_meeting(meeting, "m06") == [
        "m06: speakers key 'SPEAKER_9' is not a transcript speaker"
    ]


def test_a_forbidden_string_inside_a_gold_fact_is_a_contradiction() -> None:
    meeting = _m06()
    meeting["gold"]["must_not_contain"].append("Hafenbund")
    problems = notes_gold.validate_meeting(meeting, "m06")
    assert problems == ["m06: must_not_contain[6] occurs in a gold key fact"]


def test_an_unknown_recording_type_or_key_is_refused() -> None:
    meeting = _m06()
    meeting["recording_type"] = "town_hall"
    assert any("recording_type" in p for p in notes_gold.validate_meeting(meeting, "m06"))
    typo = copy.deepcopy(_m06())
    typo["gold"]["hedges"] = []
    assert any("hedges" in p for p in notes_gold.validate_meeting(typo, "m06"))


def test_problems_never_quote_the_gold_text() -> None:
    meeting = _m06()
    meeting["gold"]["entities"][0]["surface_forms"].append("Geheimname Zett")
    for problem in notes_gold.validate_meeting(meeting, "m06"):
        assert "Geheimname" not in problem


def test_the_cli_prints_nothing_and_exits_0_on_the_committed_corpus(capsys: Any) -> None:
    assert notes_gold.main([str(CORPUS)]) == 0
    assert capsys.readouterr().out == ""
    assert notes_gold.main([str(CORPUS / "missing")]) == 3
