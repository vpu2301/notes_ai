#!/usr/bin/env python3
"""Sprint TQ1 T4 — the nightly ASR gate (ADR-0019, amended).

    python scripts/eval/compare_asr.py --baseline docs/eval/asr-baseline-inproc_cpu_asr-test.json \\
        --current docs/eval/asr-<date>-inproc_cpu_asr-test-nightly.json [--max-drop '{"wer": 0.01}']

Per language (de, uk, en) and for the whole split:

- ``wer`` may not rise by more than 1.0 pp (``0.010``);
- TR-02 (``halluc_chars_per_nonspeech_min``, ``artefact_hits``) and TR-03
  (``speech_coverage``, ``unexplained_gaps``) may not worsen.

The tolerances are ``DEFAULT_MAX_DROP``; ``--max-drop`` (or ``MAX_DROP`` in
the environment, JSON) overrides single metrics. A comparison it cannot make
(another backend, split or corpus manifest; a language measured on one side
only) is refused with exit 2 — never read as a pass. Exit 1 on a regression.
Output is metric names and numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# metric → (direction, tolerance). "up" = higher is worse.
DEFAULT_MAX_DROP: dict[str, tuple[str, float]] = {
    "wer": ("up", 0.010),
    "halluc_chars_per_nonspeech_min": ("up", 0.0),
    "artefact_hits": ("up", 0.0),
    "speech_coverage": ("down", 0.0),
    "unexplained_gaps": ("up", 0.0),
}
GROUPS = ("de", "uk", "en", "all")


class IncomparableError(Exception):
    pass


def compare(
    baseline: dict[str, Any], current: dict[str, Any], max_drop: dict[str, float] | None = None
) -> list[str]:
    """Regressions as lines; empty when the current run holds the line."""
    for key in ("backend", "split", "corpus_manifest_sha256"):
        if baseline.get(key) != current.get(key):
            raise IncomparableError(
                f"{key}: baseline {baseline.get(key)!r} ≠ current {current.get(key)!r}"
            )
    rules = {k: (d, (max_drop or {}).get(k, tol)) for k, (d, tol) in DEFAULT_MAX_DROP.items()}
    out: list[str] = []
    for group in GROUPS:
        b = baseline["by_language"].get(group)
        c = current["by_language"].get(group)
        if b is None or c is None or b.get("not_measured") or c.get("not_measured"):
            if (b and not b.get("not_measured")) != (c and not c.get("not_measured")):
                raise IncomparableError(f"{group}: measured on one side only")
            continue
        if b["n"] != c["n"]:
            raise IncomparableError(f"{group}: n {b['n']} ≠ {c['n']}")
        for metric, (direction, tol) in rules.items():
            bv, cv = b.get(metric), c.get(metric)
            if bv is None and cv is None:
                continue
            if bv is None or cv is None:
                raise IncomparableError(f"{group}.{metric}: measured on one side only")
            delta = cv - bv if direction == "up" else bv - cv
            if delta > tol + 1e-12:
                out.append(f"{group}.{metric}: {bv} → {cv} (worse by {delta:.4f}, allowed {tol})")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--current", type=Path, required=True)
    ap.add_argument(
        "--max-drop", default=os.environ.get("MAX_DROP", ""), help="JSON {metric: tolerance}"
    )
    ap.add_argument(
        "--inject-wer-pp",
        type=float,
        default=0.0,
        help="drill: add this many WER points to every measured language of --current before comparing",
    )
    args = ap.parse_args(argv)
    overrides = json.loads(args.max_drop) if args.max_drop.strip().startswith("{") else {}
    baseline = json.loads(args.baseline.read_text("utf-8"))
    current = json.loads(args.current.read_text("utf-8"))
    if args.inject_wer_pp:
        print(f"DRILL: +{args.inject_wer_pp} pp WER injected into the current report")
        for agg in current["by_language"].values():
            if agg.get("wer") is not None:
                agg["wer"] = round(agg["wer"] + args.inject_wer_pp / 100, 6)
    try:
        regressions = compare(baseline, current, overrides)
    except IncomparableError as exc:
        print(f"REFUSED: {exc}")
        return 2
    for line in regressions:
        print(f"REGRESSION {line}")
    if regressions:
        return 1
    print("PASS: no ASR metric regressed beyond its tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
