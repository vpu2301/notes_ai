#!/usr/bin/env python3
"""Nightly share retention (Sprint 23).

    DATABASE_URL=postgresql://app_role:...@host/notes \\
        uv run python scripts/jobs/share_retention.py [--days 30]

For every link expired longer than `--days` (default
`MDX_SHARE_RETENTION_DAYS`, 30): responses are cleared, the recipient
address dropped, any verification code deleted. Runs per tenant on a
tenant-scoped connection so RLS applies exactly as it does online.
Idempotent; prints counts per kind and emits nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

from db import tenant_connection

SQL_TENANTS = "SELECT id FROM tenants WHERE status = 'active'"
SQL_RESPONSES = """
    UPDATE share_link_responses r SET cleared_at = now()
    FROM note_share_links l
    WHERE l.id = r.link_id AND r.cleared_at IS NULL
      AND l.expires_at < now() - ($1 || ' days')::interval
"""
SQL_EMAILS = """
    UPDATE note_share_links SET recipient_email = NULL
    WHERE recipient_email IS NOT NULL AND expires_at < now() - ($1 || ' days')::interval
"""
SQL_OTPS = """
    DELETE FROM share_link_otps o USING note_share_links l
    WHERE l.id = o.link_id AND l.expires_at < now() - ($1 || ' days')::interval
"""


def _n(result: str | None) -> int:
    return int(result.split()[-1]) if result else 0


async def main(days: int) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    totals = {"responses": 0, "emails": 0, "otps": 0}
    try:
        async with pool.acquire() as conn:
            tenant_ids = [r["id"] for r in await conn.fetch(SQL_TENANTS)]
        for tenant_id in tenant_ids:
            async with tenant_connection(pool, tenant_id) as conn:
                totals["responses"] += _n(await conn.execute(SQL_RESPONSES, str(days)))
                totals["emails"] += _n(await conn.execute(SQL_EMAILS, str(days)))
                totals["otps"] += _n(await conn.execute(SQL_OTPS, str(days)))
    finally:
        await pool.close()
    for kind, n in totals.items():
        print(f"share_retention cleared {kind}={n}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--days", type=int, default=int(os.environ.get("MDX_SHARE_RETENTION_DAYS", "30"))
    )
    sys.exit(asyncio.run(main(ap.parse_args().days)))
