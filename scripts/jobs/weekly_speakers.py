#!/usr/bin/env python3
"""Weekly speaker-quality report (Sprint 30).

    DATABASE_URL=postgresql://funnel_reader:...@host/notes \\
        uv run python scripts/jobs/weekly_speakers.py [--out DIR]

Runs scripts/ops/speaker_quality.sql as the read-only `funnel_reader` role
(column-level grant, migration 0046) and writes `speakers-YYYY-WW.csv`
(ISO week of the run) to --out (default `MDX_SPEAKER_REPORT_DIR`, then
`MDX_FUNNEL_REPORT_DIR`, then ./reports). Counts only — one row per
(week of completion, dimension, bucket); definitions in
docs/product/speaker-metrics.md. Idempotent: a rerun overwrites the same file.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

SQL = Path(__file__).resolve().parent.parent / "ops" / "speaker_quality.sql"
if not SQL.exists():
    # In the chart the SQL ships next to the job.
    SQL = Path(__file__).resolve().parent / "speaker_quality.sql"


def report_path(out_dir: Path, now: datetime) -> Path:
    year, week, _ = now.isocalendar()
    return out_dir / f"speakers-{year}-{week:02d}.csv"


def write_csv(
    columns: Sequence[str], rows: Sequence[Mapping[str, Any]], out_dir: Path, now: datetime
) -> Path:
    """The header is written even for an empty cohort, so an empty week
    reads as "no evaluable jobs", not as a broken job."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = report_path(out_dir, now)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(columns))
        for row in rows:
            writer.writerow([row[k] for k in columns])
    return target


async def main(out_dir: Path) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        stmt = await conn.prepare(SQL.read_text(encoding="utf-8"))
        columns = [a.name for a in stmt.get_attributes()]
        rows = await stmt.fetch()
    finally:
        await conn.close()
    target = write_csv(columns, rows, out_dir, datetime.now(UTC))
    print(f"wrote {target} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(
            os.environ.get("MDX_SPEAKER_REPORT_DIR")
            or os.environ.get("MDX_FUNNEL_REPORT_DIR", "reports")
        ),
    )
    sys.exit(asyncio.run(main(ap.parse_args().out)))
