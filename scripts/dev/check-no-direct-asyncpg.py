#!/usr/bin/env python3
"""Gate: no direct ``asyncpg.connect`` / ``create_pool`` outside ``libs/db/`` (the RLS
contract, ADR-0004). Skips libs/db/, tests/ and scripts/; override with ``# noqa: DB001``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r"\basyncpg\.(connect|create_pool)\b")


def is_excluded(path: Path) -> bool:
    """True if ``path`` is a sanctioned raw-driver surface and must not be
    scanned: ``libs/db/`` (the only app-code home), or any ``tests/`` /
    ``scripts/`` tree (integration tests + operational tooling). Works on
    absolute paths too (for the unit tests)."""
    parts = path.parts
    if "tests" in parts or "scripts" in parts:
        return True
    posix = path.as_posix()
    return posix.startswith("libs/db/") or "/libs/db/" in posix


def main(paths: list[str]) -> int:
    failed = False
    for raw in paths:
        p = Path(raw)
        if not p.is_file() or p.suffix != ".py":
            continue
        if is_excluded(p):
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "noqa: DB001" in line:
                continue
            if PATTERN.search(line):
                print(
                    f"{p}:{lineno}: DB001 direct asyncpg use outside libs/db/ — "
                    f"use libs/db.tenant_connection()",
                    file=sys.stderr,
                )
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
