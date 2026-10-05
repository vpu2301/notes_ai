#!/usr/bin/env python3
"""Nightly AI-path retention (Sprint 37, B-6).

    DATABASE_URL=postgresql://tenant_writer:...@host/notes \\
        uv run python scripts/jobs/ai_retention.py [--jobs-days 30] [--usage-days 400]

Two tables the application deliberately cannot delete from:

* ``jobs`` — terminal rows are history nobody reads after a month, and
  every one of them is scanned by the queue's own indexes forever.
* ``model_usage`` — the ledger's 400-day retention was written in the
  migration header (0023) and never enforced. A documented retention
  that does not happen is worse than none: it is a promise in a policy.

Both are append-only to ``app_role`` (policy ``USING (false)``), so this
runs as ``tenant_writer``, whose only powers here are SELECT and DELETE
on these two tables (migration 0054). Neither holds note content: ids,
counts, costs and a scrubbed error kind.

Idempotent. Deletes in batches so a year of backlog cannot hold one long
transaction open against a live queue. Prints counts and nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

BATCH = 5_000

SQL_JOBS = """
    DELETE FROM jobs WHERE id IN (
        SELECT id FROM jobs
        WHERE status IN ('complete', 'failed', 'dead', 'cancelled')
          AND coalesce(finished_at, created_at) < now() - make_interval(days => $1)
        LIMIT $2
    )
"""
SQL_USAGE = """
    DELETE FROM model_usage WHERE ctid IN (
        SELECT ctid FROM model_usage
        WHERE created_at < now() - make_interval(days => $1)
        LIMIT $2
    )
"""


def _n(result: str | None) -> int:
    return int(result.split()[-1]) if result else 0


async def _purge(pool: asyncpg.Pool, sql: str, days: int) -> int:
    total = 0
    while True:
        async with pool.acquire() as conn:
            deleted = _n(await conn.execute(sql, days, BATCH))
        total += deleted
        if deleted < BATCH:
            return total


async def main(jobs_days: int, usage_days: int) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        jobs = await _purge(pool, SQL_JOBS, jobs_days)
        usage = await _purge(pool, SQL_USAGE, usage_days)
    finally:
        await pool.close()
    print(f"ai_retention deleted jobs={jobs}")
    print(f"ai_retention deleted model_usage={usage}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--jobs-days", type=int, default=int(os.environ.get("MDX_JOBS_RETENTION_DAYS", "30"))
    )
    ap.add_argument(
        "--usage-days",
        type=int,
        default=int(os.environ.get("MDX_MODEL_USAGE_RETENTION_DAYS", "400")),
    )
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.jobs_days, args.usage_days)))
