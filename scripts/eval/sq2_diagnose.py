#!/usr/bin/env python3
"""Sprint SQ2 T1 — why a note misses the middle and end of a recording.

    uv run python scripts/eval/sq2_diagnose.py REPORT.json [REPORT.json …] \\
        --out docs/eval/sq2-diagnosis-<date>.md

Reads ``notes_eval.py`` pipeline reports (each meeting row carries the
engine's per-window numbers since SQ2 T1) and writes, per report, the
per-window table and one verdict per hypothesis:

* **H1** later windows failed (``call_failed`` in thirds 2–3);
* **H2** the small-model profile starves long windows (fixed budget hit);
* **H3** the merge drops later facts (kept ÷ verified in thirds 2–3 ≪ third 1);
* **H4** reduce cites only the head (cited ÷ available per third uneven);
* **H5** noise exclusion removed content (excluded share of speech);
* **H6** a one-section family (one block planned for ≥ 5 minutes);
* **H7** (added in SQ2) the model lists the head of each window
  (facts in the window's second half ≪ its first half);
* **H8** (added in SQ2) the window's fact budget binds on any profile
  (the model returns as many facts as it may, so the cap, not the
  recording, decides where the list stops).

Numbers and meeting ids only — never transcript or note text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

THIRDS = (1, 2, 3)
# Verdict thresholds, fixed before any run is read.
H1_FAILED_LATE = 1  # any failed window in thirds 2–3
H2_CAP_SHARE = 0.5  # half the small-profile windows filled the fixed budget
H2_FIXED = 12
H3_RATIO = 0.7  # kept/verified in a later third below 0.7 × third 1's
H4_RATIO = 0.5  # cited/available in the worst third below 0.5 × the best
H5_SHARE = 0.10  # more than a tenth of the speech excluded
H6_MINUTES = 5.0
H7_RATIO = 0.5  # second-half facts below half of first-half facts
H7_MIN_CHARS = 4_000
H8_SHARE = 0.5  # half the long windows returned their whole budget


def _third(ms: float, start: int, end: int) -> int:
    share = (ms - start) / max(1, end - start)
    return 1 if share < 1 / 3 else (2 if share < 2 / 3 else 3)


def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def meeting_numbers(row: dict[str, Any]) -> dict[str, Any] | None:
    stats = row.get("stats") or {}
    wins = [w for w in stats.get("windows") or [] if isinstance(w, dict)]
    if not wins:
        return None
    first = [w for w in wins if not w.get("coverage_retry")]
    start = min(w["start_ms"] for w in first)
    end = max(w["end_ms"] for w in first)
    by_third: dict[int, dict[str, int]] = {
        t: {"verified": 0, "kept": 0, "failed": 0, "windows": 0} for t in THIRDS
    }
    for w in first:
        t = _third((w["start_ms"] + w["end_ms"]) / 2, start, end)
        by_third[t]["windows"] += 1
        by_third[t]["verified"] += w.get("facts_verified", 0)
        by_third[t]["kept"] += w.get("facts_kept_after_merge", 0)
        by_third[t]["failed"] += w.get("call_failed", 0)
    facts = stats.get("facts_by_third") or [0, 0, 0]
    cited = stats.get("reduce_cited_by_third") or [0, 0, 0]
    recall = row.get("recall_by_third") or {}
    long_windows = [w for w in first if w.get("chars", 0) >= H7_MIN_CHARS]
    return {
        "meeting": row.get("meeting"),
        "minutes": round((stats.get("speech_ms") or 0) / 60_000, 1),
        "windows": first,
        "retry_windows": [w for w in wins if w.get("coverage_retry")],
        "by_third": by_third,
        "facts_by_third": facts,
        "cited_by_third": cited,
        "recall_by_third": {t: recall.get(str(t)) for t in THIRDS},
        "key_fact_recall": row.get("key_fact_recall"),
        "excluded_share": _ratio(
            stats.get("excluded_speech_ms", stats.get("excluded_ms", 0)) or 0,
            stats.get("speech_ms") or 0,
        ),
        "blocks_planned": stats.get("blocks_planned", stats.get("blocks")),
        "blocks_rendered": stats.get("blocks_rendered"),
        "sections": row.get("sections"),
        "small": bool(stats.get("small_model_profile")),
        "window_chars": stats.get("window_chars"),
        "first_half": sum(w.get("facts_first_half", 0) for w in long_windows),
        "second_half": sum(w.get("facts_second_half", 0) for w in long_windows),
        "recording_type": stats.get("recording_type"),
    }


def verdicts(meetings: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """``{H: (held | ruled out, the number it rests on)}`` over a report."""
    out: dict[str, tuple[str, str]] = {}
    late_failed = sum(m["by_third"][t]["failed"] for m in meetings for t in (2, 3))
    all_failed = sum(m["by_third"][t]["failed"] for m in meetings for t in THIRDS)
    out["H1"] = (
        "held" if late_failed >= H1_FAILED_LATE else "ruled out",
        f"{late_failed} failed window(s) in thirds 2–3 ({all_failed} in all)",
    )
    small = [w for m in meetings if m["small"] for w in m["windows"]]
    if not small:
        out["H2"] = ("ruled out", "backend is not small_model; facts per character are constant")
    else:
        capped = sum(1 for w in small if w.get("facts_extracted", 0) >= H2_FIXED)
        share = capped / len(small)
        out["H2"] = (
            "held" if share >= H2_CAP_SHARE else "ruled out",
            f"{capped}/{len(small)} small-profile windows filled the fixed {H2_FIXED}",
        )
    kept = {t: sum(m["by_third"][t]["kept"] for m in meetings) for t in THIRDS}
    ver = {t: sum(m["by_third"][t]["verified"] for m in meetings) for t in THIRDS}
    keep = {t: _ratio(kept[t], ver[t]) for t in THIRDS}
    first = keep[1] or 0
    worst_late = min((keep[t] for t in (2, 3) if keep[t] is not None), default=None)
    out["H3"] = (
        "held"
        if worst_late is not None and first and worst_late < H3_RATIO * first
        else "ruled out",
        "kept/verified by third: "
        + " / ".join("—" if keep[t] is None else f"{keep[t]:.2f}" for t in THIRDS),
    )
    avail = [sum(m["facts_by_third"][k] for m in meetings) for k in range(3)]
    cited = [sum(m["cited_by_third"][k] for m in meetings) for k in range(3)]
    share = [_ratio(cited[k], avail[k]) for k in range(3)]
    known = [s for s in share if s is not None]
    out["H4"] = (
        "held" if known and max(known) and min(known) < H4_RATIO * max(known) else "ruled out",
        "cited/available by third: " + " / ".join("—" if s is None else f"{s:.2f}" for s in share),
    )
    excl = [m["excluded_share"] for m in meetings if m["excluded_share"] is not None]
    worst = max(excl, default=0.0)
    out["H5"] = (
        "held" if worst > H5_SHARE else "ruled out",
        f"largest excluded share of speech {worst:.2f}",
    )
    one = [
        m["meeting"]
        for m in meetings
        if m["minutes"] >= H6_MINUTES and (m["blocks_planned"] or 0) <= 1
    ]
    out["H6"] = (
        "held" if one else "ruled out",
        f"{len(one)} recording(s) ≥ {H6_MINUTES:g} min with one block planned",
    )
    fh = sum(m["first_half"] for m in meetings)
    sh = sum(m["second_half"] for m in meetings)
    out["H7"] = (
        "held" if fh and sh < H7_RATIO * fh else "ruled out",
        f"facts in windows' first / second half: {fh} / {sh}",
    )
    long_w = [
        w
        for m in meetings
        for w in m["windows"]
        if w.get("chars", 0) >= H7_MIN_CHARS and w.get("budget")
    ]
    full = sum(1 for w in long_w if w.get("facts_extracted", 0) >= w["budget"])
    out["H8"] = (
        "held" if long_w and full / len(long_w) >= H8_SHARE else "ruled out",
        f"{full}/{len(long_w)} windows of ≥ {H7_MIN_CHARS} characters returned their whole budget",
    )
    return out


def _fmt3(values: Any) -> str:
    return " / ".join(str(v) for v in values)


def _recall3(rec: dict[int, Any]) -> str:
    parts = []
    for t in THIRDS:
        v = rec.get(t)
        parts.append(f"{v[0]}/{v[1]}" if isinstance(v, list) and len(v) == 2 else "—")
    return " · ".join(parts)


def render(report: dict[str, Any], path: Path) -> str:
    rows = [r for run in report.get("runs", []) for r in run.get("meetings", [])]
    meetings = [m for m in (meeting_numbers(r) for r in rows if not r.get("failed")) if m]
    lines = [
        f"### {report.get('backend')} · `{report.get('model_id')}` · "
        f"context {report.get('context_window')} · small profile "
        f"{'on' if report.get('small_model_profile') else 'off'}",
        "",
        f"Report: `{path.name}` · prompt `{report.get('prompt_version')}` · git `{report.get('git')}`",
        "",
        "| Recording | Min | Windows (chars) | Extracted (of budget) → verified → kept | "
        "1st/2nd half | Failed | Facts by third | Cited by third | Recall by third | "
        "Blocks | Excluded |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in meetings:
        per = " · ".join(
            f"{w.get('facts_extracted', 0)}"
            + (f" of {w['budget']}" if w.get("budget") else "")
            + f"→{w.get('facts_verified', 0)}→"
            f"{w.get('facts_kept_after_merge', 0)}"
            for w in m["windows"]
        )
        halves = " · ".join(
            f"{w.get('facts_first_half', 0)}/{w.get('facts_second_half', 0)}" for w in m["windows"]
        )
        chars = ", ".join(str(w.get("chars", 0)) for w in m["windows"])
        failed = sum(w.get("call_failed", 0) for w in m["windows"])
        excluded = "—" if m["excluded_share"] is None else f"{m['excluded_share']:.2f}"
        lines.append(
            f"| {m['meeting']} | {m['minutes']} | {len(m['windows'])} ({chars}) | {per} | "
            f"{halves} | {failed} | {_fmt3(m['facts_by_third'])} | {_fmt3(m['cited_by_third'])} | "
            f"{_recall3(m['recall_by_third'])} | {m['blocks_planned']} | "
            f"{excluded} |"
        )
    lines += ["", "| Hypothesis | Verdict | Number |", "|---|---|---|"]
    for h, (verdict, number) in verdicts(meetings).items():
        lines.append(f"| {h} | {verdict} | {number} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ns = ap.parse_args(argv)
    parts = [render(json.loads(p.read_text("utf-8")), p) for p in ns.reports]
    text = "\n".join(parts)
    if ns.out:
        ns.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
