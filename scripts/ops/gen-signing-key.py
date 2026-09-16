#!/usr/bin/env python3
"""Generate one RS256 signing key for the native issuer (IDX-A2, F1).

Prints a JSON object to append to the AUTH_SIGNING_KEYS_JSON list:

    {"kid": "<sha256(spki)[:12]>", "private_pem": "...", "not_after": "..."}

Usage:
    python scripts/ops/gen-signing-key.py                 # 3072-bit, valid 180 days
    python scripts/ops/gen-signing-key.py --days 365
    python scripts/ops/gen-signing-key.py --not-after 2027-03-01T00:00:00Z
    python scripts/ops/gen-signing-key.py --list          # wrap in a one-element list

Rotation: generate the next key, append it to the list with a LATER
not_after (it becomes active immediately — the active key is the one whose
not_after is furthest ahead), keep the old entry until not_after + access
TTL has passed, then drop it. Never print or paste the output anywhere but
the secret store; the dev-only key lives at infra/dev/auth-signing-dev.json
and CI refuses its kid outside dev configs (scripts/ci/check-dev-keys.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_BITS = 3072


def kid_for(public_key: rsa.RSAPublicKey) -> str:
    spki = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()[:12]


def generate(not_after: datetime, *, bits: int = KEY_BITS) -> dict[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return {
        "kid": kid_for(private.public_key()),
        "private_pem": pem,
        "not_after": not_after.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=180, help="validity from now (default 180)")
    parser.add_argument("--not-after", help="explicit ISO-8601 instant (overrides --days)")
    parser.add_argument("--bits", type=int, default=KEY_BITS)
    parser.add_argument("--list", action="store_true", help="emit a one-element JSON list")
    args = parser.parse_args(argv)

    if args.not_after:
        not_after = datetime.fromisoformat(args.not_after.replace("Z", "+00:00"))
        if not_after.tzinfo is None:
            parser.error("--not-after needs a timezone (e.g. ...Z)")
    else:
        not_after = datetime.now(UTC) + timedelta(days=args.days)
    if args.bits < 2048:
        parser.error("--bits must be >= 2048")

    entry = generate(not_after, bits=args.bits)
    out = [entry] if args.list else entry
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    print(f"kid={entry['kid']} not_after={entry['not_after']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
