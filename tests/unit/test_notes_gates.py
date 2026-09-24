"""The notes eval's gates: regression checklists, the nightly comparison
and the judge column (Summary Engine v2, Q1 T6–T8)."""

from __future__ import annotations

import asyncio
import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "scripts" / "eval"
sys.path.insert(0, str(EVAL))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


notes_assert = _load("notes_assert")
compare_notes = _load("compare_notes")
notes_eval = _load("notes_eval")


def _line(text: str, key: str = "gen:overview", kind: str = "summary", ids: tuple = ("a",)) -> dict:
    return {"section_key": key, "kind": kind, "text": text, "fact_ids": list(ids)}


# ── Checklists ──────────────────────────────────────────────────────


def test_every_committed_checklist_names_a_meeting_and_known_checks() -> None:
    known = {
        "id",
        "recording_type",
        "topics_min",
        "speakers",
        "must_not_contain",
        "must_contain_any",
        "hedged_must_keep",
        "dates",
        "every_line_cited",
        "sprint",
    }
    files = sorted(notes_assert.ASSERTIONS.glob("*.assertions.json"))
    assert {f.name for f in files} >= {
        "r01_de_zeit_was_jetzt.assertions.json",
        "m06_de_news_podcast.assertions.json",
    }
    for path in files:
        checklist = json.loads(path.read_text("utf-8"))
        assert set(checklist) <= known, path.name
        assert path.name == f"{checklist['id']}.assertions.json"
    # m06 is the synthetic twin: its meeting is in the committed corpus.
    meeting = REPO / "tests" / "fixtures" / "eval" / "notes" / "m06_de_news_podcast.json"
    assert notes_assert.checklist_for(meeting) is not None


def test_the_audit_note_fails_its_checklist_and_a_good_note_passes() -> None:
    checklist = {
        "recording_type": "podcast_broadcast",
        "topics_min": 2,
        "speakers": {"SPEAKER_1": "Lena Hartwig"},
        "must_not_contain": ["Teambesprechung", "Hinweis zum Transkript"],
        "must_contain_any": [["Hafenbund"], ["3.000", "3000"]],
        "hedged_must_keep": [{"match": "Frühverrentung", "markers": ["wahrscheinlich"]}],
        "dates": [{"text": "am Montag", "resolved": "2026-09-21"}],
        "every_line_cited": True,
        "sprint": {"dates": "Q3"},
    }
    audit_like = {
        "lines": [
            _line("Teambesprechung über die Rente mit Speaker 1."),
            _line("Die Frühverrentung wird abgeschafft.", kind="key_point"),
            _line("Hinweis zum Transkript: …", kind="note", ids=()),
        ],
        "brief": {"conversation_type": "Teambesprechung"},
    }
    results = {name: (ok, sprint) for name, ok, sprint in notes_assert.check(checklist, audit_like)}
    assert results["recording_type"] == (False, "")
    assert results["topics_min"] == (False, "")
    assert results["speakers[SPEAKER_1]"][0] is False
    assert results["must_not_contain[0]"][0] is False
    assert results["must_not_contain[1]"][0] is False
    assert results["hedged_must_keep[0]"][0] is False
    assert results["dates[0]"] == (False, "Q3")

    good = {
        "lines": [
            _line("Die Frühverrentung wird wahrscheinlich abgeschwächt.", key="gen:rente"),
            _line("Der Hafenbund ruft rund 3.000 Beschäftigte auf.", key="gen:hafen"),
        ],
        "stats": {"recording_type": "podcast_broadcast"},
        "dates": [{"text": "am Montag", "resolved": "2026-09-21"}],
    }
    assert all(ok for _name, ok, _s in notes_assert.check(checklist, good))


def test_check_output_never_carries_the_strings_it_looks_for() -> None:
    checklist = {"must_not_contain": ["Geheim"], "must_contain_any": [["Vertraulich"]]}
    for name, _ok, _sprint in notes_assert.check(checklist, {"lines": [_line("Geheim")]}):
        assert "Geheim" not in name and "Vertraulich" not in name


# ── The nightly comparison ──────────────────────────────────────────


def _report(**summary: Any) -> dict:
    base = {
        "unsupported_rate": 0.10,
        "key_fact_recall": 0.50,
        "invented_claims": 0,
        "example_echo": 0,
    }
    return {"runs": [{"summary": {**base, **summary}}]}


def test_compare_passes_an_equal_report_and_fails_a_worse_one() -> None:
    ok, _ = compare_notes.compare(
        _report(), _report(), max_unsupported_rise=0.01, max_recall_drop=0.02
    )
    assert ok == 0
    for worse in (
        _report(unsupported_rate=0.12),
        _report(key_fact_recall=0.47),
        _report(invented_claims=1),
        _report(example_echo=1),
    ):
        code, lines = compare_notes.compare(
            _report(), worse, max_unsupported_rise=0.01, max_recall_drop=0.02
        )
        assert code == 1 and any(line.startswith("REGRESSION") for line in lines)


