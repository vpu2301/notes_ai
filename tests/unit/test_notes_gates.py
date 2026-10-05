"""The notes eval's gates: regression checklists, the nightly comparison
and the judge column (Summary Engine v2, Q1 T6–T8)."""

from __future__ import annotations

import asyncio
import csv
import importlib.util
import json
import re
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
notes_scoring = _load("notes_scoring")


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
        # F2
        "no_copied_lines",
        "no_information_lines_max",
        "no_marks",
        "topics",
        # F3
        "figures",
        "figures_min",
        "presenter_line",
        "contact_line",
        # F3 amendment after r03
        "excluded_reasons",
        "guest_line",
        "chapters_min",
        "overview",
        # docs/eval/error-taxonomy.md — codes pinned per check
        "codes",
        # D1 lint: findings allowed per code
        "lint",
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
    assert notes_pairs.OVERVIEW_QUESTION in text
    sheet = list(csv.reader((out / "sheet.csv").open()))
    assert sheet[0][-2:] == ["overview_L", "overview_R"]
    assert all(len(row) == len(sheet[0]) for row in sheet)
    # Raters: two prefer the pipeline on both pairs, one picks the baseline once.
    rows = [
        [
            "pair_id",
            "rater",
            "preferred",
            "accuracy",
            "completeness",
            "usefulness",
            "readability",
            "overview_L",
            "overview_R",
        ]
    ]
    for pid, k in key.items():
        pipeline_side = "L" if k["left"] == "pipeline" else "R"
        other = "R" if pipeline_side == "L" else "L"
        # Ours: yes from every rater but r3 on p001 ("partly"); the
        # baseline: "no" throughout.
        ov = {pipeline_side: "yes", other: "no"}
        rows += [
            [pid, "r1", pipeline_side, 4, 4, 4, 4, ov["L"], ov["R"]],
            [pid, "r2", pipeline_side, 5, 4, 4, 5, ov["L"], ov["R"]],
        ]
        r3 = dict(ov, **({pipeline_side: "partly"} if pid == "p001" else {}))
        rows += [
            [pid, "r3", other if pid == "p001" else pipeline_side, 3, 3, 3, 3, r3["L"], r3["R"]]
        ]
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
    overview = result["overview"]
    assert overview["pipeline"]["n"] == 6 and overview["pipeline"]["yes"] == 5 / 6
    assert overview["baseline"]["no"] == 1.0
    assert overview["gate_met"] is False  # 5/6 < 0.9


def test_pairs_never_leave_the_local_folder(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit):
        notes_pairs.build(tmp_path, tmp_path, tmp_path, REPO / "docs" / "eval" / "pairs")


def test_wilson_interval() -> None:
    low, high = notes_pairs.wilson(50, 100)
    assert round(low, 3) == 0.404 and round(high, 3) == 0.596


def test_the_scripted_run_gates_only_what_the_engine_guarantees() -> None:
    assert notes_assert.family("must_not_contain[3]") == "must_not_contain"
    assert notes_assert.family("every_line_cited") == "every_line_cited"
    assert {
        "speakers",
        "must_not_contain",
        "every_line_cited",
        "no_marks",
    } == notes_assert.ENGINE_CHECKS


# ── F2: statements, not quotes ──────────────────────────────────────


_PARDO_LIKE = {
    "language": "en",
    "transcript": [
        {"speaker": "SPEAKER_1", "t_start_ms": 0, "t_end_ms": 9_000,
         "text": "This boat is incredible. Again this is a crowded boat right now because the show opened."},
    ],
}  # fmt: skip


def test_the_f2_scorers_count_copies_chatter_and_first_person() -> None:
    produced = {
        "lines": [
            {
                "kind": "bullet",
                "text": "- Again this is a crowded boat right now because the show opened.",
            },
            {"kind": "bullet", "text": "- Absolutely amazing."},
            {"kind": "bullet", "text": "- We lower the platform into the water."},
            {"kind": "bullet", "text": "- The platform lowers into the water to form a staircase."},
            {"kind": "action", "text": "- We should update the deck"},
        ],
        "facts": [],
    }
    row = notes_scoring.score_meeting(_PARDO_LIKE, produced)
    assert (row["copied_lines"], row["no_information_lines"], row["first_person_lines"]) == (
        1,
        1,
        1,
    )
    summary = notes_scoring.aggregate([row])
    gates = notes_scoring.f2_gates(summary, baseline_recall=None)
    assert gates == {
        "copied_lines == 0": False,
        "no_information_lines == 0": False,
        "first_person_lines == 0": False,
    }


