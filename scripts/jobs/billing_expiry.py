#!/usr/bin/env python3
"""Nightly: end redeem-code plans whose time has run out (0069), per tenant on a
tenant-scoped connection. Idempotent; prints a count.

    DATABASE_URL=postgresql://app_role:...@host/notes uv run python scripts/jobs/billing_expiry.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

from db import tenant_connection
from note_service.domain import billing

SQL_TENANTS = "SELECT id FROM tenants WHERE status = 'active'"


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    ended = 0
    try:
        async with pool.acquire() as conn:
            tenant_ids = [r["id"] for r in await conn.fetch(SQL_TENANTS)]
        for tenant_id in tenant_ids:
            async with tenant_connection(pool, tenant_id) as conn:
                ended += await billing.expire_if_due(conn, tenant_id=tenant_id)
    finally:
        await pool.close()
    print(f"billing_expiry ended={ended}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
