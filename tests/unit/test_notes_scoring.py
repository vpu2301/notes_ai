"""One hand-built case per audit metric (Summary Engine v2, Q1 T5).

The scorers decide whether Q2–Q5 passed their gates, so each rule is
pinned here on inputs small enough to check by eye.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "eval"))
_spec = importlib.util.spec_from_file_location(
    "notes_scoring", REPO / "scripts" / "eval" / "notes_scoring.py"
)
assert _spec is not None and _spec.loader is not None
scoring = importlib.util.module_from_spec(_spec)
sys.modules["notes_scoring"] = scoring
_spec.loader.exec_module(scoring)


def _fact(key: str, text: str, quote: str = "", certainty: str | None = "fact", **kw: Any) -> dict:
    return {
        "item_key": key,
        "kind": "key_point",
        "text": text,
        "quote": quote or text,
        "certainty": certainty,
        "start_ms": 0,
        "end_ms": 1000,
        "window_index": 0,
        **kw,
    }


def _line(text: str, kind: str = "summary", ids: tuple[str, ...] = ("a",)) -> dict:
    return {"section_key": "gen:overview", "kind": kind, "text": text, "fact_ids": list(ids)}


def _meeting(**gold: Any) -> dict:
    return {
        "id": "t",
        "language": gold.pop("language", "en"),
        "transcript": gold.pop(
            "transcript",
            [
                {"speaker": "SPEAKER_1", "t_start_ms": 0, "t_end_ms": 30_000, "text": "first part"},
                {
                    "speaker": "SPEAKER_2",
                    "t_start_ms": 30_000,
                    "t_end_ms": 60_000,
                    "text": "middle",
                },
                {
                    "speaker": "SPEAKER_1",
                    "t_start_ms": 60_000,
                    "t_end_ms": 90_000,
                    "text": "end part",
                },
            ],
        ),
        "recording_type": gold.pop("recording_type", None),
        "gold": gold,
    }


def _score(meeting: dict, lines: list[dict], facts: list[dict], **produced: Any) -> dict:
    return scoring.score_meeting(meeting, {"lines": lines, "facts": facts, **produced})


# ── support / unsupported_rate ──────────────────────────────────────


def test_a_german_sentence_with_a_different_inflection_is_supported() -> None:
    """ "Lieferungen" in the fact, "Lieferung" in the line: the stem carries it."""
    fact = _fact(
        "a", "Die Lieferungen an den Kunden verschieben sich", "die Lieferung verschiebt sich"
    )
    assert scoring.support(
        "Die Lieferung an den Kunden verschiebt sich.", [f"{fact['text']} {fact['quote']}"]
    )
    row = _score(_meeting(), [_line("Die Lieferung an den Kunden verschiebt sich.")], [fact])
    assert row["unsupported"] == [0, 1]


def test_a_sentence_introducing_a_new_name_is_unsupported_and_invented() -> None:
    fact = _fact("a", "the launch moves to the spring")
    line = _line("The launch moves to the spring, according to Merz.")
    row = _score(_meeting(), [line], [fact])
    assert row["unsupported"] == [1, 1]
    assert row["invented_claims"] == 1


def test_a_number_nobody_said_is_unsupported_and_invented() -> None:
    fact = _fact("a", "the budget grows next year")
    row = _score(_meeting(), [_line("The budget grows by 12 percent next year.")], [fact])
    assert row["unsupported"] == [1, 1]
    assert row["invented_claims"] == 1


def test_a_line_that_says_less_than_half_of_what_it_cites_is_unsupported() -> None:
    fact = _fact("a", "the pricing page is ready")
    row = _score(_meeting(), [_line("Hiring stalled while travel costs doubled overall.")], [fact])
    assert row["unsupported"] == [1, 1]


def test_only_composed_lines_count_toward_the_unsupported_rate() -> None:
    fact = _fact("a", "Send the deck")
    lines = [
        _line("- Send the deck", kind="action"),
        _line("Totally different claim here", kind="bullet"),
    ]
    row = _score(_meeting(), lines, [fact])
    assert row["unsupported"] == [1, 1]


def test_the_baseline_is_checked_against_the_transcript() -> None:
    meeting = _meeting(
        transcript=[
            {"speaker": "S", "t_start_ms": 0, "t_end_ms": 9000, "text": "the pier opens in May"}
        ]
    )
    row = _score(meeting, [_line("The pier opens in May.", ids=())], [], evidence="transcript")
    assert row["unsupported"] == [0, 1]


# ── example echo ────────────────────────────────────────────────────


def test_an_example_sentence_in_a_line_is_counted() -> None:
    from note_service.domain.meeting_doc import prompts

    echo = prompts.EXAMPLES["en"]["summary_right"]
    row = _score(_meeting(), [_line(echo), _line("fine")], [_fact("a", "fine")])
    assert row["example_echo"] == 1


# ── recall, coverage, excluded speech ───────────────────────────────


def test_recall_by_third_and_coverage() -> None:
    meeting = _meeting(key_facts=["first part", "end part"])
    row = _score(meeting, [_line("first part", kind="key_point")], [_fact("a", "first part")])
    assert row["key_fact_recall"] == [1, 2]
    assert row["recall_by_third"]["1"] == [1, 1]
    assert row["recall_by_third"]["3"] == [0, 1]
    summary = scoring.aggregate([row])
    assert summary["key_fact_recall"] == 0.5
    assert summary["coverage_ratio"] == 0.0


def test_excluded_speech_counts_overlapping_ranges_once() -> None:
    row = _score(
        _meeting(), [], [], noise_ranges=[[0, 9_000, "background"], [4_500, 9_000, "artifact"]]
    )
    assert row["excluded_ms"] == [9_000, 90_000]
    assert scoring.aggregate([row])["excluded_speech"] == 0.1


# ── recording type ──────────────────────────────────────────────────


def test_teambesprechung_is_a_meeting_not_a_podcast() -> None:
    meeting = _meeting(recording_type="podcast_broadcast")
    row = _score(meeting, [], [], brief={"conversation_type": "Teambesprechung"})
    assert row["recording_type"] == [0, 1]
    row = _score(meeting, [], [], brief={"conversation_type": "Nachrichtenpodcast"})
    assert row["recording_type"] == [1, 1]
    assert scoring.recording_type_of("Podcast") == "podcast_broadcast"


# ── redundancy ──────────────────────────────────────────────────────


def test_two_near_identical_bullets_are_redundant() -> None:
    lines = [
        _line("- Ticket machines at the north pier are unreliable", kind="bullet"),
        _line("- The ticket machines at the north pier are unreliable", kind="key_point"),
        _line("- Passenger numbers fell in August", kind="bullet"),
    ]
    row = _score(_meeting(), lines, [_fact("a", "x")])
    assert row["redundancy"] == [2, 3]


# ── entities ────────────────────────────────────────────────────────


def test_an_asr_spelling_in_the_note_is_an_entity_error() -> None:
    entity = {"canonical": "Friedrich Merz", "surface_forms": ["Friedrich Schmerz", "Merz"]}
    meeting = _meeting(entities=[entity], name_candidates=["Friedrich Merz"])
    wrong = _score(meeting, [_line("Friedrich Schmerz spoke.", ids=())], [])
    assert wrong["entity_accuracy"] == [0, 1]
    assert wrong["entity_accuracy_knowable"] == [0, 1]
    right = _score(meeting, [_line("Merz spoke.", ids=())], [])
    assert right["entity_accuracy"] == [1, 1]


# ── hedges ──────────────────────────────────────────────────────────


def test_a_hedged_gold_fact_written_flat_is_not_preserved() -> None:
    meeting = _meeting(
        hedged=[{"fact": "the early pension rule will be weakened", "modality": "forecast"}]
    )
    fact = _fact("a", "the early pension rule will be weakened", certainty="fact")
    row = _score(
        meeting, [_line("The early pension rule will be weakened.", kind="key_point")], [fact]
    )
    assert row["hedge_preservation"] == [0, 1]


def test_the_same_line_is_preserved_when_its_fact_is_a_prediction() -> None:
    meeting = _meeting(
        hedged=[{"fact": "the early pension rule will be weakened", "modality": "forecast"}]
    )
    fact = _fact("a", "the early pension rule will be weakened", certainty="prediction")
    row = _score(
        meeting, [_line("The early pension rule will be weakened.", kind="key_point")], [fact]
    )
    assert row["hedge_preservation"] == [1, 1]


def test_a_marker_in_the_line_preserves_the_hedge() -> None:
    meeting = _meeting(
        language="de",
        hedged=[{"fact": "Die Frühverrentung wird abgeschwächt", "modality": "forecast"}],
    )
    fact = _fact("a", "Die Frühverrentung wird abgeschwächt")
    line = _line("Die Frühverrentung wird wahrscheinlich abgeschwächt.", kind="key_point")
    assert _score(meeting, [line], [fact])["hedge_preservation"] == [1, 1]


# ── attribution ─────────────────────────────────────────────────────


def test_an_opinion_line_must_name_its_holder() -> None:
    meeting = _meeting(speakers={"SPEAKER_1": "Jonas Pfeffer"})
    opinion = _fact("a", "the offer is too low", certainty="opinion")
    anonymous = _score(meeting, [_line("The offer is too low.", kind="key_point")], [opinion])
    assert anonymous["attribution"] == [0, 1]
    named = _score(
        meeting, [_line("According to Pfeffer, the offer is too low.", kind="key_point")], [opinion]
    )
    assert named["attribution"] == [1, 1]
    fact = _fact("b", "the offer is 4 percent")
    assert _score(meeting, [_line("The offer is 4 percent.", ids=("b",))], [fact])[
        "attribution"
    ] == [0, 0]


# ── dates and checklists ────────────────────────────────────────────


def test_date_resolution_is_null_until_the_engine_exposes_dates() -> None:
    meeting = _meeting(dates=[{"text": "am Montag", "resolved": "2026-09-21"}])
    assert _score(meeting, [], [])["date_resolution"] is None
    row = _score(meeting, [], [], dates=[{"text": "am Montag", "resolved": "2026-09-21"}])
    assert row["date_resolution"] == [1, 1]


def test_must_checks_report_indices_never_strings() -> None:
    meeting = _meeting(must_contain=["Hafenbund", "Emden"], must_not_contain=["November"])
    row = _score(meeting, [_line("Der Hafenbund streikt im November.", ids=())], [])
    assert row["must_contain_failed"] == [1]
    assert row["must_not_contain_failed"] == [0]
    flat = repr(row)
    for secret in ("Hafenbund", "Emden", "November"):
        assert secret not in flat


def test_the_aggregate_is_numbers_only() -> None:
    meeting = _meeting(key_facts=["first part"], must_not_contain=["x"])
    rows = [_score(meeting, [_line("first part", kind="key_point")], [_fact("a", "first part")])]
    summary = scoring.aggregate(rows, types=["meeting"])
    for key, value in summary.items():
        assert value is None or isinstance(value, (int, float, dict)), key
    assert summary["recall_by_type"] == {"meeting": 1.0}


def test_an_action_line_with_its_verified_owner_and_deadline_invents_nothing() -> None:
    fact = _fact("a", "Publish the timetable", owner="Mira", due_text="by Friday")
    fact["kind"] = "action"
    line = _line("- Mira: Publish the timetable — by Friday", kind="action")
    assert _score(_meeting(), [line], [fact])["invented_claims"] == 0


# ── Q4: entities by source, model tier precision ────────────────────


def test_entities_are_credited_to_the_tier_that_got_them_right() -> None:
    meeting = _meeting(
        entities=[
            {"canonical": "Alisher Usmanow", "surface_forms": ["Uschmanow"]},
            {"canonical": "Fabian Reinbold", "surface_forms": ["Reinbolt"]},
        ]
    )
    facts = [
        _fact("a", "Usmanow bleibt gelistet", corrections=[["Uschmanow", "Usmanow", "model"]]),
        _fact("b", "Laut Reinbold knapp", corrections=[["Reinbolt", "Reinbold", "candidate"]]),
        _fact("c", "Ivanov sagt nein", corrections=[["Ivanow", "Ivanov", "model"]]),
    ]
    lines = [_line("Usmanow bleibt gelistet", ids=("a",)), _line("Laut Reinbold knapp", ids=("b",))]
    row = _score(meeting, lines, facts)
    assert row["entity_accuracy"] == [2, 2]
    assert row["entity_sources"] == {"model": 1, "candidate": 1}
    # Two model corrections, one of them a gold entity.
    assert row["model_tier_precision"] == [1, 2]
    assert scoring.aggregate([row])["model_tier_precision"] == 0.5


def test_the_framing_is_not_an_opinion_to_attribute() -> None:
    opinion = _fact("a", "the offer is too low", certainty="opinion")
    row = _score(_meeting(), [_line("An interview about the offer.", kind="framing")], [opinion])
    assert row["attribution"] == [0, 0]


# ── Q5: every line cited; the key-dates block ───────────────────────


def test_lines_cited_and_key_dates_recall() -> None:
    meeting = _meeting(
        dates=[
            {"text": "bis Mittwoch 0 Uhr", "resolved": "2026-09-23T00:00", "tense": "future"},
            {"text": "1. Oktober", "resolved": "2026-10-01", "tense": "future"},
            {"text": "am Montag", "resolved": "2026-09-21", "tense": "past"},
        ]
    )
    lines = [
        {**_line("A line", kind="summary"), "dates": []},
        {**_line("A typed line", kind="key_point", ids=()), "dates": []},
        {
            **_line("- 23.09.2026 00:00 — Streik endet", kind="date"),
            "dates": ["2026-09-23T00:00"],
        },
    ]
    row = _score(meeting, lines, [_fact("a", "x")])
    assert row["lines_cited"] == [2, 3]
    # The past Monday is not a key date; one of the two coming ones is in the block.
    assert row["key_dates_recall"] == [1, 2]
    summary = scoring.aggregate([row])
    assert summary["lines_cited"] == 2 / 3 and summary["key_dates_recall"] == 0.5


def test_a_key_date_line_is_an_index_not_an_invention_or_a_repeat() -> None:
    fact = _fact("a", "Der Warnstreik soll bis Mittwoch dauern")
    lines = [
        _line("- Der Warnstreik soll bis Mittwoch dauern", kind="key_point"),
        _line("- 23.09.2026 00:00 — Der Warnstreik soll bis Mittwoch dauern", kind="date"),
    ]
    row = _score(_meeting(), lines, [fact])
    assert row["invented_claims"] == 0
    assert row["redundancy"] == [0, 1]


def test_a_verified_holder_is_evidence_for_the_line_that_names_them() -> None:
    fact = _fact("a", "the offer is too low", certainty="opinion", attributed_to="Jonas Pfeffer")
    line = _line("- The offer is too low — according to Pfeffer", kind="key_point")
    assert _score(_meeting(), [line], [fact])["invented_claims"] == 0
