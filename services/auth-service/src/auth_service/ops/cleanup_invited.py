"""``python -m auth_service.ops.cleanup_invited`` — drop signups nobody finished.

    python -m auth_service.ops.cleanup_invited --dry-run
    python -m auth_service.ops.cleanup_invited --older-than-days 30
    python -m auth_service.ops.cleanup_invited --yes

An account that was created and never confirmed occupies its address
forever: the person cannot sign up again with it, and the uniform 202
means they are never told why. Thirty days is long enough that a holiday
does not lose somebody their signup, short enough that the address frees
up while they still remember trying.

Four things go, in the order the foreign keys allow: the Keycloak user,
the `users` row, the membership, and the personal workspace — the last one
only when it is empty and personal, because a team workspace with other
people in it is not this command's to delete.

**Only `invited` accounts.** An active account is never touched, whatever
its age, and neither is one an operator deactivated. The query says so and
the dry run prints what it matched, which is the part to read before
passing ``--yes``.

Exit codes: 0 (including "nothing to do"), 1 the command failed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any
from uuid import UUID

logger = logging.getLogger("auth_service.ops.cleanup_invited")

# An identity that never confirmed. `email_verified_at IS NULL` is the
# marker rather than `users.status = 'invited'` for the reason
# OnboardingService uses it: `users` is RLS-scoped per tenant and this
# command has no tenant in hand, while `identities` is person-level.
STALE = """
SELECT i.id, i.email, i.last_tenant_id, i.created_at
  FROM identities i
 WHERE i.email_verified_at IS NULL
   AND i.status = 'active'
   AND i.created_at < now() - ($1::int * interval '1 day')
 ORDER BY i.created_at
"""

# A workspace is only removed when this person is its only member AND it
# is personal. A team workspace outlives whoever failed to confirm.
IS_LONE_PERSONAL = """
SELECT t.kind = 'personal'
       AND (SELECT count(*) FROM tenant_memberships m WHERE m.tenant_id = t.id) <= 1
  FROM tenants t WHERE t.id = $1
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdx-cleanup-invited", description=__doc__)
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="age threshold (default: AUTH_SIGNUP_STALE_AFTER_DAYS, 30)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be removed; change nothing"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="actually delete (without this, --dry-run is assumed)",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    from ..config import settings
    from ..deps import install_state
    from ..main_deps import build_state, teardown_state

    # `is None`, not `or`: `--older-than-days 0` is a legitimate request
    # ("everything unconfirmed, right now") and `or` would silently turn
    # it back into the 30-day default.
    days = (
        settings.signup_stale_after_days
        if args.older_than_days is None
        else args.older_than_days
    )
    # Deleting accounts is not something to do because a flag was
    # forgotten, so the safe mode is the default and --yes is the opt-in.
    dry = args.dry_run or not args.yes

    state = await build_state()
    install_state(state)
    try:
        async with state.tenant_writer_pool.acquire() as conn:
            rows = await conn.fetch(STALE, days)

        if not rows:
            print(f"nothing to do: no unconfirmed signups older than {days} days")
            return 0

        print(f"{len(rows)} unconfirmed signup(s) older than {days} days:")
        for row in rows:
            print(f"  {row['email']}  created {row['created_at']:%Y-%m-%d}")
        if dry:
            print("\ndry run — nothing was deleted. Re-run with --yes to remove them.")
            return 0

        removed = 0
        for row in rows:
            try:
                await _remove_one(state, row)
                removed += 1
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the rest
                logger.error(
                    "auth.cleanup.failed",
                    extra={"identity_id": str(row["id"]), "error_class": type(exc).__name__},
                )
                print(f"  FAILED {row['email']}: {exc}", file=sys.stderr)
        print(f"removed {removed} of {len(rows)}")
        return 0 if removed == len(rows) else 1
    finally:
        await teardown_state(state)


async def _remove_one(state: Any, row: Any) -> None:
    """Keycloak first, then the rows, in FK order.

    Keycloak first for the same reason signup writes it first: a Keycloak
    user we failed to delete is visible and fixable, while database rows
    pointing at a user that is already gone are not.
    """
    identity_id: UUID = row["id"]
    tenant_id: UUID | None = row["last_tenant_id"]

    await state.keycloak.delete_user(identity_id)

    async with state.tenant_writer_pool.acquire() as conn, conn.transaction():
        drop_tenant = False
        if tenant_id is not None:
            drop_tenant = bool(await conn.fetchval(IS_LONE_PERSONAL, tenant_id))
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
            await conn.execute(
                "DELETE FROM users WHERE sub = $1 AND tenant_id = $2", identity_id, tenant_id
            )
        await conn.execute(
            "DELETE FROM tenant_memberships WHERE user_sub = $1", identity_id
        )
        await conn.execute("DELETE FROM auth_challenges WHERE identity_id = $1", identity_id)
        await conn.execute("DELETE FROM identities WHERE id = $1", identity_id)
        if drop_tenant and tenant_id is not None:
            await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_id)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    return asyncio.run(_run(_build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
