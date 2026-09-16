#!/usr/bin/env python3
"""Provision a meeting-room capture device (IDX-B1b F5).

    export MDX_OPERATOR_TOKEN=...           # a platform-operator access token
    uv run python scripts/ops/idx-provision-device.py \
        --auth-url https://auth.example.com \
        --tenant 00000000-0000-0000-0000-00000000000a \
        --name "Room 4.02"

Prints the client id, the secret **once**, and the token URL to configure
on the device. Nothing is written to disk and nothing is logged: if the
terminal scrollback is lost before the device is configured, rotate.

Replaces the seven `kcadm` invocations the old runbook needed to create
one room (client, service-account user, three protocol mappers, a role
mapping, a secret read-back). That procedure was long enough that rooms
were provisioned by copying an existing client, which is how two rooms
end up sharing a secret.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from uuid import UUID


def _post(url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(  # noqa: S310 — operator-supplied https URL
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            body: dict[str, object] = json.loads(response.read())
            return body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"error: {exc.code} from {url}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: cannot reach {url}: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-url", required=True, help="e.g. https://auth.example.com")
    parser.add_argument("--tenant", required=True, type=UUID, help="workspace id")
    parser.add_argument("--name", required=True, help='the room, e.g. "Room 4.02"')
    parser.add_argument(
        "--token",
        default=os.environ.get("MDX_OPERATOR_TOKEN", ""),
        help="platform-operator access token (or MDX_OPERATOR_TOKEN)",
    )
    args = parser.parse_args()
    if not args.token:
        raise SystemExit(
            "error: no operator token. Set MDX_OPERATOR_TOKEN or pass --token.\n"
            "The endpoint also requires recent auth: sign in, or complete "
            "POST /auth/reauth, within the last few minutes."
        )

    base = args.auth_url.rstrip("/")
    created = _post(
        f"{base}/admin/credentials",
        args.token,
        {"kind": "device", "name": args.name, "tenant_id": str(args.tenant)},
    )
    credential = created["credential"]
    assert isinstance(credential, dict)

    print()
    print("  Device provisioned. The secret is shown ONCE — configure the room now.")
    print()
    print(f"  Room          {credential['name']}")
    print(f"  Workspace     {credential['tenant_id']}")
    print(f"  Token URL     {base}/auth/oauth/token")
    print(f"  client_id     {credential['id']}")
    print(f"  client_secret {created['secret']}")
    print()
    print("  Verify from the room (should print a JWT):")
    print(
        f"    curl -s -X POST {base}/auth/oauth/token \\\n"
        "      -d grant_type=client_credentials \\\n"
        f"      -d client_id={credential['id']} \\\n"
        "      -d client_secret=<the secret above> | jq -r .access_token"
    )
    print()
    print("  Record the room name and client_id in the sprint log. Never the secret.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
