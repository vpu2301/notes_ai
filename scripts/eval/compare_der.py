"""Fail when speaker-count accuracy regressed against a committed DER report.

    uv run python scripts/eval/compare_der.py --baseline <a.json> --current <b.json> --n-speakers 2 --max-drop 0.05

Exit 1 on a drop beyond ``--max-drop`` (absolute); exit 2 when a bucket is missing (never a pass).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def bucket(report: dict[str, Any], n_speakers: int) -> dict[str, Any] | None:
    value = report.get("by_n_speakers", {}).get(str(n_speakers))
    return value if isinstance(value, dict) else None


def compare(
    baseline: dict[str, Any], current: dict[str, Any], *, n_speakers: int, max_drop: float
) -> tuple[int, str]:
    before, after = bucket(baseline, n_speakers), bucket(current, n_speakers)
    if before is None or after is None:
        missing = "baseline" if before is None else "current"
        return 2, f"no {n_speakers}-speaker bucket in the {missing} report"
    drop = float(before["count_exact"]) - float(after["count_exact"])
    line = (
        f"{n_speakers}-speaker count_exact {before['count_exact']:.3f} → "
        f"{after['count_exact']:.3f} ({after['files']} files; drop {drop:+.3f}, "
        f"allowed {max_drop:.3f})"
    )
    return (1 if drop > max_drop + 1e-9 else 0), line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--n-speakers", type=int, default=2)
    parser.add_argument("--max-drop", type=float, default=0.05)
    args = parser.parse_args(argv)
    code, line = compare(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.current.read_text(encoding="utf-8")),
        n_speakers=args.n_speakers,
        max_drop=args.max_drop,
    )
    print(("REGRESSION: " if code == 1 else "") + line, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