def test_the_recall_gate_allows_one_point() -> None:
    clean = {"copied_lines": 0, "no_information_lines": 0, "first_person_lines": 0}
    assert all(
        notes_scoring.f2_gates({**clean, "key_fact_recall": 0.60}, baseline_recall=0.61).values()
    )
    assert not all(
        notes_scoring.f2_gates({**clean, "key_fact_recall": 0.59}, baseline_recall=0.61).values()
    )


def test_the_r02_checklist_checks_topics_marks_and_copies() -> None:
    checklist = json.loads(
        (notes_assert.ASSERTIONS / "r02_en_pardo_65gt.assertions.json").read_text("utf-8")
    )
    good = {
        "note_text": "## Swim platform\n- A hybrid of both designs\n  - Fixed platform at the transom",
        "lines": [
            {"section_title": "Swim platform", "kind": "bullet", "text": "- A hybrid of both designs",
             "parent": False, "fact_ids": ["a"]},
            {"section_title": "Swim platform", "kind": "bullet", "text": "  - Fixed platform at the transom",
             "parent": True, "fact_ids": ["b"]},
        ],
    }  # fmt: skip
    results = {name: ok for name, ok, _s in notes_assert.check(checklist, good, _PARDO_LIKE)}
    assert results["no_copied_lines"] and results["no_marks"] and results["topics[0]"]
    bad = {
        "note_text": "## Swim platform\n- This boat is incredible. ❝",
        "lines": [{"section_title": "Swim platform", "kind": "bullet",
                   "text": "- This boat is incredible.", "parent": False, "fact_ids": ["a"]}],
    }  # fmt: skip
    results = {name: ok for name, ok, _s in notes_assert.check(checklist, bad, _PARDO_LIKE)}
    assert not results["no_copied_lines"] and not results["no_marks"] and not results["topics[0]"]
    assert not results["no_information_lines"]


def test_the_topics_round_rates_topic_bullets_only() -> None:
    ours = "Framing.\n\n## Swim platform\n- A hybrid\n  - fixed at the transom\n\n## Decisions\n- go blue"
    assert notes_pairs.topic_lines(ours) == "## Swim platform\n- A hybrid\n  - fixed at the transom"
    base = "Summary one.\nSummary two.\n\n- a decision\n\n- an action"
    assert notes_pairs.topic_lines(base, "single_pass") == "- Summary one.\n- Summary two."


# ── F3: figures, presenter, contact ─────────────────────────────────


def test_the_f3_scorers() -> None:
    gold = {
        "figures": [
            {"name": "beam", "value": "16.5", "unit": "feet", "qualifier": "a little over"},
            {"name": "fuel tank", "value": "700", "unit": "gallons", "qualifier": "about"},
            {"name": "cabins", "value": "3"},
        ],
        "presenter": {
            "name": "Corvin Aldmere",
            "role": "broker",
            "organisation": "Harbourline Yachts",
        },
        "contact": ["Questions by email or as a comment below the video"],
    }
    produced = {
        "facts": [
            {
                "figure": {
                    "name": "Beam",
                    "value": "16.5",
                    "unit": "feet",
                    "qualifier": "a little over",
                }
            },
            {"figure": {"name": "Fuel tank", "value": "800", "unit": "gallons", "qualifier": ""}},
        ]
    }
    lines = [
        {"kind": "presenter", "text": "Presenter: Corvin Aldmere, broker with Harbourline Yachts"},
        {"kind": "next_step", "text": "- Questions by email or as a comment below the video"},
    ]
    row = notes_scoring.score_f3(gold, produced, lines)
    assert row["figure_recall"] == [1, 3]
    assert row["figure_value_accuracy"] == [1, 2]  # the fuel figure is wrong: worse than none
    assert row["qualifier_preservation"] == [1, 1]
    assert row["presenter_accuracy"] == [3, 3]
    assert row["contact_present"] == [1, 1]
    gates = notes_scoring.f3_gates(notes_scoring.aggregate([row]))
    assert gates["figure_value_accuracy == 1.0"] is False
    assert gates["presenter_accuracy >= 0.9"] is True


