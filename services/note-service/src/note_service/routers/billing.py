"""Billing: the workspace's plan, this month's usage, and changing the plan.

    GET  /v1/billing         the plan, the catalogue, usage against limits
    POST /v1/billing/plan    move to another plan (through the provider)
    POST /v1/billing/redeem  spend a redeem code, no provider needed

A change answers ``applied`` or ``redirect``; without a provider it is refused, not faked.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from ratelimit import FixedWindowLimiter

from .. import audit_kinds
from ..config import settings as app_settings
from ..deps import get_state, requires
from ..domain import ai_settings
from ..domain import billing as rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/billing", tags=["billing"])


class PlanView(BaseModel):
    code: str
    name: str
    summary: str
    price_cents: int | None
    currency: str
    # Per member per year when paid yearly; None = monthly only.
    yearly_price_cents: int | None
    limits: dict[str, int | None]
    features: list[str]
    # A person may switch to it here; Enterprise is "contact us".
    self_serve: bool


class UsageMeter(BaseModel):
    key: Literal["notes", "recording_minutes", "members", "ai"]
    used: int
    # None = no limit on this plan.
    limit: int | None


class SubscriptionView(BaseModel):
    provider: str
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool
    interval: Literal["monthly", "yearly"]


class BillingView(BaseModel):
    plan: PlanView
    plans: list[PlanView]
    usage: list[UsageMeter]
    period_start: datetime
    subscription: SubscriptionView | None
    # False until a payment provider is connected: the client shows the
    # plans but says why it cannot switch.
    payments_connected: bool
    can_edit: bool


class ChangePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str
    interval: Literal["monthly", "yearly"] = "monthly"


class RedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)


class ChangePlanResult(BaseModel):
    action: Literal["applied", "redirect"]
    redirect_url: str | None = None
    billing: BillingView


def _plan_view(plan: rules.Plan, limits: dict[str, int | None] | None = None) -> PlanView:
    return PlanView(
        code=plan.code,
        name=plan.name,
        summary=plan.summary,
        price_cents=plan.price_cents,
        currency=plan.currency,
        yearly_price_cents=plan.yearly_price_cents,
        limits=dict(plan.limits if limits is None else limits),
        features=list(plan.features),
        self_serve=plan.code in rules.SELF_SERVE,
    )


async def _view(conn: object, claims: Claims) -> BillingView:
    code, recorded = await rules.tenant_plan(conn, tenant_id=claims.tid)  # type: ignore[arg-type]
    plan = rules.plan_of(code)
    limits = rules.effective_limits(plan, recorded)
    used = await rules.usage(conn, tenant_id=claims.tid)  # type: ignore[arg-type]
    # The AI allowance shown is the one enforced.
    settings_row = await ai_settings.fetch(conn, tenant_id=claims.tid)  # type: ignore[arg-type]
    ai_limit = ai_settings.budget_cents(settings_row, recorded or plan.limits)
    sub = await rules.subscription(conn, tenant_id=claims.tid)  # type: ignore[arg-type]
    period = await conn.fetchval("SELECT date_trunc('month', now())")  # type: ignore[attr-defined]
    return BillingView(
        plan=_plan_view(plan, limits),
        plans=[_plan_view(p) for p in rules.PLANS.values() if p.offered],
        usage=[
            UsageMeter(key="notes", used=used.notes, limit=limits.get("notes_per_month")),
            UsageMeter(
                key="recording_minutes",
                used=used.recording_minutes,
                limit=limits.get("recording_minutes_per_month"),
            ),
            UsageMeter(key="members", used=used.members, limit=limits.get("members")),
            UsageMeter(key="ai", used=used.ai_cents, limit=ai_limit),
        ],
        period_start=period,
        subscription=(
            SubscriptionView(
                provider=sub.provider,
                status=sub.status,
                current_period_end=sub.current_period_end,
                cancel_at_period_end=sub.cancel_at_period_end,
                interval=sub.interval,  # type: ignore[arg-type]
            )
            if sub
            else None
        ),
        payments_connected=app_settings.billing_provider != rules.NONE,
        can_edit="tenant_admin" in claims.roles,
    )


@router.get("", response_model=BillingView)
async def get_billing(
    claims: Annotated[Claims, Depends(requires("billing.read", "tenant"))],
) -> BillingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        await rules.expire_if_due(conn, tenant_id=claims.tid)
        return await _view(conn, claims)


@router.post("/plan", response_model=ChangePlanResult)
async def change_plan(
    body: ChangePlanRequest,
    claims: Annotated[Claims, Depends(requires("billing.write", "tenant"))],
) -> ChangePlanResult:
    target = rules.PLANS.get(body.plan.strip().casefold())
    if target is None or not target.offered:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unknown_plan", "detail": "there is no such plan"},
        )
    if target.code not in rules.SELF_SERVE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "plan_contact_sales", "detail": "this plan is arranged with us"},
        )
    # A plan with no yearly price is billed monthly, whatever was asked.
    interval = body.interval if target.yearly_price_cents is not None else rules.MONTHLY
    provider = app_settings.billing_provider
    if provider == rules.NONE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "billing_not_connected",
                "detail": "payments are not connected yet, so the plan cannot change here",
            },
        )

    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        current, _ = await rules.tenant_plan(conn, tenant_id=claims.tid)
        sub = await rules.subscription(conn, tenant_id=claims.tid)
        current_interval = sub.interval if sub else rules.MONTHLY
        # Pro monthly → Pro yearly is a change too.
        changed = current != target.code or current_interval != interval
        if changed:
            await rules.apply_plan(
                conn,
                tenant_id=claims.tid,
                plan=target,
                provider=provider,
                actor=claims.sub,
                interval=interval,
            )
        view = await _view(conn, claims)

    if changed:
        await state.audit_writer.write_event(
            tenant_id=claims.tid,
            kind=audit_kinds.BILLING_PLAN_CHANGED,
            actor_sub=claims.sub,
            actor_role=(claims.roles[0] if claims.roles else None),
            target_kind="tenant",
            target_id=claims.tid,
            payload={
                "from_plan": current,
                "to_plan": target.code,
                "interval": interval,
                "provider": provider,
            },
            severity=Severity.INFO,
        )
        # The premium tier and the budget read the plan; drop the cache.
        source = getattr(state, "workspace_model_settings", None)
        if source is not None:
            source.invalidate(claims.tid)
    return ChangePlanResult(action="applied", billing=view)


# A code is 80 random bits; this is the second wall, not the first.
REDEEM_ATTEMPTS_PER_HOUR = 10

_REDEEM_COPY = {
    "unknown": "that code is not valid",
    "expired": "that code has expired",
    "used_up": "that code has been used as many times as it allows",
    "already": "this workspace has already used that code",
}


async def _redeem_allowed(state: object, claims: Claims) -> None:
    redis = getattr(state, "redis", None)
    if redis is None:
        return
    limiter = FixedWindowLimiter(redis, prefix="note:redeem")
    for scope, subject in (("tenant", str(claims.tid)), ("user", str(claims.sub))):
        decision = await limiter.allow(
            scope, subject, limit=REDEEM_ATTEMPTS_PER_HOUR, window_seconds=3600, fail_open=True
        )
        if not decision.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "redeem_rate_limited", "detail": "too many tries — wait a while"},
                headers={"Retry-After": str(decision.retry_after)},
            )


@router.post("/redeem", response_model=ChangePlanResult)
async def redeem_code(
    body: RedeemRequest,
    claims: Annotated[Claims, Depends(requires("billing.write", "tenant"))],
) -> ChangePlanResult:
    """Put the workspace on the plan a code gives. Works with no payment
    provider at all — that is what codes are for."""
    state = get_state()
    await _redeem_allowed(state, claims)
    try:
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            before, _ = await rules.tenant_plan(conn, tenant_id=claims.tid)
            redeemed = await rules.redeem(
                conn, tenant_id=claims.tid, raw=body.code, actor=claims.sub
            )
            view = await _view(conn, claims)
    except rules.RedeemError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND if exc.reason == "unknown" else status.HTTP_409_CONFLICT,
            detail={"code": f"redeem_{exc.reason}", "detail": _REDEEM_COPY.get(exc.reason, "")},
        ) from None

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.BILLING_CODE_REDEEMED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="tenant",
        target_id=claims.tid,
        # Never the code: it may be one many workspaces share.
        payload={
            "from_plan": before,
            "to_plan": redeemed.plan.code,
            "days": redeemed.days,
        },
        severity=Severity.INFO,
    )
    source = getattr(state, "workspace_model_settings", None)
    if source is not None:
        source.invalidate(claims.tid)
    return ChangePlanResult(action="applied", billing=view)
