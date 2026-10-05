#!/usr/bin/env python3
"""Purge identities whose 30-day deletion grace has run out: crypto-shred credentials,
rewrite the address to ``deleted:<id>``, drop sessions/challenges, mark memberships
deleted. Notes (author renders as "Deleted user") and the hash-chained audit trail survive.
One transaction per identity; re-running is a no-op.

    uv run python scripts/ops/idx-purge-deleted-identities.py --dry-run | --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "auth-service", "src"),
)

from auth_service.maintenance.purge_impl import (  # noqa: E402
    GRACE_DAYS,
    PLATFORM_TENANT,
    due_identities,
    purge_one,
)

DEFAULT_DSN = "postgresql://tenant_writer:tenant_writer@localhost:5432/notes"


async def run(*, dsn: str, apply: bool, grace_days: int) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        due = await due_identities(conn, grace_days=grace_days)
        if not due:
            print("nothing due")
            return 0
        print(f"{len(due)} identity(ies) past the {grace_days}-day grace period:")
        for row in due:
            print(f"  {row['id']}  requested {row['deletion_requested_at'].isoformat()}")
        if not apply:
            print("\n--dry-run: nothing was changed. Re-run with --apply.")
            return 0
        for row in due:
            await purge_one(conn, row["id"])
            print(f"purged {row['id']}")
        print(
            f"\n{len(due)} purged. Write one auth.account_purged audit event per identity "
            f"to tenant {PLATFORM_TENANT} from the service (libs/audit owns that table)."
        )
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DB_TENANT_WRITER_DSN", DEFAULT_DSN),
        help="tenant_writer DSN (identity tables are writer-only)",
    )
    parser.add_argument("--grace-days", type=int, default=GRACE_DAYS)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="list what would be purged")
    group.add_argument("--apply", action="store_true", help="actually purge")
    args = parser.parse_args()
    return asyncio.run(run(dsn=args.dsn, apply=bool(args.apply), grace_days=args.grace_days))


if __name__ == "__main__":
    sys.exit(main())
