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


def _corpus() -> list[dict[str, Any]]:
    import json

    files = sorted((REPO / "tests" / "fixtures" / "eval" / "notes").glob("*.json"))
    return [json.loads(p.read_text("utf-8")) for p in files]


def test_the_committed_corpus_is_the_shape_the_harness_reads() -> None:
    meetings = _corpus()
    assert len(meetings) == 10
    for meeting in meetings:
        name = meeting["id"]
        assert meeting["gold"]["key_facts"], name
        assert meeting["meeting_type"]
        # Every gold action names what it is and who has it.
        for action in meeting["gold"]["actions"]:
            assert action["text"] and action["owner"], name
        # The result-view shape the worker snapshots must come out of it.
        turns = notes_eval.as_asr_result(meeting)["turns"]
        assert turns and all(t["paragraphs"] and t["end_ms"] > 0 for t in turns), name


# ── Q1 T1: the harness feeds the engine what the worker feeds it ────


def _engine() -> Any:
    sys.path.insert(0, str(REPO / "services" / "note-service" / "src"))
    from note_service.domain.meeting_doc import windows

    return windows


def test_the_engine_reads_every_turn_the_harness_emits() -> None:
    """Until Q1 this was 0: the harness wrote `text`, the engine reads
    `paragraphs`, and the pipeline arm scored an empty transcript."""
    windows = _engine()
    for meeting in _corpus():
        turns = windows.turns_from_result(notes_eval.as_asr_result(meeting))
        assert len(turns) == len(meeting["transcript"]), meeting["id"]
        assert [t.text for t in turns] == [t["text"] for t in meeting["transcript"]]


def test_speaker_names_are_applied_from_gold_or_defaulted() -> None:
    windows = _engine()
    by_id = {m["id"]: m for m in _corpus()}
    named = windows.turns_from_result(notes_eval.as_asr_result(by_id["m06_de_news_podcast"]))
    assert named[0].speaker_name == "Lena Hartwig"
    assert {t.speaker_name for t in named} == {"Lena Hartwig", "Jonas Pfeffer", "Karla Sommerfeld"}
    unnamed = notes_eval.as_asr_result(by_id["m02_de_kundenprojekt"])
    assert unnamed["speaker_names"]["SPEAKER_1"] == "Speaker 1"
    assert unnamed["name_candidates"] == []
    assert notes_eval.as_asr_result(by_id["m06_de_news_podcast"])["recorded_on"] == "2026-09-22"


def test_the_pipeline_lands_in_the_templates_sections() -> None:
    windows = _engine()
    assert windows  # engine importable
    from note_service.domain.meeting_doc import types

    family = types.family_for_type("auto")
    assert notes_eval.template_code(family, "de") == "meeting_notes_de"
    assert notes_eval.template_code(family, "en") == "meeting_notes"
    roles = notes_eval.role_map("meeting_notes_de")
    assert roles["decisions"] == "decisions" and roles["action_items"] == "action_items"


class _NoopProvider:
    backend = "fake"
    model_id = "fake"

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a blind engine must not call the model")

    async def aclose(self) -> None:
        return None


def test_a_blind_engine_exits_2(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    """The old shape reaches the engine as zero windows: the harness must
    say so and stop, not score an empty document."""
    import asyncio
    import json

    import models

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "m.json").write_text(json.dumps({**MEETING, "meeting_type": "auto"}), "utf-8")

    def old_shape(meeting: dict[str, Any]) -> dict[str, Any]:
        return {
            "language": "en",
            "turns": [{"speaker": "S", "text": t["text"]} for t in meeting["transcript"]],
        }

    class _Registry:
        def backend(self, name: str, expect_kind: str) -> Any:
            return type("R", (), {"name": name, "model_id": "fake", "processor": None})()

    monkeypatch.setattr(notes_eval, "as_asr_result", old_shape)
    monkeypatch.setattr(notes_eval, "load_registry", lambda: _Registry())
    monkeypatch.setattr(models, "build_chat_provider", lambda resolved: _NoopProvider())
    code = asyncio.run(notes_eval.main("pipeline", "fake", corpus, 1))
    assert code == notes_eval.EXIT_BLIND == 2
    assert "engine saw no transcript" in capsys.readouterr().err


def test_a_missing_corpus_exits_3(tmp_path: Path) -> None:
    import asyncio

    assert asyncio.run(notes_eval.main("pipeline", "fake", tmp_path / "nope", 1)) == 3


def test_a_real_quote_with_different_punctuation_or_an_echoed_header_is_a_citation() -> None:
    """Found on the first real run (Q2): the harness compared raw text while
    the engine normalises, and flagged verified quotes as hallucinated."""
    totals = notes_eval.Totals()
    row = notes_eval.score(
        MEETING,
        _produced(quotes=[("[1] Speaker 2 (00:30): Yes; I'll have the release note", 1)]),
        totals,
    )
    assert "hallucinated_quote" not in row
    assert totals.citations.rate == 1.0
