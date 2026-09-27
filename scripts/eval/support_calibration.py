"""Support-gate calibration per language (F3 amendment after r03, §2.10).

The line gate keeps a composed line when enough of its content words are in
the facts it cites (``meeting_doc.support.support_ratio``) and its numbers
and names are too. This script sets the threshold per language from the
judge column: the value at which the deterministic gate agrees with the
judge most often, reported with its disagreement rate.

    # 1. judge every composed line, keeping one record per line (local only)
    python scripts/eval/notes_eval.py --backend dev_mac --judge <strong judge> \\
        --corpus <eval/notes/v2> --judge-lines scripts/eval/local/judge/lines.jsonl
    # 2. calibrate
    python scripts/eval/support_calibration.py scripts/eval/local/judge/lines.jsonl

The report carries numbers only — never a line's text. A language with
fewer than ``MIN_LINES`` judged lines is reported, not calibrated: its
provisional threshold stays. Target: agreement ≥ 95 % per language.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO  # noqa: E402

sys.path.insert(0, str(REPO / "services" / "note-service" / "src"))
from note_service.domain.meeting_doc import support as support_rules  # noqa: E402

TARGET_AGREEMENT = 0.95
MIN_LINES = 30
GRID = [round(0.20 + 0.05 * k, 2) for k in range(13)]  # 0.20 … 0.80


def _agreement(records: list[dict[str, Any]], threshold: float) -> dict[str, float]:
    agree = accept_wrong = reject_wrong = 0
    for r in records:
        gate = bool(r["rules_ok"]) and float(r["ratio"]) >= threshold
        judge = bool(r["judge_supported"])
        if gate == judge:
            agree += 1
        elif gate:
            accept_wrong += 1  # the gate writes a line the judge calls unsupported
        else:
            reject_wrong += 1  # the gate drops a line the judge accepts
    n = len(records)
    return {
        "agreement": agree / n,
        "gate_accepts_unsupported": accept_wrong / n,
        "gate_rejects_supported": reject_wrong / n,
    }


def calibrate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_language[r.get("language") or "en"].append(r)
    out: dict[str, Any] = {}
    for language, rows in sorted(by_language.items()):
        provisional = support_rules.line_support_threshold(language)
        current = _agreement(rows, provisional)
        entry: dict[str, Any] = {
            "lines": len(rows),
            "judge_unsupported_rate": sum(1 for r in rows if not r["judge_supported"]) / len(rows),
            "provisional_threshold": provisional,
            "at_provisional": current,
        }
        if len(rows) < MIN_LINES:
            entry["calibrated_threshold"] = None
            entry["note"] = f"fewer than {MIN_LINES} judged lines: not calibrated"
        else:
            # Best agreement; on a tie, the value nearest the provisional
            # one, then the stricter.
            scored = [(t, _agreement(rows, t)) for t in GRID]
            best_t, best = max(
                scored,
                key=lambda ts: (round(ts[1]["agreement"], 6), -abs(ts[0] - provisional), ts[0]),
            )
            entry["calibrated_threshold"] = best_t
            entry["at_calibrated"] = best
            entry["meets_target"] = best["agreement"] >= TARGET_AGREEMENT
            entry["sweep"] = {f"{t:.2f}": round(a["agreement"], 4) for t, a in scored}
        out[language] = entry
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lines", type=Path, nargs="+", help="JSONL from notes_eval --judge-lines")
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "docs" / "eval" / f"support-calibration-{date.today().isoformat()}.json",
    )
    args = ap.parse_args()
    records: list[dict[str, Any]] = []
    for path in args.lines:
        for line in path.read_text("utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    if not records:
        print("no judged lines", file=sys.stderr)
        return 2
    report = {
        "target_agreement": TARGET_AGREEMENT,
        "min_lines": MIN_LINES,
        "compound_min": support_rules.COMPOUND_MIN,
        "languages": calibrate(records),
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{'lang':<5} {'lines':>5} {'prov':>5} {'agree':>6} {'calib':>6} {'agree':>6}  target")
    for language, e in report["languages"].items():
        calibrated = e.get("calibrated_threshold")
        at = e.get("at_calibrated", {}).get("agreement")
        print(
            f"{language:<5} {e['lines']:>5} {e['provisional_threshold']:>5.2f} "
            f"{e['at_provisional']['agreement']:>6.3f} "
            f"{'-' if calibrated is None else f'{calibrated:.2f}':>6} "
            f"{'-' if at is None else f'{at:.3f}':>6}  "
            f"{'met' if e.get('meets_target') else 'not met' if calibrated else '-'}"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