def test_the_r02_checklist_checks_figures_presenter_and_contact() -> None:
    checklist = json.loads(
        (notes_assert.ASSERTIONS / "r02_en_pardo_65gt.assertions.json").read_text("utf-8")
    )
    produced = {
        "facts": [
            {"figure": {"name": "Length overall", "value": "66", "unit": "feet", "qualifier": ""}},
            {
                "figure": {
                    "name": "Water tank",
                    "value": "300",
                    "unit": "gallons",
                    "qualifier": "just under",
                }
            },
        ],
        "lines": [
            {"kind": "presenter", "fact_ids": ["p"], "text": checklist["presenter_line"]},
            {"kind": "figure", "fact_ids": ["a"], "text": "| Length overall | 66 feet |"},
            {"kind": "next_step", "fact_ids": ["c"], "text": "- Questions by email"},
        ],
    }
    results = {name: ok for name, ok, _s in notes_assert.check(checklist, produced, _PARDO_LIKE)}
    assert results["figures"] and results["figures_cited"]
    assert results["presenter_line"] and results["contact_line"]


# ── Support-gate calibration (F3 amendment after r03, §2.10) ────────

support_calibration = _load("support_calibration")


def test_calibration_picks_the_threshold_the_judge_agrees_with(tmp_path: Path) -> None:
    records = []
    # German: the judge accepts every line at ratio ≥ 0.35 and none below.
    for n in range(40):
        ratio = n / 40
        records.append(
            {
                "language": "de",
                "ratio": ratio,
                "rules_ok": True,
                "judge_supported": ratio >= 0.35,
                "text": "SECRET LINE",
            }  # fmt: skip
        )
    # English: too few lines to calibrate.
    records += [
        {"language": "en", "ratio": 0.6, "rules_ok": True, "judge_supported": True, "text": "x"}
    ] * 5
    # A line failing the number/name rules is unsupported at any threshold.
    records.append(
        {"language": "de", "ratio": 1.0, "rules_ok": False, "judge_supported": False, "text": "y"}
    )
    result = support_calibration.calibrate(records)
    de = result["de"]
    assert de["calibrated_threshold"] == 0.35
    assert de["at_calibrated"]["agreement"] == 1.0 and de["meets_target"]
    assert de["at_provisional"]["agreement"] < 1.0
    assert result["en"]["calibrated_threshold"] is None
    path = tmp_path / "lines.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), "utf-8")
    out = tmp_path / "report.json"
    import sys as _sys

    argv = _sys.argv
    _sys.argv = ["support_calibration.py", str(path), "--out", str(out)]
    try:
        assert support_calibration.main() == 0
    finally:
        _sys.argv = argv
    assert "SECRET LINE" not in out.read_text("utf-8")


def test_the_r03_checks_read_the_overview_the_guest_and_the_chapters() -> None:
    checklist = json.loads(
        (notes_assert.ASSERTIONS / "r03_de_palantir_podcast.assertions.json").read_text("utf-8")
    )
    framing = (
        "Podcast-Folge über Palantir. Es sprechen Erzähler/in und als Gast Felix Holtermann "
        "(Büroleiter beim Handelsblatt). Themen sind Thiel, Karp und Überwachung."
    )
    top = f"{framing}\n\nZunächst — Palantir wird 2004 gegründet."
    produced = {
        "language": "de",
        "stats": {
            "recording_type": "podcast_broadcast",
            "excluded_ranges": [[0, 20_000, "advertisement"]],
        },
        "brief": {"themes": ["Thiel", "Karp", "Überwachung"]},
        "sections": [
            {"section_key": "gen:overview", "role": "summary", "title": None, "text": top},
            *(
                {"section_key": f"gen:{n}", "role": "topics", "title": f"0{n}:00 — X", "text": "-"}
                for n in range(4)
            ),
        ],
        # SQ3 T2: the guest is named in paragraph 1, never on a "Gast:" line.
        "lines": [{"kind": "framing", "text": framing, "fact_ids": ["a"]}],
    }
    results = {name: ok for name, ok, _s in notes_assert.check(checklist, produced)}
    for name in (
        "excluded_reasons[0]",
        "guest_line",
        "chapters_min",
        "overview.prose_paragraphs_min",
        "overview.names_recording_type",
        "overview.names_guest",
        "overview.themes_min",
        "overview.bullets_above_first_heading",
    ):
        assert results[name], name
    assert notes_assert.family("overview.themes_min") == "overview"
    # A key-point list above the first heading fails two checks.
    produced["sections"][0]["text"] = top + "\n\n- a point"
    results = {name: ok for name, ok, _s in notes_assert.check(checklist, produced)}
    assert not results["overview.prose_paragraphs_min"]
    assert not results["overview.bullets_above_first_heading"]
    # Mentioned, but not among who speaks: not the guest line.
    produced["lines"][0]["text"] = (
        "Podcast-Folge über Felix Holtermann. Es sprechen Erzähler/in und Anna Berg."
    )
    results = {name: ok for name, ok, _s in notes_assert.check(checklist, produced)}
    assert not results["guest_line"]


