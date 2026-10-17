"""``python -m auth_service.ops.ensure_personal [--dry-run]`` — every person gets a Personal workspace.

W1 (ADR-0069): for every active identity with no membership in a ``kind='personal'``
tenant, call ``IdentityRepository.ensure_personal_workspace``. Idempotent; run once per
environment after deploy, then `make check-identity-bridge` must be green. Prints ids
and counts, never an address. Exit codes: 0 every identity has one, 1 a heal failed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logger = logging.getLogger("auth_service.ops.ensure_personal")

MISSING = """
SELECT i.id, i.email, i.locale
  FROM identities i
 WHERE i.status = 'active'
   AND NOT EXISTS (SELECT 1 FROM tenant_memberships m
                     JOIN tenants t ON t.id = m.tenant_id
                    WHERE m.user_sub = i.id AND t.kind = 'personal')
 ORDER BY i.created_at
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdx-ensure-personal", description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="count who would be healed; change nothing"
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    # Imported inside the function so `--help` works without a database.
    from ..deps import install_state
    from ..domain.identity_repository import IdentityRepository
    from ..main_deps import build_state, teardown_state

    state = await build_state()
    install_state(state)
    try:
        async with state.tenant_writer_pool.acquire() as conn:
            rows = await conn.fetch(MISSING)
        print(
            f"{len(rows)} active identit{'y' if len(rows) == 1 else 'ies'} without a Personal workspace"
        )
        if args.dry_run or not rows:
            return 0

        identities = IdentityRepository(state.tenant_writer_pool)
        healed = skipped = failed = 0
        for row in rows:
            try:
                created = await identities.ensure_personal_workspace(
                    row["id"], row["email"], locale=row["locale"] or "en"
                )
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the rest
                failed += 1
                logger.error(
                    "auth.personal.heal_failed",
                    extra={"identity_id": str(row["id"]), "error_class": type(exc).__name__},
                )
                print(f"  FAILED {row['id']}: {type(exc).__name__}", file=sys.stderr)
                continue
            if created is None:
                skipped += 1  # healed concurrently (sign-in or refresh got there first)
            else:
                healed += 1
                print(f"  healed {row['id']} → {created.tenant_id}")
        print(f"healed {healed}, already had one {skipped}, failed {failed}")
        return 0 if failed == 0 else 1
    finally:
        await teardown_state(state)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    return asyncio.run(_run(_build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
