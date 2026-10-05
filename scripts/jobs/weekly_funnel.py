#!/usr/bin/env python3
"""Weekly loop-funnel CSV (counts only) from scripts/ops/loop_funnel.sql as ``funnel_reader``.

DATABASE_URL=postgresql://funnel_reader:...@host/notes uv run python scripts/jobs/weekly_funnel.py [--out DIR]
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