# ── Error taxonomy (docs/eval/error-taxonomy.md) ────────────────────

taxonomy = _load("taxonomy")


def test_every_code_the_tools_use_is_in_the_taxonomy_document() -> None:
    doc = (REPO / "docs" / "eval" / "error-taxonomy.md").read_text("utf-8")
    documented = set(re.findall(r"^\| ([A-Z]-[A-Z]+) \|", doc, re.MULTILINE))
    assert documented == set(taxonomy.CODES)
    used = {
        *(c for codes in taxonomy.CHECK_CODES.values() for c in codes),
        *(c for codes in taxonomy.METRIC_CODES.values() for c in codes),
        *taxonomy.REASON_CODES.values(),
    }
    assert used <= set(taxonomy.CODES)


def test_every_scorer_metric_and_checklist_check_has_a_code() -> None:
    summary = notes_scoring.aggregate([{}])
    assert set(summary) <= set(taxonomy.METRIC_CODES), set(summary) - set(taxonomy.METRIC_CODES)
    for path in sorted(notes_assert.ASSERTIONS.glob("*.assertions.json")):
        checklist = json.loads(path.read_text("utf-8"))
        for name, _ok, _s in notes_assert.check(checklist, {"lines": [], "sections": []}):
            codes = taxonomy.check_codes(name, checklist)
            assert codes and set(codes) <= set(taxonomy.CODES), (path.name, name)


def test_every_asr_metric_has_a_code_or_a_reason_for_none() -> None:
    """Sprint TQ1 T3: the transcript harness's aggregate keys are coded."""
    asr_scoring = _load("asr_scoring")
    summary = asr_scoring.aggregate([])
    assert taxonomy.uncoded_metrics(summary) == []
    # And the rule has teeth: a new, uncoded key is caught.
    assert taxonomy.uncoded_metrics([*summary, "brand_new_rate"]) == ["brand_new_rate"]


def test_the_taxonomy_detectors() -> None:
    meeting = {
        "language": "de",
        "transcript": [{"t_start_ms": 0, "t_end_ms": 600_000, "text": "x", "speaker": "SPEAKER_1"}],
    }
    content = [
        {"kind": "framing", "text": "Podcast-Folge. Es sprechen Erzähler/in."},
        {"kind": "summary", "text": "Er ist genervt, dass er die Schuhe ausziehen muss."},
        {"kind": "summary", "text": "Zunächst — Peter Thiel gründet 2004 Palantir."},
        {"kind": "bullet", "text": "- Speaker 1 findet das schwierig"},
        {"kind": "bullet", "text": "- Ein riesiger Feuerball entsteht"},
        {"kind": "bullet", "text": "- Fast 3000 Menschen sterben"},
    ]
    produced = {"sections": [{"role": "topics", "title": "Gründung"}, {"role": "summary"}]}
    row = notes_scoring.score_taxonomy(meeting, produced, content, {"Peter Thiel"})
    assert row["label_lines"] == 1  # "Speaker 1"; the framing may name the narrator
    assert row["unresolved_subject"] == [1, 5]
    assert row["unspecific_bullets"] == [2, 3]
    assert row["volume"][1] == 600
    assert row["headings"] == [1, 600]
    summary = notes_scoring.aggregate([row])
    assert summary["headings_per_10_min"] == 1.0
    assert summary["unspecific_bullet_rate"] == 2 / 3


