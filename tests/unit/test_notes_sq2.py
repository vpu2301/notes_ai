"""The coverage scoring, gates and diagnosis verdicts."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "eval"))

import notes_scoring as scoring  # noqa: E402
import sq2_diagnose  # noqa: E402
import taxonomy  # noqa: E402


def _meeting(minutes: float) -> dict:
    return {"transcript": [{"t_start_ms": 0, "t_end_ms": int(minutes * 60_000), "text": "x"}]}


def _produced(bullets_per_section: list[int], cited_summary: int = 1) -> dict:
    sections = [{"section_key": "gen:overview", "role": "summary"}]
    lines = [
        {"section_key": "gen:overview", "kind": "summary", "fact_ids": ["f"]}
        for _ in range(cited_summary)
    ]
    for n, count in enumerate(bullets_per_section):
        key = f"gen:topic:{n}"
        sections.append({"section_key": key, "role": "topics"})
        lines += [{"section_key": key, "kind": "bullet", "fact_ids": ["f"]} for _ in range(count)]
    return {"sections": sections, "lines": lines}


def test_one_bullet_sections_and_near_empty() -> None:
    row = scoring.score_sq2(_meeting(10), _produced([3, 1, 2]))
    assert row == {"one_bullet_sections": 1, "near_empty": 0}
    assert scoring.score_sq2(_meeting(10), _produced([], cited_summary=2))["near_empty"] == 1
    assert scoring.score_sq2(_meeting(1), _produced([]))["near_empty"] is None


def test_the_gates() -> None:
    passing = {
        "key_fact_recall": 0.72,
        "by_third_ratio": 0.85,
        "sections_count_ok": 0.95,
        "near_empty_rate": 0.0,
        "one_bullet_sections": 0,
        "unsupported_rate": 0.05,
        "seconds_per_meeting_hour_p95": 250,
    }
    gates = scoring.sq2_gates(passing, baseline_unsupported=0.09, staging=True)
    assert gates and all(gates.values())
    failing = {**passing, "by_third_ratio": 0.5, "unsupported_rate": 0.2}
    gates = scoring.sq2_gates(failing, baseline_unsupported=0.09)
    assert not gates["sq2_by_third_ratio_80pct"] and not gates["sq2_unsupported_not_above_sq1"]
    assert "sq2_p95_seconds_per_meeting_hour_300" not in gates  # not on staging


def test_new_metrics_have_codes() -> None:
    keys = ("sections_count_ok", "near_empty_rate", "one_bullet_sections")
    assert taxonomy.uncoded_metrics(keys) == []
    assert taxonomy.uncoded_metrics(("seconds_per_meeting_hour_p95",)) == []


def _window(index: int, start: int, end: int, **kw: int) -> dict:
    return {
        "index": index,
        "start_ms": start,
        "end_ms": end,
        "chars": kw.pop("chars", 6_000),
        "budget": kw.pop("budget", 24),
        "facts_extracted": kw.pop("extracted", 10),
        "facts_verified": kw.pop("verified", 10),
        "facts_kept_after_merge": kw.pop("kept", 10),
        "call_failed": kw.pop("failed", 0),
        "facts_first_half": kw.pop("first", 5),
        "facts_second_half": kw.pop("second", 5),
    }


def test_the_verdicts_rest_on_the_numbers() -> None:
    row = {
        "meeting": "x",
        "stats": {
            "speech_ms": 30 * 60_000,
            "windows": [
                _window(0, 0, 600_000, first=10, second=1, extracted=24),
                _window(1, 600_000, 1_200_000, failed=1, verified=0, kept=0),
                _window(2, 1_200_000, 1_800_000, kept=3, first=8, second=1),
            ],
            "facts_by_third": [10, 0, 3],
            "reduce_cited_by_third": [5, 0, 0],
            "excluded_speech_ms": 0,
            "blocks_planned": 4,
        },
    }
    m = sq2_diagnose.meeting_numbers(row)
    assert m is not None
    v = sq2_diagnose.verdicts([m])
    assert v["H1"][0] == "held"
    assert v["H2"][0] == "ruled out"
    assert v["H3"][0] == "held"  # third 3 kept 3 of 10
    assert v["H4"][0] == "held"
    assert v["H5"][0] == "ruled out"
    assert v["H6"][0] == "ruled out"
    assert v["H7"][0] == "held"
    assert v["H8"][0] == "ruled out"  # one of three windows used its budget
