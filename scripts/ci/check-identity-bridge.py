#!/usr/bin/env python3
"""CI gate: every active identity has its bridge ``users`` row (BE-1).

``users`` is how the rest of the estate turns a ``sub`` into a person.
note-service reads it to offer share recipients; notification-service
reads it to find an address to mail. An identity without one holds a
perfectly valid token, writes notes nobody can share with them, and
receives no mail — and every one of those failures is silent on the path
that produces it. Nothing 500s; the person is simply not there.

(The authorship foreign keys — ``notes.primary_author_id``,
``note_versions.created_by``, ``autocomplete_*.owner_user_id`` — moved to
``identities`` in migration 0028, so this is no longer about being able
to save a note. It is about being findable.)

The rule (ADR-IDX-03: "``users`` is a bridge until B2") is that the row is
written in the SAME transaction as the identity and its personal tenant —
``create_with_personal_workspace`` and ``ensure_personal_workspace`` are
the only writers. This gate is what keeps that true: a second code path
that creates identities, or a transaction boundary drawn in the wrong
place, shows up here rather than as a person who cannot be shared with.

Runs against a live database, beside ``check-rls-policies.py`` and
``check-identity-grants.py``::

    DATABASE_URL=postgres://... uv run python scripts/ci/check-identity-bridge.py

Exit codes:
    0 — every active identity is bridged (and on a fresh DB, there are none)
    1 — unbridged identities found; their ids are printed
    2 — could not reach the database
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

# The superuser DSN, as `check-rls-policies.py` uses. It has to be:
# `app_role` holds NO grant on `identities` — that is `check-identity-grants.py`
# talking, and this gate must not be the reason somebody widens it.
DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/notes"

# The assertion from the sprint brief, verbatim in intent: an active
# identity with no `users` row is a person who cannot author content.
UNBRIDGED = """
SELECT i.id, i.email, i.legacy_idp
  FROM identities i
  LEFT JOIN users u ON u.sub = i.id
 WHERE u.sub IS NULL
   AND i.status = 'active'
 ORDER BY i.created_at
 LIMIT 50
"""

COUNT = """
SELECT count(*) FROM identities i
  LEFT JOIN users u ON u.sub = i.id
 WHERE u.sub IS NULL AND i.status = 'active'
"""

# The other half of the rule: a bridge row must point at a tenant the
# identity is actually a member of. A `users` row on a tenant with no
# matching membership authors content into a workspace nobody can reach.
ORPHAN_BRIDGE = """
SELECT u.sub, u.tenant_id
  FROM users u
  JOIN identities i ON i.id = u.sub
 WHERE NOT EXISTS (
           SELECT 1 FROM tenant_memberships m
            WHERE m.user_sub = u.sub AND m.tenant_id = u.tenant_id
       )
 LIMIT 50
"""


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    try:
        conn = await asyncpg.connect(dsn)
    except Exception as exc:  # noqa: BLE001 — an unreachable DB is not a violation
        print(f"check-identity-bridge: cannot connect ({exc})", file=sys.stderr)
        print("Is the dev stack up? `make dev-up && make migrate-up`", file=sys.stderr)
        return 2

    try:
        total = await conn.fetchval(COUNT)
        rows = await conn.fetch(UNBRIDGED) if total else []
        orphans = await conn.fetch(ORPHAN_BRIDGE)
    finally:
        await conn.close()

    failed = False

    if total:
        failed = True
        print(f"check-identity-bridge: FAIL — {total} active identity(ies) with no users row", file=sys.stderr)
        for row in rows:
            origin = "backfilled (legacy_idp)" if row["legacy_idp"] else "native signup"
            print(f"  {row['id']}  {row['email']}  [{origin}]", file=sys.stderr)
        if total > len(rows):
            print(f"  … and {total - len(rows)} more", file=sys.stderr)
        print(
            "\nEvery identity needs a bridge `users` row written in the same "
            "transaction as its personal tenant — see "
            "IdentityRepository.create_with_personal_workspace / "
            "ensure_personal_workspace and migration "
            "0031_identity_legacy_idp.sql. Without one the person cannot be "
            "found as a share recipient and receives no notification mail.",
            file=sys.stderr,
        )

    if orphans:
        failed = True
        print(
            f"check-identity-bridge: FAIL — {len(orphans)} bridge row(s) on a "
            "tenant the identity is not a member of",
            file=sys.stderr,
        )
        for row in orphans:
            print(f"  sub={row['sub']} tenant={row['tenant_id']}", file=sys.stderr)

    if failed:
        return 1

    print("check-identity-bridge: OK — every active identity is bridged")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
