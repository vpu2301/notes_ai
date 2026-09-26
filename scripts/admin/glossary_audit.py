#!/usr/bin/env python3
"""Which glossary terms are role labels, per workspace (Sprint I2 T1).

    DATABASE_URL=postgresql://funnel_reader:...@host/notes \\
        uv run python scripts/admin/glossary_audit.py [--show-terms]

The vocabulary rule (``note_service.domain.glossary.is_vocabulary``) now
keeps a stored role label — "Moderator II", "speaker background" — out of
the transcriber's hint without a data migration. This lists, per
workspace, how many live terms fail the rule so support can ask the
workspace to remove them (the glossary page shows the same banner).

Counts by default. ``--show-terms`` prints the failing term text as well —
to the terminal only, never to a file — for the one workspace whose
incident is being handled. Workspace ids are shortened.

The reader role has no grant on ``workspace_glossary``; this reads through
``app_role`` as the migrations job does, under a tenant-less connection
with row security off, which the funnel_reader role cannot do. Run it as
an operator on the database host.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "note-service" / "src"))

from note_service.domain.glossary import is_vocabulary  # noqa: E402


async def main(show_terms: bool) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT tenant_id, term, kind FROM workspace_glossary"
            " WHERE deleted_at IS NULL ORDER BY tenant_id, created_at"
        )
    finally:
        await conn.close()
    per_tenant: dict[str, list[tuple[str, str]]] = {}
    totals: dict[str, int] = {}
    for row in rows:
        tid = str(row["tenant_id"])
        totals[tid] = totals.get(tid, 0) + 1
        if not is_vocabulary(str(row["term"]), str(row["kind"])):
            per_tenant.setdefault(tid, []).append((str(row["term"]), str(row["kind"])))
    print(f"workspaces with a glossary: {len(totals)}; with role labels: {len(per_tenant)}")
    for tid, failing in sorted(per_tenant.items(), key=lambda kv: -len(kv[1])):
        print(f"  {tid[:8]}…  {len(failing)} of {totals[tid]} terms are role labels")
        if show_terms:
            for term, kind in failing:
                print(f"      - {term!r} ({kind})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--show-terms", action="store_true", help="print the failing terms (terminal only)"
    )
    sys.exit(asyncio.run(main(ap.parse_args().show_terms)))
