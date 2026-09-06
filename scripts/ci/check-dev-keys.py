#!/usr/bin/env python3
"""CI gate (IDX-A2): the dev-only signing key never reaches a non-dev config.

``infra/dev/auth-signing-dev.json`` is a checked-in RSA private key so the
compose stack can run the native issuer without a secret store. Its ``kid``
must not appear anywhere a staging or production deployment reads from:
Helm values, deploy/ specs, workflows, env examples. The dev compose file
and this script are the only places allowed to name it outside infra/dev.

Also fails if any *other* private key PEM shows up under infra/ or deploy/
outside infra/dev — a second "temporary" key is how dev keys go to prod.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEV_KEY_FILE = ROOT / "infra" / "dev" / "auth-signing-dev.json"

# Files that may legitimately mention the dev kid.
ALLOWED = {
    "infra/dev/auth-signing-dev.json",
    "infra/dev/README.md",
    "docker-compose.override.yml",
    "scripts/ci/check-dev-keys.py",
}
SCAN_DIRS = ("infra", "deploy", "config", ".github", "scripts/k8s")
SCAN_FILES = (".env.example",)
TEXT_SUFFIXES = {
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".md",
    ".sh",
    ".py",
    ".env",
    ".example",
    ".txt",
    "",
}
PEM_RE = re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")


def _dev_kids() -> set[str]:
    if not DEV_KEY_FILE.exists():
        return set()
    entries = json.loads(DEV_KEY_FILE.read_text(encoding="utf-8"))
    return {e["kid"] for e in entries if isinstance(e, dict) and "kid" in e}


def _candidates() -> list[Path]:
    out: list[Path] = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if base.exists():
            out.extend(p for p in base.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES)
    out.extend(ROOT / f for f in SCAN_FILES if (ROOT / f).exists())
    return out


def main() -> int:
    kids = _dev_kids()
    if not kids:
        print("check-dev-keys: no dev signing key present; nothing to guard")
        return 0
    failures: list[str] = []
    for path in _candidates():
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if rel in ALLOWED:
            continue
        for kid in kids:
            if kid in text:
                failures.append(f"{rel}: mentions dev signing kid {kid}")
        if not rel.startswith("infra/dev/") and PEM_RE.search(text):
            failures.append(f"{rel}: contains a private key PEM")
    if failures:
        print("check-dev-keys: FAIL")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"check-dev-keys: OK (dev kids {sorted(kids)} confined to dev configs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
