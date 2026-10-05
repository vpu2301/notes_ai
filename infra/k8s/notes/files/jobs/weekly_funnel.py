#!/usr/bin/env python3
"""Weekly loop-funnel report (Sprint 22).

    DATABASE_URL=postgresql://funnel_reader:...@host/notes \\
        uv run python scripts/jobs/weekly_funnel.py [--out DIR]

Runs scripts/ops/loop_funnel.sql as the read-only `funnel_reader` role
and writes `funnel-YYYY-WW.csv` (ISO week of the run) to --out (default
`MDX_FUNNEL_REPORT_DIR`, then ./reports). Counts only — the file is the
input to the weekly product cadence and safe to attach to a ticket.
Idempotent: a rerun overwrites the same file.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

SQL = Path(__file__).resolve().parent.parent / "ops" / "loop_funnel.sql"
if not SQL.exists():
    # In the chart the SQL ships next to the job.
    SQL = Path(__file__).resolve().parent / "loop_funnel.sql"


async def main(out_dir: Path) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(SQL.read_text(encoding="utf-8"))
    finally:
        await conn.close()
    out_dir.mkdir(parents=True, exist_ok=True)
    year, week, _ = datetime.now(UTC).isocalendar()
    target = out_dir / f"funnel-{year}-{week:02d}.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if rows:
            writer.writerow(list(rows[0].keys()))
            for row in rows:
                writer.writerow([row[k] for k in row.keys()])  # noqa: SIM118 — Records iterate values
    print(f"wrote {target} ({len(rows)} weeks)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", type=Path, default=Path(os.environ.get("MDX_FUNNEL_REPORT_DIR", "reports"))
    )
    sys.exit(asyncio.run(main(ap.parse_args().out)))
