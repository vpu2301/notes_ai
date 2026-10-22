#!/usr/bin/env python3
"""Nightly telemetry retention: delete runs past ``retention_until`` (spans, LLM calls, client
events and run context cascade) and close runs stuck ``queued``/``running`` with no activity
for 6 hours. Telemetry only; per tenant on a tenant-scoped connection; prints counts only.

    DATABASE_URL=postgresql://app_role:...@host/notes uv run python scripts/jobs/telemetry_retention.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

from telemetry.retention import purge


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        result = await purge(pool)
    finally:
        await pool.close()
    print(
        f"telemetry_retention: tenants={result.tenants} deleted_runs={result.deleted_runs}"
        f" closed_stale_runs={result.closed_stale_runs}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
