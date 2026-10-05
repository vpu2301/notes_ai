#!/usr/bin/env python3
"""CI gate: demo/dev escape hatches (``MD_OBJECT_STORE_DISABLED``, ``MDX_DEMO_MODE``,
``DEMO_*``, ``AUTH_BYPASS_DEV``) are never set truthy in a production-looking config.

Exit 0 clean, 1 violations on stderr.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FLAGS = [
    "MD_OBJECT_STORE_DISABLED",
    "MDX_DEMO_MODE",
    "AUTH_BYPASS_DEV",
    r"DEMO_[A-Z0-9_]+",
]
TRUTHY = re.compile(
    r"(?P<flag>" + "|".join(FLAGS) + r")\s*[:=]\s*['\"]?(true|1|yes|on)['\"]?",
    re.IGNORECASE,
)
# `MDX_DEV_*` switches are dev-only by contract: any non-empty literal in a
# production-looking config is a violation (`${VAR:-}` pass-throughs are not literals).
DEV_ONLY = re.compile(r"(?P<flag>MDX_DEV_[A-Z0-9_]+)\s*[:=]\s*['\"]?(?!\$\{)[A-Za-z0-9_.:/-]+")
PROD_ENV = re.compile(r"ENVIRONMENT\s*[:=]\s*['\"]?(production|prod|staging)['\"]?", re.IGNORECASE)
PRODISH_PATH = re.compile(r"(prod|production|staging|release)", re.IGNORECASE)

SCAN_SUFFIXES = {".yml", ".yaml", ".env", ".toml", ".json", ".conf", ".sh", ""}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache"}
SKIP_PREFIXES = ("docs/",)
SKIP_PARTS = {"tests", "test"}
SELF = "scripts/ci/check-no-demo-envvars-in-prod.py"


def scan() -> list[str]:
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        parts = set(rel.parts)
        if parts & SKIP_DIRS or parts & SKIP_PARTS:
            continue
        rel_str = str(rel)
        if rel_str.startswith(SKIP_PREFIXES) or rel_str == SELF:
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES and ".env" not in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = TRUTHY.search(text) or DEV_ONLY.search(text)
        if not m:
            continue
        flag = m.group("flag")
        if PRODISH_PATH.search(rel_str):
            violations.append(f"{rel_str}: enables {flag} in a production-looking config file")
        elif PROD_ENV.search(text):
            violations.append(
                f"{rel_str}: enables {flag} alongside a production/staging ENVIRONMENT"
            )
    return violations


def main() -> int:
    violations = scan()
    if violations:
        print(
            "check-no-demo-envvars-in-prod: demo/dev escape hatches "
            "(MD_OBJECT_STORE_DISABLED, MDX_DEMO_MODE, DEMO_*, AUTH_BYPASS_DEV, MDX_DEV_*) "
            "must NEVER be enabled in production configs:",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print("check-no-demo-envvars-in-prod: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
