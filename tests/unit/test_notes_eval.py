"""The gold-set scoring (Sprint 33 B-2 / Sprint 37 B-1).

A benchmark decides which model ships, so its arithmetic has to be worth
trusting on its own. These are the rules the numbers rest on: wording is
free, content is not, an owner is only scored on a line that matched, and
a quote that is not verbatim in the transcript fails the run rather than
scoring lower.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "notes_eval", REPO / "scripts" / "eval" / "notes_eval.py"
)
assert _spec is not None and _spec.loader is not None
notes_eval = importlib.util.module_from_spec(_spec)
sys.modules["notes_eval"] = notes_eval
_spec.loader.exec_module(notes_eval)


class _Fact:
    def __init__(self, text: str, owner: str | None = None, quote: str = "", turn: int = 0) -> None:
        self.text, self.owner_label, self.quote, self.turn = text, owner, quote, turn


MEETING: dict[str, Any] = {
    "id": "m",
    "language": "en",
    "transcript": [
        {
            "speaker": "SPEAKER_1",
            "t_start_ms": 0,
            "t_end_ms": 30_000,
            "text": "Priya, can you send the release note to support before the rollout?",
        },
        {
            "speaker": "SPEAKER_2",
            "t_start_ms": 30_000,
            "t_end_ms": 60_000,
            "text": "Yes, I'll have the release note to support by Thursday noon.",
        },
    ],
    "gold": {
        "key_facts": ["The release note goes to support before the rollout"],
        "actions": [{"text": "Send the release note to support", "owner": "Priya"}],
        "decisions": [],
    },
}


def _produced(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "seconds": 1.0,
        "lines": ["Release note to support before the rollout — Priya, Thursday"],
        "actions": [
            _Fact(
                "Release note to support before the rollout — Priya, Thursday",
                "Priya",
                "by Thursday noon",
                1,
            )
        ],
        "decisions": [],
        "quotes": [("by Thursday noon", 1)],
        "windows": 1,
        "windows_failed": 0,
    }
    base.update(over)
    return base


def test_different_wording_of_the_same_fact_counts_as_the_fact() -> None:
    totals = notes_eval.Totals()
    row = notes_eval.score(MEETING, _produced(), totals)
    assert row["key_facts_missed"] == []
    assert totals.actions_recall.rate == 1.0
    assert totals.owners.rate == 1.0


def test_a_line_that_drops_half_the_fact_does_not_count_as_the_fact() -> None:
    """The threshold is on content words, so "Release note — Priya" is not
    "the release note goes to support before the rollout"."""
    totals = notes_eval.Totals()
    row = notes_eval.score(
        MEETING,
        _produced(
            lines=["Release note — Priya"],
            actions=[_Fact("Release note — Priya", "Priya", "", -1)],
            quotes=[],
        ),
        totals,
    )
    assert row["key_facts_missed"] == ["#1"]


def test_a_line_about_something_else_is_not_the_fact() -> None:
    totals = notes_eval.Totals()
    row = notes_eval.score(
        MEETING,
        _produced(
            lines=["The team discussed the pricing page"],
            actions=[_Fact("Look at the pricing page", None, "", -1)],
            quotes=[],
        ),
        totals,
    )
    assert row["key_facts_missed"] == ["#1"]
    assert totals.actions_recall.rate == 0.0
    assert totals.actions_precision.rate == 0.0
    # No owner was scored: there was no matched action to score it on.
    assert totals.owners.total == 0


def test_the_wrong_owner_on_the_right_action_is_an_owner_error() -> None:
    totals = notes_eval.Totals()
    notes_eval.score(
        MEETING,
        _produced(
            actions=[
                _Fact("Release note to support before the rollout", "Tom", "by Thursday noon", 1)
            ]
        ),
        totals,
    )
    assert totals.actions_recall.rate == 1.0
    assert totals.owners.rate == 0.0


def test_a_quote_that_was_never_said_fails_the_run() -> None:
    totals = notes_eval.Totals()
    row = notes_eval.score(MEETING, _produced(quotes=[("we agreed to a 40% discount", 1)]), totals)
    assert row["hallucinated_quote"] is True
    assert totals.citations.rate == 0.0


def test_a_real_quote_attributed_to_the_wrong_turn_is_not_a_citation() -> None:
    """Verbatim is necessary and not sufficient: a quote pinned to the
    wrong turn plays back the wrong seconds and names the wrong speaker."""
    totals = notes_eval.Totals()
    row = notes_eval.score(MEETING, _produced(quotes=[("by Thursday noon", 0)]), totals)
    assert "hallucinated_quote" not in row
    assert totals.citations.rate == 0.0


def test_speed_is_reported_per_meeting_hour_not_per_meeting() -> None:
    totals = notes_eval.Totals()
    notes_eval.score(MEETING, _produced(seconds=30.0), totals)
    # One minute of audio, thirty seconds of work → half an hour per hour.
    summary = notes_eval.summarise(totals, totals.audio_seconds / 3600.0)
    assert summary["seconds_per_meeting_hour"] == 1800.0


def test_the_committed_corpus_is_the_shape_the_harness_reads() -> None:
    import json

    files = sorted((REPO / "tests" / "fixtures" / "eval" / "notes").glob("*.json"))
    assert len(files) == 5
    for path in files:
        meeting = json.loads(path.read_text("utf-8"))
        assert meeting["gold"]["key_facts"], path.name
        assert meeting["meeting_type"]
        # Every gold action names what it is and who has it.
        for action in meeting["gold"]["actions"]:
            assert action["text"] and action["owner"], path.name
        # The ASR shape the engine reads must come out of it.
        turns = notes_eval.as_asr_result(meeting)["turns"]
        assert turns and all(t["text"] and t["end_ms"] > 0 for t in turns)
