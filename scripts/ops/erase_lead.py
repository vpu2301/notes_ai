#!/usr/bin/env python3
"""Erase every referral lead for an e-mail address (DSAR). ``referrals`` is global, owned
by ``tenant_writer``; a recipient address on a share link is dropped by revoking the link.

    DB_TENANT_WRITER_DSN=postgresql://... uv run python scripts/ops/erase_lead.py tom@client.com
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg


async def main(email: str) -> int:
    dsn = os.environ.get("DB_TENANT_WRITER_DSN")
    if not dsn:
        print("DB_TENANT_WRITER_DSN is not set", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        result = await conn.execute(
            "DELETE FROM referrals WHERE lower(lead_email) = lower($1)", email.strip()
        )
    finally:
        await conn.close()
    print(f"referrals: {result}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
