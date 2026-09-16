#!/usr/bin/env python3
"""CI gate — `app_role` must never reach identity or credential secrets.

`app_role` is the role every product service in the fleet connects as. It
is the widest-blast-radius database credential in the system, and these
tables are the ones where a read is equivalent to an authentication
bypass:

* ``identity_totp``            — second-factor secrets (encrypted, but the
                                 envelope is not the only control)
* ``identity_recovery_codes``  — the paper credentials
* ``service_credential_secrets`` — every room device's client secret hash
* ``identities`` / ``auth_challenges`` / ``auth_sessions`` — live codes,
                                 lockout state, every registered address

RLS would already deny them (none has an `app_role` policy), but a grant
is the thing a future migration is most likely to add absent-mindedly,
and a `GRANT ... ON ALL TABLES` would sweep them all in at once. This gate
reads the migrations rather than a live database so it fails in CI, on the
diff that introduced it, rather than in staging.

Exit codes:
    0 — no violations
    1 — violations printed to stderr
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "infra" / "postgres" / "migrations"

# Tables `app_role` must hold no privilege on at all.
SEALED_TABLES: frozenset[str] = frozenset(
    {
        "identities",
        "auth_challenges",
        "auth_sessions",
        "identity_totp",
        "identity_recovery_codes",
        "service_credential_secrets",
    }
)

# Tables `app_role` may READ (tenant-scoped by RLS) but never write.
READ_ONLY_TABLES: frozenset[str] = frozenset({"service_credentials"})

_GRANT = re.compile(
    r"GRANT\s+(?P<privs>[A-Z ,]+?)\s+ON\s+(?:TABLE\s+)?(?P<table>[a-z_.]+)\s+TO\s+(?P<roles>[a-z_, ]+)",
    re.IGNORECASE,
)
_GRANT_ALL_TABLES = re.compile(r"GRANT\s+[A-Z ,]+\s+ON\s+ALL\s+TABLES", re.IGNORECASE)


def main() -> int:
    violations: list[str] = []

    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name.endswith(".down.sql"):
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()

        for match in _GRANT_ALL_TABLES.finditer(text):
            line = text[: match.start()].count("\n") + 1
            violations.append(
                f"{rel}:{line}  GRANT ... ON ALL TABLES sweeps in the sealed tables; "
                "grant per table instead"
            )

        for match in _GRANT.finditer(text):
            roles = {r.strip().lower() for r in match.group("roles").split(",")}
            if "app_role" not in roles:
                continue
            table = match.group("table").lower().removeprefix("public.")
            privs = {p.strip().upper() for p in match.group("privs").split(",")}
            line = text[: match.start()].count("\n") + 1
            if table in SEALED_TABLES:
                violations.append(
                    f"{rel}:{line}  app_role is granted {sorted(privs)} on '{table}' — "
                    "this table must be tenant_writer only"
                )
            elif table in READ_ONLY_TABLES and privs - {"SELECT"}:
                violations.append(
                    f"{rel}:{line}  app_role is granted {sorted(privs - {'SELECT'})} on "
                    f"'{table}' — read only"
                )

    if violations:
        print("ERROR: app_role reaches identity/credential material:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nIdentity and credential tables are tenant_writer-only. "
            "See infra/postgres/migrations/0024, 0025, 0026.",
            file=sys.stderr,
        )
        return 1

    print(
        f"ok: app_role holds nothing on {len(SEALED_TABLES)} sealed table(s) "
        f"and read-only on {len(READ_ONLY_TABLES)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
