"""Billing: the workspace's plan (``tenants.plan`` / ``plan_limits``), this month's
usage, and the provider seam (``MDX_BILLING_PROVIDER``: ``none`` shows plans and
changes nothing, ``manual`` changes the plan at once, ``stripe`` later). Limits
are shown, not enforced, except the AI allowance.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import asyncpg

from . import ai_settings

NONE: Final = "none"
MANUAL: Final = "manual"
STRIPE: Final = "stripe"
# The plan came from a redeem code, not from a payment.
CODE: Final = "code"

MONTHLY: Final = "monthly"
YEARLY: Final = "yearly"
INTERVALS: Final = (MONTHLY, YEARLY)


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    summary: str
    # Whole cents per member per month; None = "talk to us".
    price_cents: int | None
    currency: str
    # Whole cents per member per YEAR when paid yearly (two months free);
    # None = no yearly price (free, talk to us).
    yearly_price_cents: int | None = None
    # None = no limit. Keys match tenants.plan_limits.
    limits: dict[str, int | None] = field(default_factory=dict)
    features: tuple[str, ...] = ()
    # Offered in the picker. `legacy` is shown only to a workspace on it.
    offered: bool = True


# Prices and limits are placeholders until pricing is decided.
PLANS: Final[dict[str, Plan]] = {
    p.code: p
    for p in (
        Plan(
            code="free",
            name="Free",
            summary="For trying it out on your own meetings.",
            price_cents=0,
            currency="EUR",
            limits={
                "notes_per_month": 50,
                "recording_minutes_per_month": 300,
                "members": 3,
                "ai_cents_per_month": ai_settings.DEFAULT_BUDGET_CENTS,
            },
            features=("Meeting notes in the language you speak", "Share notes by link"),
        ),
        Plan(
            code="pro",
            name="Pro",
            summary="For a team that meets every day.",
            price_cents=1_800,
            currency="EUR",
            yearly_price_cents=18_000,
            limits={
                "notes_per_month": None,
                "recording_minutes_per_month": 3_000,
                "members": None,
                "ai_cents_per_month": 10_000,
            },
            features=(
                "Unlimited notes",
                "Premium writing model",
                "Your logo on shared notes, no product banner",
            ),
        ),
        Plan(
            code="enterprise",
            name="Enterprise",
            summary="For an organisation with its own rules.",
            price_cents=None,
            currency="EUR",
            limits={
                "notes_per_month": None,
                "recording_minutes_per_month": None,
                "members": None,
                # Never None: the budget reads a missing number as the
                # platform default, not as "no limit".
                "ai_cents_per_month": 100_000,
            },
            features=("Everything in Pro", "Your own model provider", "A contract and a DPA"),
        ),
        Plan(
            code="legacy",
            name="Legacy",
            summary="The plan this workspace had before plans existed.",
            price_cents=None,
            currency="EUR",
            limits={},
            offered=False,
        ),
    )
}

# What a person may pick by themselves; Enterprise is a conversation.
SELF_SERVE: Final[frozenset[str]] = frozenset({"free", "pro"})


def plan_of(code: str | None) -> Plan:
    return PLANS.get((code or "").strip().casefold(), PLANS["legacy"])


def effective_limits(plan: Plan, recorded: dict[str, Any] | None) -> dict[str, int | None]:
    """The catalogue's limits, with what is recorded on the tenant on top
    (an operator's exception wins over the catalogue)."""
    out: dict[str, int | None] = dict(plan.limits)
    for key, value in (recorded or {}).items():
        try:
            out[key] = None if value is None else int(value)
        except (TypeError, ValueError):
            continue
    return out


@dataclass(frozen=True)
class Usage:
    notes: int
    recording_minutes: int
    members: int
    ai_cents: int


@dataclass(frozen=True)
class Subscription:
    provider: str
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool
    interval: str = MONTHLY


async def tenant_plan(conn: asyncpg.Connection, *, tenant_id: UUID) -> tuple[str, dict[str, Any]]:
    record = await conn.fetchrow("SELECT plan, plan_limits FROM tenants WHERE id = $1", tenant_id)
    if record is None:
        return "legacy", {}
    limits = record["plan_limits"]
    return str(record["plan"] or "legacy"), (
        json.loads(limits) if isinstance(limits, str) else dict(limits or {})
    )


async def usage(conn: asyncpg.Connection, *, tenant_id: UUID) -> Usage:
    """This calendar month (UTC), as the AI budget counts it."""
    notes = await conn.fetchval(
        "SELECT count(*) FROM notes WHERE tenant_id = $1 AND deleted_at IS NULL "
        "AND created_at >= date_trunc('month', now())",
        tenant_id,
    )
    minutes = await conn.fetchval(
        "SELECT coalesce(sum(a.duration_ms), 0) / 60000 FROM transcription_jobs j "
        "JOIN audio_files a ON a.id = j.audio_id "
        "WHERE j.tenant_id = $1 AND j.queued_at >= date_trunc('month', now())",
        tenant_id,
    )
    members = await conn.fetchval(
        "SELECT count(*) FROM tenant_memberships WHERE tenant_id = $1 AND status = 'active'",
        tenant_id,
    )
    spent = await ai_settings.month_to_date_cents(conn, tenant_id=tenant_id)
    return Usage(
        notes=int(notes or 0),
        recording_minutes=int(minutes or 0),
        members=int(members or 0),
        ai_cents=spent,
    )


async def subscription(conn: asyncpg.Connection, *, tenant_id: UUID) -> Subscription | None:
    row = await conn.fetchrow(
        "SELECT provider, status, current_period_end, cancel_at_period_end, billing_interval "
        "FROM workspace_billing WHERE tenant_id = $1",
        tenant_id,
    )
    if row is None:
        return None
    return Subscription(
        provider=row["provider"],
        status=row["status"],
        current_period_end=row["current_period_end"],
        cancel_at_period_end=row["cancel_at_period_end"],
        interval=row["billing_interval"],
    )


async def apply_plan(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    plan: Plan,
    provider: str,
    actor: UUID,
    period_end: datetime | None = None,
    interval: str = MONTHLY,
) -> None:
    """Put the workspace on ``plan`` now, with the catalogue's limits —
    until ``period_end`` when it is given (a code for three months)."""
    await conn.execute(
        "SELECT set_tenant_plan($1, $2, $3::jsonb)",
        tenant_id,
        plan.code,
        json.dumps(plan.limits),
    )
    await conn.execute(
        """
        INSERT INTO workspace_billing
               (tenant_id, provider, status, updated_by, current_period_end,
                cancel_at_period_end, billing_interval)
        VALUES ($1, $2, 'active', $3, $4::timestamptz, $4::timestamptz IS NOT NULL, $5)
        ON CONFLICT (tenant_id) DO UPDATE
           SET provider = EXCLUDED.provider, status = 'active',
               current_period_end = EXCLUDED.current_period_end,
               cancel_at_period_end = EXCLUDED.cancel_at_period_end,
               billing_interval = EXCLUDED.billing_interval,
               updated_by = EXCLUDED.updated_by, updated_at = now()
        """,
        tenant_id,
        provider,
        actor,
        period_end,
        interval,
    )


# ── Redeem codes ────────────────────────────────────────────────────

# What a person types is forgiving: case, spaces and dashes do not count.
_CODE_NOISE = re.compile(r"[\s\-_]+")
CODE_MIN: Final = 8
CODE_MAX: Final = 64


def normalise_code(raw: str) -> str:
    return _CODE_NOISE.sub("", raw or "").upper()


def code_hash(raw: str) -> bytes:
    """What the table stores and looks up — never the code itself."""
    return hashlib.sha256(normalise_code(raw).encode("utf-8")).digest()


class RedeemError(Exception):
    """A code that cannot be redeemed: unknown, expired, used_up, already."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Redeemed:
    plan: Plan
    period_end: datetime | None
    days: int | None


async def redeem(conn: asyncpg.Connection, *, tenant_id: UUID, raw: str, actor: UUID) -> Redeemed:
    """Spend one code on this workspace and put it on the code's plan.
    Raises RedeemError with the reason the database gave."""
    code = normalise_code(raw)
    if not CODE_MIN <= len(code) <= CODE_MAX:
        raise RedeemError("unknown")
    try:
        row = await conn.fetchrow(
            "SELECT plan, duration_days FROM redeem_code($1, $2, $3)",
            tenant_id,
            code_hash(code),
            actor,
        )
    except asyncpg.RaiseError as exc:
        message = str(exc)
        if message.startswith("redeem:"):
            raise RedeemError(message.split(":", 1)[1]) from None
        raise
    plan = plan_of(row["plan"])
    days = row["duration_days"]
    period_end = datetime.now(UTC) + timedelta(days=int(days)) if days else None
    await apply_plan(
        conn, tenant_id=tenant_id, plan=plan, provider=CODE, actor=actor, period_end=period_end
    )
    return Redeemed(plan=plan, period_end=period_end, days=int(days) if days else None)


async def expire_if_due(conn: asyncpg.Connection, *, tenant_id: UUID) -> bool:
    """A plan given for a time ends when its time does: back to Free.
    True when it just ended. (Paid plans end through their provider.)"""
    due = await conn.fetchval(
        "SELECT 1 FROM workspace_billing WHERE tenant_id = $1 AND provider = 'code' "
        "AND current_period_end IS NOT NULL AND current_period_end <= now()",
        tenant_id,
    )
    if not due:
        return False
    free = PLANS["free"]
    await conn.execute(
        "SELECT set_tenant_plan($1, $2, $3::jsonb)", tenant_id, free.code, json.dumps(free.limits)
    )
    await conn.execute("DELETE FROM workspace_billing WHERE tenant_id = $1", tenant_id)
    return True
