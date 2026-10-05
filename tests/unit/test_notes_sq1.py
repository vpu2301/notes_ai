"""Gold v3 and the scorers the summary criteria need."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "eval"))

import notes_gold  # noqa: E402
import notes_scoring as scoring  # noqa: E402
import taxonomy  # noqa: E402


def _meeting(**gold: object) -> dict:
    return {
        "id": "x",
        "language": "de",
        "meeting_type": "podcast",
        "transcript": [
            {
                "speaker": "SPEAKER_1",
                "t_start_ms": 0,
                "t_end_ms": 5000,
                "text": "Das Abkommen wurde 2022 unterzeichnet, sagt Welchering.",
            },
            {
                "speaker": "SPEAKER_2",
                "t_start_ms": 5000,
                "t_end_ms": 9000,
                "text": "Boniat glaubt, dass es scheitert.",
            },
        ],
        "gold": gold,
    }


def test_a_participant_without_a_role_is_refused() -> None:
    problems = notes_gold.validate_meeting(
        _meeting(
            participants=[{"label": "SPEAKER_1", "name": "Peter Welchering", "speech_share": 0.6}]
        ),
        "m",
    )
    assert any("participants.0.role" in p for p in problems)


def test_v3_key_facts_validate_with_ids_thirds_and_opinions() -> None:
    gold = {
        "key_facts": [
            {"id": "k01", "text": "Abkommen 2025 unterzeichnet", "third": 1, "kind": "date"},
            {
                "id": "k02",
                "text": "Boniat erwartet ein Scheitern",
                "third": 3,
                "kind": "opinion",
                "holder": "Tara Boniat",
            },
        ],
        "opinions": [{"fact": "k02", "holder": "Tara Boniat"}, {"fact": "k09", "holder": "x"}],
        "participants": [
            {
                "label": "SPEAKER_1",
                "name": "Peter Welchering",
                "role": "expert",
                "speech_share": 0.6,
            }
        ],
        "reviewers": 2,
    }
    problems = notes_gold.validate_meeting(_meeting(**gold), "m")
    assert problems == ["m: opinions[1].fact names no key fact"]


def test_v2_files_stay_valid() -> None:
    assert notes_gold.validate_corpus(REPO / "tests" / "fixtures" / "eval" / "notes") == []


def test_participant_recall_two_of_three() -> None:
    gold = {
        "participants": [
            {"name": "Peter Welchering", "role": "expert", "speech_share": 0.5},
            {"name": "Tara Boniat", "role": "interviewee", "speech_share": 0.2},
            {"name": "Anna Keller", "role": "narrator", "speech_share": 0.3},
        ]
    }
    produced = {
        "sections": [
            {
                "role": "orientation",
                "text": "Podcast. Es sprechen Peter Welchering und Tara Boniat.",
            }
        ],
        "lines": [],
    }
    row = scoring.score_sq1({"gold": gold, "transcript": []}, produced)
    assert row["participant_recall"] == [2, 3]
    assert row["participant_precision"] == [2, 2]


def test_a_line_right_by_the_asr_but_wrong_by_the_truth_is_propagated() -> None:
    meeting = _meeting()
    meeting["reference_transcript"] = [
        {
            "speaker": "SPEAKER_1",
            "t_start_ms": 0,
            "t_end_ms": 5000,
            "text": "Das Abkommen wurde 2025 unterzeichnet, sagt Welchering.",
        }
    ]
    produced = {
        "lines": [
            {"kind": "bullet", "text": "Das Abkommen wurde 2022 unterzeichnet.", "fact_ids": ["a"]}
        ],
        "facts": [],
    }
    row = scoring.score_sq1(meeting, produced)
    assert (row["propagated_from_asr"], row["invented_vs_truth"]) == (1, 0)


def test_a_filler_line_is_one_whose_words_another_line_has() -> None:
    lines = [
        {
            "kind": "bullet",
            "text": "Welchering erklärt die Sanktionen gegen Iran",
            "fact_ids": ["a"],
        },
        {"kind": "bullet", "text": "Welchering erklärt Sanktionen", "fact_ids": ["b"]},
        {"kind": "bullet", "text": "Boniat zweifelt am Abkommen", "fact_ids": ["c"]},
    ]
    assert scoring.filler_lines(lines, cited_evidence=True) == 1


def test_title_checks() -> None:
    evidence = "Welchering spricht über Handala und Iran"
    good = scoring.title_checks({"title": "Handala und der Iran: was Welchering erklärt"}, evidence)
    assert good["title_ok"] == [1, 1]
    generic = scoring.title_checks({"title": "Podcast-Folge Besprechung Meeting Notes"}, evidence)
    assert generic["title_not_generic"] is False
    invented = scoring.title_checks(
        {"title": "Handala und das Treffen mit Natanz-Experten"}, evidence
    )
    assert invented["title_names_supported"] is False


def test_every_sq1_metric_has_a_taxonomy_code() -> None:
    summary = scoring.aggregate([{}])
    for key in ("participant_precision", "participant_recall", "opinion_attribution", "filler_lines",
                "title_ok", "by_third_ratio", "propagated_from_asr", "invented_vs_truth"):  # fmt: skip
        assert key in summary and key in taxonomy.METRIC_CODES
