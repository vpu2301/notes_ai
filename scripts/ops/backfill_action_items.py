#!/usr/bin/env python3
"""Materialise action items for notes that predate migration 0037.

    DB_APP_ROLE_DSN=postgresql://... uv run python scripts/ops/backfill_action_items.py [--tenant <uuid>]

Optional: since 0042 items are derived lazily the first time a version is
read, so this only warms the projection ahead of the first read.
Idempotent: the (version, item_key) unique constraint makes a rerun a
no-op. Walks every tenant (or one), every live note's current version,
on a tenant-scoped connection so RLS applies exactly as it does on read.
The anchor for relative dates is TODAY in the tenant's zone — the parser
only needs it for "Friday"-style text.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from uuid import UUID

import asyncpg

from db import tenant_connection
from note_service.domain import action_items
from note_service.domain import notes_repository as repo


async def _tenants(pool: asyncpg.Pool, only: UUID | None) -> list[UUID]:
    if only:
        return [only]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM tenants WHERE status = 'active' ORDER BY created_at"
        )
    return [r["id"] for r in rows]


async def main(only: UUID | None) -> int:
    dsn = os.environ.get("DB_APP_ROLE_DSN")
    if not dsn:
        print("DB_APP_ROLE_DSN is not set", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        total = 0
        for tenant_id in await _tenants(pool, only):
            async with tenant_connection(pool, tenant_id) as conn:
                anchor = await action_items.anchor_date(conn, tenant_id=tenant_id)
                note_ids = [
                    r["id"]
                    for r in await conn.fetch(
                        "SELECT id FROM notes WHERE status = 'draft' AND deleted_at IS NULL"
                    )
                ]
                inserted = 0
                for note_id in note_ids:
                    note = await repo.fetch_note(conn, note_id=note_id)
                    if note is None:
                        continue
                    version = await repo.fetch_version(conn, version_id=note.current_version_id)
                    if version is None:
                        continue
                    inserted += await action_items.materialise_items(
                        conn, note=note, version=version, anchor=anchor
                    )
                print(f"tenant {tenant_id}: {len(note_ids)} notes, {inserted} items inserted")
                total += inserted
        print(f"done: {total} items inserted")
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", type=UUID, default=None)
    sys.exit(asyncio.run(main(ap.parse_args().tenant)))
