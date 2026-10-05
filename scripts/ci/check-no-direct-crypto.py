#!/usr/bin/env python3
"""CI gate: ``cryptography.hazmat`` primitives live only in libs/crypto (plus libs/kep for
X.509/CMS signing, tests for adversarial ciphertext).

Exit 0 clean, 1 violations on stderr.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+cryptography\.hazmat\b",
    re.MULTILINE,
)

ALLOWED_PREFIXES = (
    "libs/crypto/",
    "libs/kep/",  # KEP digital signatures: X.509/CMS/PAdES primitives
    "libs/storage/tests/",  # tampering tests
    "libs/crypto/tests/",  # adversarial tests
    "libs/auth/tests/",  # JWT signing-key fixtures (RS256 test keys)
    # The native issuer's RS256 signer (PKCS#8, JWK, kid from SPKI) is token
    # signing, not data-at-rest crypto; libs/crypto has no API for it.
    "services/auth-service/src/auth_service/domain/signing_keys.py",
    "services/auth-service/tests/unit/test_issuer.py",
    "libs/auth/src/auth/testing.py",  # in-memory issuer for contract tests
    "scripts/ops/gen-signing-key.py",  # generates the key list operators paste
    "scripts/ci/check-no-direct-crypto.py",
)


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    violations: list[tuple[Path, int, str]] = []

    for path in repo.rglob("*.py"):
        rel = path.relative_to(repo).as_posix()
        if any(rel.startswith(p) for p in ALLOWED_PREFIXES):
            continue
        if (
            "/.venv/" in rel
            or "/__pycache__/" in rel
            or "site-packages" in rel
            or rel.startswith(".venv/")
            or rel.startswith("dist/")
        ):
            continue
        try:
            text = path.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in BANNED_IMPORTS.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            violations.append((path, line_no, match.group(0).strip()))

    if violations:
        print("ERROR: direct cryptography.hazmat imports outside libs/crypto:", file=sys.stderr)
        for path, line, snippet in violations:
            print(f"  {path.relative_to(repo)}:{line}  {snippet}", file=sys.stderr)
        print(
            "\nUse libs/crypto.Envelope. Any new primitive belongs in libs/crypto.",
            file=sys.stderr,
        )
        return 1
    print("ok: no direct cryptography.hazmat imports outside libs/crypto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
