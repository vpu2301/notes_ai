#!/usr/bin/env python3
"""Forward/rollback SQL migration runner over ``infra/postgres/migrations/NNNN_*.sql``
(with ``NNNN_*.down.sql`` siblings). Takes an EXCLUSIVE lock on ``schema_migrations``
per transaction; a divergent sha256 on an applied file aborts before any change.

    python scripts/db/migrate.py up | down | status   (DATABASE_URL overrides the dev default)

Files named in ``infra/postgres/migrations/DEV_ONLY`` (the demo tenants) are recorded as
``skipped`` instead of run when ``--skip-dev-seeds`` is given or ``MDX_ENV=prod``, so the
version numbering stays dense and a prod database never holds dev fixtures.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

import asyncpg

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "infra" / "postgres" / "migrations"
DEV_ONLY_FILE = "DEV_ONLY"

_VERSION_RE = re.compile(r"^(\d{4})_([\w-]+)\.sql$")

_TXN_BEGIN_RE = re.compile(r"^\s*(?:BEGIN|START\s+TRANSACTION)\s*;\s*$", re.IGNORECASE)
_TXN_COMMIT_RE = re.compile(r"^\s*COMMIT\s*;\s*$", re.IGNORECASE)


def _strip_outer_transaction(sql: str) -> str:
    """Drop a file's own outer ``BEGIN;`` / ``COMMIT;``: the runner's transaction also carries
    the ``schema_migrations`` row, and a self-committing file would split the two.
    Only the first and last statement lines are considered (dollar-quoted bodies untouched).
    """
    lines = sql.splitlines()

    def _is_noise(line: str) -> bool:
        stripped = line.strip()
        return not stripped or stripped.startswith("--")

    head = next((i for i, ln in enumerate(lines) if not _is_noise(ln)), None)
    if head is None or not _TXN_BEGIN_RE.match(lines[head]):
        return sql
    tail = next(i for i in range(len(lines) - 1, -1, -1) if not _is_noise(lines[i]))
    if tail <= head or not _TXN_COMMIT_RE.match(lines[tail]):
        return sql
    return "\n".join(lines[:head] + lines[head + 1 : tail] + lines[tail + 1 :])


class Migration(NamedTuple):
    version: str
    name: str
    up_path: Path
    down_path: Path


def _discover() -> list[Migration]:
    """Return all migrations sorted by version."""
    out: list[Migration] = []
    for entry in sorted(MIGRATIONS_DIR.iterdir()):
        if entry.name.endswith(".down.sql"):
            continue
        m = _VERSION_RE.match(entry.name)
        if not m:
            continue
        version, name = m.group(1), m.group(2)
        down = entry.with_name(f"{version}_{name}.down.sql")
        if not down.exists():
            raise RuntimeError(f"missing rollback for {entry.name}: expected {down.name}")
        out.append(Migration(version=version, name=name, up_path=entry, down_path=down))
    return out


def _dev_only_names(migrations_dir: Path) -> frozenset[str]:
    """File names listed in ``DEV_ONLY`` — one per line, ``#`` comments allowed."""
    path = migrations_dir / DEV_ONLY_FILE
    if not path.exists():
        return frozenset()
    lines = (ln.split("#", 1)[0].strip() for ln in path.read_text().splitlines())
    return frozenset(ln for ln in lines if ln)


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _ensure_tracking_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            checksum   TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute(
        "ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS skipped BOOLEAN NOT NULL DEFAULT false"
    )


async def _applied_versions(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {r["version"]: r["checksum"] for r in rows}


async def _apply_one(conn: asyncpg.Connection, m: Migration, *, skip: bool = False) -> None:
    sql = _strip_outer_transaction(m.up_path.read_text())
    csum = _checksum(m.up_path)  # over the raw file — stripping must not shift checksums
    async with conn.transaction():
        await conn.execute("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
        existing = await conn.fetchrow(
            "SELECT checksum FROM schema_migrations WHERE version = $1", m.version
        )
        if existing is not None:
            if existing["checksum"] != csum:
                raise RuntimeError(
                    f"checksum drift on {m.version}: applied={existing['checksum'][:8]}…, "
                    f"file={csum[:8]}…"
                )
            print(f"  = {m.version}_{m.name} (already applied)")
            return
        if not skip:
            await conn.execute(sql)
        await conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum, skipped) VALUES ($1, $2, $3, $4)",
            m.version,
            m.name,
            csum,
            skip,
        )
    print(f"  {'~' if skip else '+'} {m.version}_{m.name}{' (dev-only, skipped)' if skip else ''}")


