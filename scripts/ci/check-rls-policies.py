#!/usr/bin/env python3
"""CI gate against a live database: every ``public``/``audit`` table has RLS enabled AND
forced (explicit exemptions below); a table with no policy is warned about.

    DATABASE_URL=postgres://... uv run python scripts/ci/check-rls-policies.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Final

import asyncpg

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/notes"

# Exemptions: tables with no tenant dimension, and ADR-documented perf
# exceptions that carry tenant_id and rely on app-level filtering (accepted
# risks pending security sign-off).
EXEMPT: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("public", "schema_migrations"),  # migration tracker
        # ── global, no tenant_id ───────────────────────────────────────
        (
            "public",
            "voice_commands",
        ),  # global voice-command catalogue (no per-tenant rows yet)
        # ── ADR-0025 perf exception (has tenant_id; app-level filtering) ─
        # FLAGGED for security sign-off.
        ("public", "autocomplete_rollup_progress"),
    }
)

# Name-prefix exemptions: range-partition children with a date suffix.
EXEMPT_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("public", "autocomplete_telemetry"),  # ADR-0025 perf exception (FLAGGED — see report)
)

# Schemas where we enforce.
ENFORCED_SCHEMAS: Final[tuple[str, ...]] = ("public", "audit")


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT n.nspname AS schema,
                   c.relname AS name,
                   c.relrowsecurity,
                   c.relforcerowsecurity,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policy_count
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relkind = 'r'  -- ordinary tables only
              AND n.nspname = ANY($1::text[])
            ORDER BY n.nspname, c.relname
            """,
            list(ENFORCED_SCHEMAS),
        )
    finally:
        await conn.close()

    failures: list[str] = []
    warnings: list[str] = []
    checked = 0

    for r in rows:
        key = (r["schema"], r["name"])
        if key in EXEMPT:
            continue
        if any(r["schema"] == sch and r["name"].startswith(pfx) for sch, pfx in EXEMPT_PREFIXES):
            continue
        checked += 1
        full = f"{r['schema']}.{r['name']}"
        if not r["relrowsecurity"]:
            failures.append(
                f"{full}: RLS NOT enabled (ALTER TABLE {full} ENABLE ROW LEVEL SECURITY)"
            )
            continue
        if not r["relforcerowsecurity"]:
            failures.append(
                f"{full}: RLS enabled but NOT forced "
                f"(ALTER TABLE {full} FORCE ROW LEVEL SECURITY) — "
                "without FORCE, superuser/owner queries bypass policies"
            )
            continue
        if r["policy_count"] == 0:
            warnings.append(
                f"{full}: RLS+FORCE active but no policies → all rows hidden from everyone"
            )

    if failures:
        print("FAIL:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"PASS: {checked} table(s) in {list(ENFORCED_SCHEMAS)} all have RLS+FORCE")
    if warnings:
        print("WARNINGS (may be intentional):")
        for w in warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