def test_compare_refuses_a_comparison_it_cannot_make() -> None:
    code, _ = compare_notes.compare(
        _report(), _report(unsupported_rate=None), max_unsupported_rise=0.01, max_recall_drop=0.02
    )
    assert code == 2


def test_compare_cli_exit_code(tmp_path: Path) -> None:
    base, worse = tmp_path / "b.json", tmp_path / "c.json"
    base.write_text(json.dumps(_report()), "utf-8")
    worse.write_text(json.dumps(_report(example_echo=2)), "utf-8")
    assert compare_notes.main(["--baseline", str(base), "--current", str(base)]) == 0
    assert compare_notes.main(["--baseline", str(base), "--current", str(worse)]) == 1


# ── The judge column (eval only) ────────────────────────────────────


class _Answer:
    def __init__(self, payload: dict) -> None:
        self.json = payload
        self.input_tokens = 10
        self.output_tokens = 2


class _Judge:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, prompt: str, schema: Any = None, **kwargs: Any) -> _Answer:
        self.prompts.append(prompt)
        supported = "spring" in prompt.split("Facts it cites:")[0]
        return _Answer({"supported": supported, "problem": "none" if supported else "new_claim"})


def test_the_judge_sees_the_line_and_its_facts_and_never_the_transcript() -> None:
    produced = {
        "lines": [
            _line("The launch moves to the spring."),
            _line("The launch moves to the spring, says Merz."),
            _line("- Send the deck", kind="action"),
            _line("Uncited", ids=()),
        ],
        "facts": [
            {
                "item_key": "a",
                "text": "the launch moves to the spring",
                "quote": "we move it to spring",
            }
        ],
    }
    judge = _Judge()
    totals, usage = notes_eval.JudgeTotals(), notes_eval.Totals()
    asyncio.run(notes_eval.judge(produced, judge, totals, usage))
    # Only composed lines that cite facts are judged.
    assert len(judge.prompts) == 2
    assert all("we move it to spring" in p for p in judge.prompts)
    summary = totals.summary()
    assert summary["judge_unsupported_rate"] == 0.0
    # The deterministic check calls the "says Merz" line unsupported; the
    # fake judge does not — that is the disagreement the column exists for.
    assert summary["deterministic_vs_judge_disagreement"] == 0.5
    assert usage.input_tokens == 20


# ── Blind pairwise rating (Q4 T7) ───────────────────────────────────

notes_pairs = _load("notes_pairs")


def test_pairs_round_trip_from_notes_to_a_preference(tmp_path: Path, monkeypatch: Any) -> None:
    local = tmp_path / "local"
    monkeypatch.setattr(notes_pairs, "LOCAL", local)
    corpus = REPO / "tests" / "fixtures" / "eval" / "notes"
    a, b = local / "a", local / "b"
    for folder, word in ((a, "pipeline"), (b, "baseline")):
        folder.mkdir(parents=True)
        for mid in ("m01_en_product_sync", "m06_de_news_podcast"):
            (folder / f"{mid}.md").write_text(f"{word} note for {mid}", "utf-8")
    out = local / "pairs"
    assert notes_pairs.build(a, b, corpus, out, seed=1) == 0
    key = {row["pair_id"]: row for row in csv.DictReader((out / "key.csv").open())}
    assert len(key) == 2
    text = (out / "p001.md").read_text("utf-8")
    assert "## Note L" in text and "## Note R" in text and "## Transcript" in text
    # Raters: two prefer the pipeline on both pairs, one picks the baseline once.
    rows = [
        ["pair_id", "rater", "preferred", "accuracy", "completeness", "usefulness", "readability"]
    ]
    for pid, k in key.items():
        pipeline_side = "L" if k["left"] == "pipeline" else "R"
        other = "R" if pipeline_side == "L" else "L"
        rows += [[pid, "r1", pipeline_side, 4, 4, 4, 4], [pid, "r2", pipeline_side, 5, 4, 4, 5]]
        rows += [[pid, "r3", other if pid == "p001" else pipeline_side, 3, 3, 3, 3]]
    ratings = out / "ratings.csv"
    with ratings.open("w", newline="") as handle:
        csv.writer(handle).writerows(rows)
    result = notes_pairs.score(ratings, out / "key.csv", corpus)
    assert result["pairs"] == 2 and result["raters"] == 3
    assert result["overall"]["preference"] == 5 / 6
    low, high = result["overall"]["ci95"]
    assert 0 < low < 5 / 6 < high <= 1
    assert set(result["by_language"]) == {"en", "de"}
    assert result["inter_rater_agreement"] == 4 / 6


def test_pairs_never_leave_the_local_folder(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit):
        notes_pairs.build(tmp_path, tmp_path, tmp_path, REPO / "docs" / "eval" / "pairs")


def test_wilson_interval() -> None:
    low, high = notes_pairs.wilson(50, 100)
    assert round(low, 3) == 0.404 and round(high, 3) == 0.596