def test_the_lint_check_reads_the_engine_lint_per_code() -> None:
    checklist = {"id": "x", "lint": {"D-ORIENT": 0, "D-VOL": 0}}
    meeting = {
        "language": "en",
        "transcript": [{"t_start_ms": 0, "t_end_ms": 60_000, "text": "x", "speaker": "S"}],
    }
    produced = {
        "sections": [{"section_key": "gen:x", "role": "topics", "title": "Pricing", "text": ""}],
        "lines": [
            {
                "section_key": "gen:x",
                "kind": "bullet",
                "text": "- Acme pays 5 dollars",
                "fact_ids": ["a"],
            },
            {
                "section_key": "gen:x",
                "kind": "bullet",
                "text": "- Acme pays 6 dollars",
                "fact_ids": ["a"],
            },
        ],
        "facts": [],
    }
    results = {n: ok for n, ok, _s in notes_assert.check(checklist, produced, meeting)}
    assert results == {"lint[D-ORIENT]": False, "lint[D-VOL]": True}  # no overview
    assert taxonomy.check_codes("lint[D-ORIENT]") == ("D-ORIENT",)


# ── The document standard's blind rubric (§8) ───────────────────────


def test_rubric_round_trip_and_release_gate(tmp_path: Path, monkeypatch: Any) -> None:
    local = tmp_path / "local"
    monkeypatch.setattr(notes_pairs, "LOCAL", local)
    corpus = REPO / "tests" / "fixtures" / "eval" / "notes"
    arms = {"pipeline": local / "a", "comparison": local / "b"}
    for arm, folder in arms.items():
        folder.mkdir(parents=True)
        for mid in ("m01_en_product_sync", "m06_de_news_podcast"):
            (folder / f"{mid}.md").write_text(f"{arm} line one\n{arm} line two", "utf-8")
    out = local / "rubric"
    assert notes_pairs.rubric_build(arms, corpus, out, seed=2) == 0
    key = {r["note_id"]: r for r in csv.DictReader((out / "rubric_key.csv").open())}
    assert len(key) == 4
    page = (out / "n001.md").read_text("utf-8")
    assert "Q4 lines to check" in page and "Q7 band" in page and "Q8 Form" in page
    rows = [["note_id", "rater", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8"]]
    for note_id, k in key.items():
        ours = k["arm"] == "pipeline"
        for rater in ("r1", "r2", "r3"):
            scores = [2] * 8 if ours else [1, 2, 2, 0, 0, 2, 2, 2]
            if ours and rater == "r1":
                scores[3] = 1  # one rater finds an unsupported line; the median stays 2
            rows.append([note_id, rater, *scores])
    ratings = out / "ratings.csv"
    with ratings.open("w", newline="") as handle:
        csv.writer(handle).writerows(rows)
    result = notes_pairs.rubric_score(ratings, out / "rubric_key.csv")
    assert result["arms"]["pipeline"]["mean_total"] == 16
    assert result["arms"]["comparison"]["mean_total"] == 11  # the r03 comparison note's shape
    assert result["release_gate"] == {
        "mean_total": True,
        "faithful_share": True,
        "no_orientation_zero": True,
    }


# ── Sprint D2: composition scorers and gates ────────────────────────


def test_the_d2_scorers_read_an_enforced_note_end_to_end() -> None:
    sys.path.insert(0, str(REPO / "services" / "note-service" / "tests" / "unit"))
    from meeting_doc_fakes import ScriptedProvider

    harness = _load("notes_eval")
    meeting = json.loads(
        (REPO / "tests" / "fixtures" / "eval" / "notes" / "m06_de_news_podcast.json").read_text()
    )
    meeting["gold"]["roles"] = {"SPEAKER_1": "narrator"}
    produced = asyncio.run(harness.run_pipeline(meeting, ScriptedProvider()))
    row = notes_scoring.score_meeting(meeting, produced)
    for key in ("headings_pass", "bullets_specific", "children", "lint_first_pass"):
        assert key in row, key
    assert row["subject_failures"] == 0
    summary = notes_scoring.aggregate([row])
    gates = notes_scoring.d2_gates(summary)
    assert set(gates) >= {
        "d2_lint_first_pass_90pct",
        "d2_lint_after_regeneration_98pct",
        "d2_no_subject_failures",
        "d2_roles_correct_95pct",
    }
    assert gates["d2_no_subject_failures"]
