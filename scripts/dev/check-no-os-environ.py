#!/usr/bin/env python3
"""Gate: no ``os.environ`` reads outside a service's ``config.py`` (pydantic-settings is
the trust boundary). Skips config.py, tests/, libs/secret/, scripts/; override with ``# noqa: ENV001``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r"\bos\.environ\b|\bos\.getenv\b")


def is_excluded(path: Path) -> bool:
    """True if ``path`` is a sanctioned env surface (config.py, tests/, libs/secret/, scripts/);
    works on absolute paths too.
    """
    parts = path.parts
    if path.name == "config.py":
        return True
    if "tests" in parts:
        return True
    posix = path.as_posix()
    if posix.startswith("libs/secret/") or "/libs/secret/" in posix:
        return True
    return "scripts" in parts


def main(paths: list[str]) -> int:
    failed = False
    for raw in paths:
        p = Path(raw)
        if not p.is_file() or p.suffix != ".py":
            continue
        if is_excluded(p):
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "noqa: ENV001" in line:
                continue
            if PATTERN.search(line):
                print(
                    f"{p}:{lineno}: ENV001 os.environ / os.getenv outside config.py — "
                    f"use pydantic-settings",
                    file=sys.stderr,
                )
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
