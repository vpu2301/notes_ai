"""Sprint SQ3 — the scorers and gates read by code (D-FORM, order, filler)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "eval"))

import notes_scoring as scoring  # noqa: E402
import taxonomy  # noqa: E402


def _produced(lines: list[dict]) -> dict:
    facts = [{"item_key": k, "start_ms": ms} for k, ms in (("a", 0), ("b", 60_000), ("c", 120_000))]
    return {"facts": facts, "lines": lines}


def test_speaker_shaped_paragraphs_are_counted_bullets_are_not() -> None:
    row = scoring.score_sq3(
        _produced(
            [
                {"kind": "summary", "text": "Vorwurf: Iran griff an."},
                {"kind": "summary", "text": "Vorwurf — Iran griff an."},
                {"kind": "bullet", "text": "- Vorwurf: Iran griff an.", "fact_ids": ["a"]},
                {"kind": "framing", "text": "Es sprechen Anna und Ben."},
            ]
        ),
        {"redundancy": [0, 4]},
    )
    assert row["speaker_shaped_lines"] == 1


def test_an_inverted_bullet_pair_is_counted() -> None:
    lines = [
        {"kind": "bullet", "section_key": "s", "text": "- x", "fact_ids": ["b"]},
        {"kind": "bullet", "section_key": "s", "text": "- y", "fact_ids": ["a"]},
        {"kind": "bullet", "section_key": "t", "text": "- z", "fact_ids": ["c"]},
    ]
    assert scoring.score_sq3(_produced(lines), {})["order_inversions"] == 1


def test_redundancy_ok_is_per_document() -> None:
    assert scoring.score_sq3(_produced([]), {"redundancy": [1, 10]})["redundancy_ok"] == 0
    assert scoring.score_sq3(_produced([]), {"redundancy": [0, 10]})["redundancy_ok"] == 1


def test_gates_and_codes() -> None:
    summary = {
        "speaker_shaped_lines": 0,
        "label_lines": 0,
        "filler_lines": 0,
        "redundancy_ok_rate": 1.0,
        "order_inversions": 0,
        "title_ok": 1.0,
    }
    gates = scoring.sq3_gates(summary)
    assert gates and all(gates.values())
    assert not scoring.sq3_gates({**summary, "order_inversions": 2})["sq3_order_inversions_zero"]
    assert (
        taxonomy.uncoded_metrics(("speaker_shaped_lines", "order_inversions", "redundancy_ok_rate"))
        == []
    )
