"""A1/A2 review step 4 — the two deterministic global assertions."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "eval"))

from notes_assert import global_checks, holder_named_per_run, overview_first  # noqa: E402


def _doc(lines: list[dict], facts: list[dict], sections: list[dict] | None = None) -> dict:
    return {"lines": lines, "facts": facts, "sections": sections or []}


def test_a_holder_named_once_covers_the_run_in_its_section() -> None:
    facts = [{"item_key": "f1", "certainty": "prediction", "attributed_to": "Marek Quill"}]
    ok = _doc(
        [
            {
                "section_key": "gen:a",
                "kind": "bullet",
                "text": "- Marek Quill expects slippage.",
                "fact_ids": ["f1"],
            },
            {
                "section_key": "gen:a",
                "kind": "bullet",
                "text": "- They expect short card stock.",
                "fact_ids": ["f1"],
            },
        ],
        facts,
    )
    assert holder_named_per_run(ok)
    other_section = _doc(
        [
            {
                "section_key": "gen:a",
                "kind": "bullet",
                "text": "- Marek Quill expects slippage.",
                "fact_ids": ["f1"],
            },
            {
                "section_key": "gen:b",
                "kind": "bullet",
                "text": "- They expect short card stock.",
                "fact_ids": ["f1"],
            },
        ],
        facts,
    )
    assert not holder_named_per_run(other_section)
    assert holder_named_per_run(_doc([], []))
    # A holder written as "Name, Role" is named by the name.
    role = [
        {
            "item_key": "f2",
            "certainty": "statement",
            "attributed_to": "Bernd Walzmann, Finanzminister",
        }
    ]
    named = _doc(
        [
            {
                "section_key": "gen:o",
                "kind": "framing",
                "text": "Bernd Walzmann and Karla Sommerfeld speak.",
                "fact_ids": ["f2"],
            }
        ],
        role,
    )
    assert holder_named_per_run(named)
    # One speaker or a memo (review step 3): attribution is implicit, the run rule is off.
    implicit = {**other_section, "stats": {"attribution_implicit": True}}
    assert holder_named_per_run(implicit)


def test_the_overview_comes_first_and_the_transcript_never_does() -> None:
    first = [{"role": "summary", "text": "An overview."}, {"role": "transcript", "text": "x"}]
    assert overview_first({"sections": first})
    empty_then = [
        {"role": "key_dates", "text": "", "lines": []},
        {"role": "summary", "text": "An overview."},
    ]
    assert overview_first({"sections": empty_then})
    transcript_first = [
        {"role": "transcript", "text": "x"},
        {"role": "summary", "text": "An overview."},
    ]
    assert not overview_first({"sections": transcript_first})


def test_the_five_global_checks_are_reported() -> None:
    names = [n for n, _ in global_checks({"lines": [], "facts": [], "sections": []})]
    assert names == [
        "no_repeated_holder_suffix",
        "no_impersonal_claim",
        "p1_not_label",
        "holder_named_per_run",
        "overview_first",
    ]