async def _rollback_one(conn: asyncpg.Connection, m: Migration) -> None:
    sql = _strip_outer_transaction(m.down_path.read_text())
    async with conn.transaction():
        await conn.execute("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
        existing = await conn.fetchrow(
            "SELECT version, skipped FROM schema_migrations WHERE version = $1", m.version
        )
        if existing is None:
            print(f"  - {m.version}_{m.name} (not applied; nothing to do)")
            return
        if not existing["skipped"]:
            await conn.execute(sql)
        await conn.execute("DELETE FROM schema_migrations WHERE version = $1", m.version)
    print(f"  - {m.version}_{m.name}")


async def cmd_up(conn: asyncpg.Connection, *, skip_dev_seeds: bool = False) -> int:
    await _ensure_tracking_table(conn)
    migrations = _discover()
    dev_only = _dev_only_names(MIGRATIONS_DIR) if skip_dev_seeds else frozenset()
    applied = await _applied_versions(conn)
    pending = [m for m in migrations if m.version not in applied]
    if not pending:
        print("No pending migrations.")
        return 0
    print(f"Applying {len(pending)} migration(s):")
    for m in pending:
        await _apply_one(conn, m, skip=m.up_path.name in dev_only)
    return 0


async def cmd_down(conn: asyncpg.Connection) -> int:
    """Rollback the single most-recently-applied migration."""
    await _ensure_tracking_table(conn)
    row = await conn.fetchrow("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1")
    if row is None:
        print("Nothing to roll back.")
        return 0
    target_version = row["version"]
    migration = next(
        (m for m in _discover() if m.version == target_version),
        None,
    )
    if migration is None:
        print(
            f"ERROR: version {target_version} is recorded as applied but the migration "
            "file is missing from infra/postgres/migrations/",
            file=sys.stderr,
        )
        return 2
    await _rollback_one(conn, migration)
    return 0


async def cmd_status(conn: asyncpg.Connection) -> int:
    await _ensure_tracking_table(conn)
    migrations = _discover()
    applied = await _applied_versions(conn)
    skipped = {
        r["version"]
        for r in await conn.fetch("SELECT version FROM schema_migrations WHERE skipped")
    }
    print(f"{'STATUS':<8} {'VERSION':<6} NAME")
    for m in migrations:
        status = (
            "skipped" if m.version in skipped else "applied" if m.version in applied else "pending"
        )
        print(f"{status:<8} {m.version:<6} {m.name}")
    for version, csum in applied.items():
        match = next((x for x in migrations if x.version == version), None)
        if match is not None and _checksum(match.up_path) != csum:
            print(
                f"WARNING: checksum drift on {version} — file edited after apply.",
                file=sys.stderr,
            )
    return 0


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("up", "down", "status"))
    p.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL", DEFAULT_DSN),
        help="Postgres DSN (default: env DATABASE_URL or %(default)s)",
    )
    p.add_argument(
        "--skip-dev-seeds",
        action="store_true",
        default=os.environ.get("MDX_ENV") == "prod",
        help="record DEV_ONLY files as skipped instead of running them (default: on when MDX_ENV=prod)",
    )
    args = p.parse_args()

    conn = await asyncpg.connect(args.dsn)
    try:
        if args.command == "up":
            return await cmd_up(conn, skip_dev_seeds=args.skip_dev_seeds)
        if args.command == "down":
            return await cmd_down(conn)
        if args.command == "status":
            return await cmd_status(conn)
        return 2  # unreachable
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
