#!/usr/bin/env python3
"""How often a fallback wrote the note instead of the model path — per language,
recording type and backend, over the last 30 days of ``note_generations.stats``.
Numbers only: no text column is ever selected.

    uv run --project services/note-service --with asyncpg python scripts/eval/fallback_report.py \
        [--env dev|staging] [--dsn postgresql://funnel_reader:…] [--days 30]

Writes ``docs/eval/fallbacks-<date>-<env>.json`` and prints the table (Markdown).
The reader role (``funnel_reader``) sees every tenant's rows and no content.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DOCS_EVAL, git_sha  # noqa: E402

DEFAULT_DSN = "postgresql://funnel_reader:funnel_reader@localhost:5432/notes"

# One pass over the generations; every output is a count. ``lines_unsupported`` is a
# per-reason object, summed per cell.
QUERY = """
SELECT
  coalesce(stats->>'language', '?')                       AS language,
  coalesce(stats->>'recording_type', '?')                 AS recording_type,
  coalesce(backend, '?')                                  AS backend,
  count(*)                                                AS generations,
  count(*) FILTER (WHERE status = 'complete')             AS complete,
  count(*) FILTER (WHERE status = 'partial')              AS partial,
  count(*) FILTER (WHERE status = 'failed')               AS failed,
  count(*) FILTER (WHERE stats->>'summary_ladder' = 'model')    AS summary_model,
  count(*) FILTER (WHERE stats->>'summary_ladder' = 'strict')   AS summary_strict,
  count(*) FILTER (WHERE stats->>'summary_ladder' = 'composed') AS summary_composed,
  count(*) FILTER (WHERE stats->>'summary_ladder' IS NULL)      AS summary_none,
  count(*) FILTER (WHERE coalesce((stats->>'block_chapters')::int, 0) > 0) AS with_chapters,
  coalesce(sum((stats->>'block_chapters')::int), 0)       AS chapter_blocks,
  coalesce(sum((stats->>'blocks_rendered')::int), 0)      AS blocks_rendered,
  count(*) FILTER (WHERE stats->>'topics_fallback' IS NOT NULL) AS topics_fallback,
  count(*) FILTER (WHERE stats->>'summary_fallback' IS NOT NULL) AS summary_fallback,
  coalesce(sum((stats->>'headings_fallback')::int), 0)    AS headings_fallback,
  coalesce(sum((stats->>'facts_kept')::int), 0)           AS facts_kept,
  coalesce(sum((stats->>'speech_ms')::bigint), 0)         AS speech_ms,
  coalesce(sum((stats->'lines_unsupported'->>'unsupported')::int), 0) AS unsupported,
  coalesce(sum((stats->'lines_unsupported'->>'name')::int), 0)        AS unsupported_name,
  coalesce(sum((stats->'lines_unsupported'->>'number')::int), 0)      AS unsupported_number,
  coalesce(sum((stats->'lines_unsupported'->>'copied')::int), 0)      AS unsupported_copied,
  coalesce(sum((stats->'lines_unsupported'->>'first_person')::int), 0) AS unsupported_first_person,
  coalesce(sum((stats->'lines_unsupported'->>'descriptive')::int), 0)  AS unsupported_descriptive,
  coalesce(sum((stats->'lines_unsupported'->>'no_information')::int), 0) AS unsupported_no_information
FROM note_generations
WHERE created_at > now() - make_interval(days => $1)
  AND stats IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY generations DESC, 1, 2, 3
"""

COLUMNS = (
    "language",
    "recording_type",
    "backend",
    "generations",
    "complete",
    "summary_model",
    "summary_strict",
    "summary_composed",
    "summary_none",
    "with_chapters",
    "chapter_blocks",
    "blocks_rendered",
)


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def rows_to_cells(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells = []
    for r in rows:
        cell = {k: (int(v) if isinstance(v, (int, Decimal)) else v) for k, v in r.items()}
        complete = int(r["complete"])
        cell["share_summary_composed"] = _share(int(r["summary_composed"]), complete)
        cell["share_with_chapters"] = _share(int(r["with_chapters"]), complete)
        minutes = int(r["speech_ms"]) / 60_000
        cell["facts_kept_per_minute"] = (
            round(int(r["facts_kept"]) / minutes, 2) if minutes else None
        )
        cells.append(cell)
    return cells


def markdown(cells: list[dict[str, Any]]) -> str:
    head = "| " + " | ".join(COLUMNS) + " | composed % | chapters % |"
    rule = "|" + "---|" * (len(COLUMNS) + 2)
    lines = [head, rule]
    for c in cells:
        pct = lambda v: "–" if v is None else f"{100 * v:.0f}"  # noqa: E731
        lines.append(
            "| "
            + " | ".join(str(c[k]) for k in COLUMNS)
            + f" | {pct(c['share_summary_composed'])} | {pct(c['share_with_chapters'])} |"
        )
    return "\n".join(lines)


async def main(dsn: str, env: str, days: int, out_dir: Path) -> int:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        rows = [dict(r) for r in await conn.fetch(QUERY, days)]
    finally:
        await conn.close()
    cells = rows_to_cells(rows)
    total = sum(int(c["generations"]) for c in cells)
    complete = sum(int(c["complete"]) for c in cells)
    composed = sum(int(c["summary_composed"]) for c in cells)
    chaptered = sum(int(c["with_chapters"]) for c in cells)
    report = {
        "kind": "fallbacks",
        "env": env,
        "days": days,
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_sha(),
        "totals": {
            "generations": total,
            "complete": complete,
            "summary_composed": composed,
            "with_chapters": chaptered,
            "share_summary_composed": _share(composed, complete),
            "share_with_chapters": _share(chaptered, complete),
        },
        "cells": cells,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"fallbacks-{report['date']}-{env}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(markdown(cells))
    print(
        f"\n{env}: {total} generations in {days} days, {complete} complete; "
        f"composed summaries {composed}, notes with chapter blocks {chaptered}"
    )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", default="dev", help="label in the file name: dev, staging, prod")
    ap.add_argument("--dsn", default=DEFAULT_DSN, help="a read-only DSN (funnel_reader)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", type=Path, default=DOCS_EVAL)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.dsn, args.env, args.days, args.out)))
