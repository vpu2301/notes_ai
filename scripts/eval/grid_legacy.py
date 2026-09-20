"""B-4 guard-rail grid for the legacy clusterer, with the pre-registered ship rule.

    uv run --with 'pyannote.metrics>=3.2,<4' python scripts/eval/grid_legacy.py

1. Every config below runs on the DEV split (embeddings cached per file,
   chunking and VAD setting, so the grid re-clusters without re-embedding).
2. Winner = best ``count_exact``, ties by DER.
3. Winner vs defaults on the TEST split. SHIP only if overcount falls
   ≥ 50 % relative AND DER rises ≤ 2 points AND undercount ≤ 5 % of files.
Writes docs/eval/grid-<date>-legacy.json; the verdict goes into ADR-0052.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import REPO, write_report  # noqa: E402
from run_der import (  # noqa: E402
    AUDIO_DIR,
    MANIFEST,
    LegacyModels,
    aggregate,
    evaluate,
    legacy_engine,
    load_entries,
)

# chunk_target_ms → cluster_chunk_min_ms: tied so the grid stays ≤ 300 configs.
CHUNKING = {1500: 500, 2000: 700, 3000: 1000}
GRID = {
    "min_speaker_speech_ms": (5000, 8000, 12000),
    "min_speaker_share": (0.02, 0.03, 0.05),
    "chunk_target_ms": tuple(CHUNKING),
    "centroid_merge_threshold": (0.45, 0.50, 0.55, 0.60),
    "vad_threshold": (0.5, 0.6),
}


def configs() -> list[dict[str, Any]]:
    keys = list(GRID)
    out = []
    for values in itertools.product(*(GRID[k] for k in keys)):
        cfg = dict(zip(keys, values, strict=True))
        cfg["cluster_chunk_min_ms"] = CHUNKING[cfg["chunk_target_ms"]]
        out.append(cfg)
    return out


def ship_verdict(base: dict[str, Any], cand: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    if base["overcount"] and cand["overcount"] > base["overcount"] * 0.5:
        reasons.append("overcount did not fall by ≥ 50 % relative")
    if not base["overcount"]:
        reasons.append("baseline has no overcount on test; nothing to fix")
    if "der" in base and "der" in cand and cand["der"] - base["der"] > 0.02:
        reasons.append("DER rose by more than 2 points")
    if cand["undercount"] > 0.05:
        reasons.append("undercount above 5 % of files")
    return not reasons, reasons


def main() -> int:
    models = LegacyModels()
    dev = load_entries(MANIFEST, "dev")
    test = load_entries(MANIFEST, "test")
    grid = configs()
    results = []
    for i, cfg in enumerate(grid, 1):
        rows, _ = evaluate(legacy_engine(cfg, models), dev, AUDIO_DIR, log=False)
        agg = aggregate(rows)
        results.append({"config": cfg, **agg})
        print(
            f"[{i}/{len(grid)}] exact {agg.get('count_exact')} der {agg.get('der')}",
            file=sys.stderr,
        )
    results.sort(key=lambda r: (-r.get("count_exact", 0), r.get("der", 1.0)))
    winner = results[0]["config"]

    base_rows, _ = evaluate(legacy_engine({}, models), test, AUDIO_DIR, log=False)
    cand_rows, _ = evaluate(legacy_engine(winner, models), test, AUDIO_DIR, log=False)
    base, cand = aggregate(base_rows), aggregate(cand_rows)
    ship, reasons = ship_verdict(base, cand)
    print(f"winner: {winner}\ntest baseline: {base}\ntest winner:   {cand}")
    print("VERDICT: SHIP" if ship else f"VERDICT: DO NOT SHIP — {'; '.join(reasons)}")
    path = write_report(
        "grid",
        "legacy",
        {
            "winner": winner,
            "test_baseline": base,
            "test_winner": cand,
            "ship": ship,
            "reasons": reasons,
            "dev_results": results,
        },
    )
    print(f"report: {path.relative_to(REPO)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
