"""Referral leads (migration 0036, Sprint 19).

One table, global by design — see the migration. This sprint records the
fake-door lead; Sprint 21 adds the row that ties a real signup back to
the link it came from.
"""

from __future__ import annotations

import asyncpg


async def record_lead(pool: asyncpg.Pool, *, ref_code: str, email: str) -> bool:
    """Store a lead. The same address through the same link is one lead:
    a repeat submit is a no-op and answers False."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            INSERT INTO referrals (ref_code, lead_email, lead_consent_at, source)
            VALUES ($1, $2, now(), 'share_cta')
            ON CONFLICT (lower(lead_email), ref_code) WHERE lead_email IS NOT NULL
            DO NOTHING
            """,
            ref_code,
            email.strip().lower(),
        )
    return bool(result) and result.split()[-1] == "1"
