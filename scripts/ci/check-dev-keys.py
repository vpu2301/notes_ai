#!/usr/bin/env python3
"""CI gate: the dev-only signing key (infra/dev/auth-signing-dev.json) never reaches a
non-dev config, no other private key PEM appears under infra/ or deploy/, and the
Keycloak realm export carries a credential value only for `dev-*` users (W1).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEV_KEY_FILE = ROOT / "infra" / "dev" / "auth-signing-dev.json"
REALM_EXPORT = ROOT / "infra" / "keycloak" / "realm-export.json"

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


def _realm_credential_failures() -> list[str]:
    """A plaintext password in the export is a real secret unless the user is a dev fixture."""
    if not REALM_EXPORT.exists():
        return []
    realm = json.loads(REALM_EXPORT.read_text(encoding="utf-8"))
    return [
        f"infra/keycloak/realm-export.json: user {u.get('username')!r} carries a credential value"
        for u in realm.get("users", [])
        if not str(u.get("username", "")).startswith("dev-")
        and any(c.get("value") for c in u.get("credentials", []))
    ]


def main() -> int:
    failures = _realm_credential_failures()
    kids = _dev_kids()
    if not kids and not failures:
        print("check-dev-keys: no dev signing key present; nothing to guard")
        return 0
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
