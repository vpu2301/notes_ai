#!/usr/bin/env python3
"""Weekly notes-quality CSV (counts only) from scripts/ops/notes_quality.sql as
``funnel_reader``, plus the latest week's headline numbers against the kill thresholds.

    DATABASE_URL=postgresql://funnel_reader:...@host/notes uv run python scripts/jobs/weekly_notes_quality.py [--out DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg

SQL = Path(__file__).resolve().parent.parent / "ops" / "notes_quality.sql"
if not SQL.exists():
    SQL = Path(__file__).resolve().parent / "notes_quality.sql"

# metric → (direction, threshold %, what crossing it means)
THRESHOLDS: dict[str, tuple[str, float | None, str]] = {
    "kept_line_rate": ("min", 50.0, "not trusted if below after four weeks"),
    "regenerate_rate": ("max", 40.0, "not trusted if above after four weeks"),
    "share_without_edit": ("baseline", None, "not send-ready unless above the baseline week"),
}
HEADLINE = (
    "kept_line_rate",
    "dismiss_rate",
    "regenerate_rate",
    "share_without_edit",
    "minutes_to_first_share",
    "corrections_accepted",
    "type_changed",
    "title_changed",
)


def report_path(out_dir: Path, now: datetime) -> Path:
    year, week, _ = now.isocalendar()
    return out_dir / f"notes-quality-{year}-{week:02d}.csv"


def write_csv(
    columns: Sequence[str], rows: Sequence[Mapping[str, Any]], out_dir: Path, now: datetime
) -> Path:
    """The header is written even for an empty week, so it reads as "no
    generations", not as a broken job."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = report_path(out_dir, now)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(columns))
        for row in rows:
            writer.writerow([row[k] for k in columns])
    return target


def headline(rows: Sequence[Mapping[str, Any]], now: datetime) -> list[str]:
    """The last complete week's `all` numbers, each with its threshold.
    Kept lines need 7 days to be read, so that metric's week is one earlier."""
    this_monday = now.date() - timedelta(days=now.weekday())
    last_week = this_monday - timedelta(days=7)
    lines = [f"week of {last_week.isoformat()} (all workspaces):"]
    for metric in HEADLINE:
        week = last_week - timedelta(days=7) if metric == "kept_line_rate" else last_week
        row = next(
            (
                r
                for r in rows
                if r["metric"] == metric and r["dimension"] == "all" and _as_date(r["week"]) == week
            ),
            None,
        )
        if row is None:
            shown = "no data"
        elif metric == "minutes_to_first_share":
            shown = f"median {row['value']} min over {row['numerator']} shares"
        else:
            shown = f"{row['value']} % ({row['numerator']}/{row['denominator']})"
        rule = THRESHOLDS.get(metric)
        verdict = ""
        if rule and row is not None and row["value"] is not None:
            direction, limit, meaning = rule
            value = float(row["value"])
            if direction == "min" and limit is not None:
                verdict = f"  [threshold ≥ {limit:g} %: {'ok' if value >= limit else 'BELOW'} — {meaning}]"
            elif direction == "max" and limit is not None:
                verdict = f"  [threshold ≤ {limit:g} %: {'ok' if value <= limit else 'ABOVE'} — {meaning}]"
            else:
                verdict = f"  [{meaning}]"
        elif rule:
            verdict = f"  [{rule[2]}]"
        lines.append(f"  {metric:24s} {shown}{verdict}")
    lines.append("  evidence_opened_per_line  not reported: no evidence-opened metric exists yet")
    lines.extend(rising_codes(rows, last_week))
    return lines


def rising_codes(rows: Sequence[Mapping[str, Any]], last_week: date) -> list[str]:
    """Error-taxonomy codes whose share of dismissals rose two weeks running
    (docs/eval/error-taxonomy.md: such a code opens a sprint item under its
    owning sprint). Compares the last three complete weeks."""
    weeks = [last_week - timedelta(days=14), last_week - timedelta(days=7), last_week]
    share: dict[str, dict[date, float]] = {}
    for r in rows:
        week = _as_date(r["week"])
        if r["metric"] != "dismiss_code" or week not in weeks or r["value"] is None:
            continue
        share.setdefault(str(r["bucket"]), {})[week] = float(r["value"])
    rising = sorted(
        code
        for code, by_week in share.items()
        if code != "other"
        and all(w in by_week for w in weeks)
        and by_week[weeks[0]] < by_week[weeks[1]] < by_week[weeks[2]]
    )
    if not rising:
        return ["  dismiss codes rising two weeks running: none"]
    return [f"  dismiss codes rising two weeks running: {', '.join(rising)}  [open a sprint item]"]


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


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
    now = datetime.now(UTC)
    target = write_csv(columns, rows, out_dir, now)
    print(f"wrote {target} ({len(rows)} rows)")
    print("\n".join(headline(rows, now)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(
            os.environ.get("MDX_NOTES_REPORT_DIR")
            or os.environ.get("MDX_FUNNEL_REPORT_DIR", "reports")
        ),
    )
    sys.exit(asyncio.run(main(ap.parse_args().out)))
