#!/usr/bin/env python3
"""Make, list and retire redeem codes (0069).

    DATABASE_URL=postgresql://postgres:...@host/notes \\
        uv run python scripts/admin/redeem_code.py create --plan pro --days 90 [--max 1]
            [--expires 2026-12-31] [--note "Webinar October"]
    ... redeem_code.py list
    ... redeem_code.py retire <code>

``create`` prints the code ONCE — only its SHA-256 is stored, so a lost
code cannot be shown again; make a new one. ``--days`` omitted = the plan
stays until someone changes it. ``--max`` omitted = any number of
workspaces. ``retire`` sets the code's expiry to now.

app_role has no grant on the code tables (the API reaches them only
through ``redeem_code()``), so this runs as the database owner, as the
migrations do.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import secrets
import sys
from datetime import UTC, datetime

import asyncpg

# No 0/O, 1/I/L: a code is read off a slide or a printed card.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
GROUPS, GROUP = 4, 4  # 16 characters ≈ 79 bits


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP))
    return "-".join(raw[i : i + GROUP] for i in range(0, len(raw), GROUP))


def code_hash(code: str) -> bytes:
    # Same normalisation as note_service.domain.billing.normalise_code.
    return hashlib.sha256(re.sub(r"[\s\-_]+", "", code).upper().encode()).digest()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--plan", required=True, choices=["free", "pro", "enterprise"])
    c.add_argument("--days", type=int)
    c.add_argument("--max", type=int, dest="max_redemptions")
    c.add_argument("--expires", help="last day the code can be redeemed (YYYY-MM-DD)")
    c.add_argument("--note", default="")
    sub.add_parser("list")
    r = sub.add_parser("retire")
    r.add_argument("code")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        if args.cmd == "create":
            code = new_code()
            expires = (
                datetime.fromisoformat(args.expires).replace(hour=23, minute=59, tzinfo=UTC)
                if args.expires
                else None
            )
            await conn.execute(
                "INSERT INTO redeem_codes (code_hash, plan, duration_days, max_redemptions, "
                "expires_at, note) VALUES ($1, $2, $3, $4, $5, $6)",
                code_hash(code),
                args.plan,
                args.days,
                args.max_redemptions,
                expires,
                args.note or None,
            )
            print(code)
        elif args.cmd == "list":
            rows = await conn.fetch(
                "SELECT plan, duration_days, max_redemptions, redeemed_count, expires_at, "
                "note, created_at FROM redeem_codes ORDER BY created_at DESC"
            )
            for row in rows:
                until = f"{row['expires_at']:%Y-%m-%d}" if row["expires_at"] else "—"
                print(
                    f"{row['created_at']:%Y-%m-%d}  {row['plan']:<10}  "
                    f"days={row['duration_days'] or '∞'}  "
                    f"used={row['redeemed_count']}/{row['max_redemptions'] or '∞'}  "
                    f"until={until}  {row['note'] or ''}"
                )
        else:
            done = await conn.execute(
                "UPDATE redeem_codes SET expires_at = now() WHERE code_hash = $1",
                code_hash(args.code),
            )
            print("retired" if done.endswith("1") else "no such code")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
