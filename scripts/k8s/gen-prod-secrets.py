#!/usr/bin/env python3
"""Generate production secret material (every ``dev-secret-change-in-prod-*`` placeholder
regenerated) and write it to Vault in the chart's ExternalSecret layout; prints nothing
unless ``--show``.

    MDX_VAULT_ADDR=... MDX_VAULT_TOKEN=... python scripts/k8s/gen-prod-secrets.py [--dry-run]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import urllib.request

SECRET_LAYOUT: dict[str, dict[str, str]] = {
    # path (under <mount>/mdx/) → {field: kind}
    "keycloak-clients": {
        "KEYCLOAK_LOGIN_CLIENT_SECRET": "token",
        "KEYCLOAK_ADMIN_CLIENT_SECRET": "token",
    },
    "master-key": {
        # File-provider pods only; Transit-mode pods need no key file.
        "master.key": "bytes32-b64",
    },
    "infra": {
        "password": "token",  # postgres superuser
        "user": "literal:mdx",
        # Shares the postgres row shape; split if the hosting choice separates them.
    },
}


def _value(kind: str) -> str:
    if kind == "token":
        return secrets.token_urlsafe(32)
    if kind == "hex32":
        return secrets.token_hex(32)
    if kind == "bytes32-b64":
        return base64.b64encode(secrets.token_bytes(32)).decode()
    if kind.startswith("literal:"):
        return kind.split(":", 1)[1]
    raise ValueError(kind)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", action="store_true", help="print generated values (DANGEROUS)")
    ap.add_argument("--mount", default="secret")
    ap.add_argument("--prefix", default="mdx")
    args = ap.parse_args()

    addr = os.environ.get("MDX_VAULT_ADDR", "")
    token = os.environ.get("MDX_VAULT_TOKEN", "")
    if not args.dry_run and (not addr or not token):
        print("MDX_VAULT_ADDR / MDX_VAULT_TOKEN required (or use --dry-run)", file=sys.stderr)
        return 2

    for path, fields in SECRET_LAYOUT.items():
        data = {field: _value(kind) for field, kind in fields.items()}
        target = f"{args.mount}/data/{args.prefix}/{path}"
        if args.dry_run:
            print(f"would write {target}: fields={sorted(data)}")
            continue
        req = urllib.request.Request(
            f"{addr.rstrip('/')}/v1/{target}",
            data=json.dumps({"data": data}).encode(),
            headers={"X-Vault-Token": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            resp.read()
        shown = data if args.show else dict.fromkeys(data, "<generated>")
        print(f"wrote {target}: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
