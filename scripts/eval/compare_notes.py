"""Fail when the notes eval regressed against a committed baseline report.

    uv run python scripts/eval/compare_notes.py \\
        --baseline docs/eval/notes-baseline-pipeline.json \\
        --current  docs/eval/notes-pipeline-2026-09-24-dev_mac.json

Summary Engine v2, Q1 T8 — the nightly job's gate, mirroring
``compare_der.py``. It compares the first run's summary of each report
and fails (exit 1) when:

* ``unsupported_rate`` rose by more than ``--max-unsupported-rise`` (0.01),
* ``invented_claims`` is above zero,
* ``example_echo`` is above zero,
* ``key_fact_recall`` dropped by more than ``--max-recall-drop`` (0.02).

A metric missing from either report exits 2: a comparison that cannot be
made is not a pass. The baseline changes only in a PR that carries the
new report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def summary(report: dict[str, Any]) -> dict[str, Any]:
    runs = report.get("runs") or []
    return (runs[0].get("summary") if runs else None) or {}


def compare(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    max_unsupported_rise: float,
    max_recall_drop: float,
) -> tuple[int, list[str]]:
    before, after = summary(baseline), summary(current)
    needed = ("unsupported_rate", "key_fact_recall", "invented_claims", "example_echo")
    missing = [
        k for k in needed if after.get(k) is None or (k in needed[:2] and before.get(k) is None)
    ]
    if missing:
        return 2, [f"cannot compare: {', '.join(missing)} missing"]

    lines: list[str] = []
    code = 0
    rise = float(after["unsupported_rate"]) - float(before["unsupported_rate"])
    bad = rise > max_unsupported_rise + 1e-9
    lines.append(
        f"{'REGRESSION: ' if bad else ''}unsupported_rate {before['unsupported_rate']:.3f} → "
        f"{after['unsupported_rate']:.3f} (rise {rise:+.3f}, allowed {max_unsupported_rise:.3f})"
    )
    code |= int(bad)

    drop = float(before["key_fact_recall"]) - float(after["key_fact_recall"])
    bad = drop > max_recall_drop + 1e-9
    lines.append(
        f"{'REGRESSION: ' if bad else ''}key_fact_recall {before['key_fact_recall']:.3f} → "
        f"{after['key_fact_recall']:.3f} (drop {drop:+.3f}, allowed {max_recall_drop:.3f})"
    )
    code |= int(bad)

    for key in ("invented_claims", "example_echo"):
        bad = int(after[key]) > 0
        lines.append(f"{'REGRESSION: ' if bad else ''}{key} = {after[key]} (allowed 0)")
        code |= int(bad)
    return code, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--max-unsupported-rise", type=float, default=0.01)
    parser.add_argument("--max-recall-drop", type=float, default=0.02)
    args = parser.parse_args(argv)
    code, lines = compare(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.current.read_text(encoding="utf-8")),
        max_unsupported_rise=args.max_unsupported_rise,
        max_recall_drop=args.max_recall_drop,
    )
    for line in lines:
        print(line, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
