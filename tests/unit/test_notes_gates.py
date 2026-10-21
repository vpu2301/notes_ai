"""The notes eval's gates: regression checklists, the nightly comparison and the judge column."""

from __future__ import annotations

import asyncio
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
        "no_copied_lines",
        "no_information_lines_max",
        "no_marks",
        "topics",
        "figures",
        "figures_min",
        "presenter_line",
        "contact_line",
        "excluded_reasons",
        "guest_line",
        "chapters_min",
        "overview",
        "headings_must_not_match",
        "framing_must_not_contain",
        "claims_row",
        # The original generation's numbers and the sentinel of a regression case (B1)
        "original_generation",
        "sentinel",
        # Codes pinned per check
        "codes",
        # Lint findings allowed per code
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


# ── Statements, not quotes ──────────────────────────────────────


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


def test_the_r03_checks_read_the_overview_the_guest_and_the_chapters() -> None:
    checklist = json.loads(
        (notes_assert.ASSERTIONS / "r03_de_palantir_podcast.assertions.json").read_text("utf-8")
    )
    framing = (
        "Sendung über Palantir. Es sprechen Erzähler/in und als Gast Felix Holtermann "
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
        # The guest is named in paragraph 1, never on a "Gast:" line.
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


# ── Error taxonomy ────────────────────

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
