#!/usr/bin/env python3
"""Erase everything held about one recipient address (DSAR): link addresses nulled,
responses cleared, OTPs and leads deleted, suppression hash deleted unless
``--keep-suppression``. Links keep working until they expire. Prints counts only.

    DB_TENANT_WRITER_DSN=... MDX_SHARE_MAIL_SUPPRESSION_PEPPER_HEX=... uv run python scripts/ops/erase_recipient.py --email tom@client.com [--keep-suppression]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys

import asyncpg


def _n(result: str | None) -> int:
    return int(result.split()[-1]) if result else 0


async def main(email: str, keep_suppression: bool) -> int:
    dsn = os.environ.get("DB_TENANT_WRITER_DSN")
    pepper_hex = os.environ.get("MDX_SHARE_MAIL_SUPPRESSION_PEPPER_HEX", "")
    if not dsn:
        print("DB_TENANT_WRITER_DSN is not set", file=sys.stderr)
        return 2
    address = email.strip().lower()
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            # tenant_writer is not RLS-scoped on note_share_links; walk tenants
            # explicitly so the per-tenant setting is honoured where a policy applies.
            tenant_ids = [r["id"] for r in await conn.fetch("SELECT id FROM tenants")]
            links = responses = otps = 0
            for tid in tenant_ids:
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tid))
                ids = [
                    r["id"]
                    for r in await conn.fetch(
                        "SELECT id FROM note_share_links WHERE tenant_id = $1 AND lower(recipient_email) = $2",
                        tid,
                        address,
                    )
                ]
                if not ids:
                    continue
                responses += _n(
                    await conn.execute(
                        "UPDATE share_link_responses SET cleared_at = now() WHERE link_id = ANY($1::uuid[]) AND cleared_at IS NULL",
                        ids,
                    )
                )
                otps += _n(
                    await conn.execute(
                        "DELETE FROM share_link_otps WHERE link_id = ANY($1::uuid[])", ids
                    )
                )
                links += _n(
                    await conn.execute(
                        "UPDATE note_share_links SET recipient_email = NULL WHERE id = ANY($1::uuid[])",
                        ids,
                    )
                )
            leads = _n(
                await conn.execute("DELETE FROM referrals WHERE lower(lead_email) = $1", address)
            )
            suppressions = 0
            if not keep_suppression and pepper_hex:
                digest = hashlib.sha256(
                    bytes.fromhex(pepper_hex) + address.encode("utf-8")
                ).digest()
                suppressions = _n(
                    await conn.execute(
                        "DELETE FROM share_mail_suppressions WHERE email_hash = $1", digest
                    )
                )
    finally:
        await conn.close()
    print(
        f"erase_recipient links={links} responses={responses} otps={otps} leads={leads} "
        f"suppressions={suppressions}"
    )
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--keep-suppression", action="store_true")
    args = ap.parse_args()
    if "@" not in args.email:
        print("--email must be an address", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(args.email, args.keep_suppression)))
