#!/usr/bin/env python3
"""Re-wrap stored TOTP secrets through the libs/crypto envelope after a master-key or
platform-tenant change. One transaction per row, idempotent; an undecryptable row is
reported and skipped, never deleted.

    uv run python scripts/ops/idx-rekey-totp-secrets.py --dry-run | --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from uuid import UUID

import asyncpg

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "auth-service", "src"),
)

from auth_service import totp  # noqa: E402
from auth_service.config import settings  # noqa: E402


async def _envelope() -> object:
    """Build just enough ServiceState to get an Envelope."""
    from crypto import Envelope, TenantKekRepository, build_master_key_provider
    from db import create_pool

    master = build_master_key_provider(
        provider=settings.master_key_provider,
        file_path=settings.master_key_path,
        vault_addr=settings.vault_addr,
        vault_token=settings.vault_token,
        vault_transit_key=settings.vault_transit_key,
        vault_transit_mount=settings.vault_transit_mount,
    )
    await master.startup_self_check()
    pool = await create_pool(settings.db_crypto_writer_dsn, application_name="idx-rekey")
    return Envelope(
        master_key_provider=master,
        kek_repository=TenantKekRepository(pool=pool, master_key_provider=master),
    )


async def run(*, dsn: str, apply: bool) -> int:
    envelope = await _envelope()
    target_tenant = UUID(settings.auth_platform_tenant_id)
    conn = await asyncpg.connect(dsn)
    rewrapped = failed = skipped = 0
    try:
        rows = await conn.fetch(
            "SELECT identity_id, secret_enc, kek_tenant_id FROM identity_totp"
            " WHERE confirmed_at IS NOT NULL ORDER BY identity_id"
        )
        print(f"{len(rows)} confirmed second factor(s) to consider")
        for row in rows:
            identity_id = row["identity_id"]
            try:
                secret = await totp.decrypt_secret(
                    envelope,  # type: ignore[arg-type]
                    packed=row["secret_enc"],
                    tenant_id=row["kek_tenant_id"],
                    sub=identity_id,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  ! {identity_id}: cannot decrypt ({type(exc).__name__}) — skipped")
                continue
            if not apply:
                skipped += 1
                continue
            packed = await totp.encrypt_secret(
                envelope,  # type: ignore[arg-type]
                secret=secret,
                tenant_id=target_tenant,
                sub=identity_id,
            )
            async with conn.transaction():
                await conn.execute(
                    "UPDATE identity_totp SET secret_enc = $2, kek_tenant_id = $3"
                    " WHERE identity_id = $1",
                    identity_id,
                    packed,
                    target_tenant,
                )
            rewrapped += 1
            print(f"  + {identity_id}")
    finally:
        await conn.close()

    if apply:
        print(f"\nre-wrapped {rewrapped}, undecryptable {failed}")
    else:
        print(
            f"\n--dry-run: {skipped} row(s) decrypt cleanly and would be re-wrapped, "
            f"{failed} cannot be decrypted. Re-run with --apply."
        )
    # An unreadable row is an operator problem: say so in the exit code.
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn", default=os.environ.get("DB_TENANT_WRITER_DSN", settings.db_tenant_writer_dsn)
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(dsn=args.dsn, apply=bool(args.apply)))


if __name__ == "__main__":
    sys.exit(main())
