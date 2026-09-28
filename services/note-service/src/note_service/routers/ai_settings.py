"""Who processes this workspace's meetings (Sprint 37).

    GET /v1/ai/settings   every member: the processors, the tier, the spend
    PUT /v1/ai/settings   tenant_admin: change it, after acknowledging

The page behind this is the one ADR-0046 decision 12 promised. Two rules
carry the whole thing:

* **The processor list is computed, not written.** It comes from the same
  `Registry` object that routes the calls, so a change to
  `config/models.yaml` cannot put a new company in somebody's data path
  while the page still shows the old list. A disclosure page that can
  drift from reality is worse than no page, because people believe it.
* **Every member may read it; only an admin with MFA may change it.**
  Who processes your employer's meetings is not admin-only information.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..config import settings as app_settings
from ..deps import get_state, requires
from ..domain import ai_settings as rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ai", tags=["ai"])

_ADMIN_ROLES = frozenset({"tenant_admin"})

# What each operation's processor does with the data lives with the rules
# (`domain/ai_settings.PURPOSES`) since Sprint L2, so the generation gate
# and this page read one table.
PURPOSES = rules.PURPOSES


class ProcessorView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    region: str
    """What this company does with the data, in words a customer can
    check against their DPA. Derived from the routing table, not typed
    into a page."""
    purpose: str
    """Which tiers route to it (`standard`, `premium`)."""
    tiers: list[str] = []
    acknowledged: bool


class WriterView(BaseModel):
    """Sprint L2 — who writes the notes on this deployment right now, and
    whether that is the configured primary or its fallback."""

    model_config = ConfigDict(extra="forbid")

    backend: str
    model_id: str | None = None
    processor: str | None = None
    region: str | None = None
    primary: str
    fallback: str | None = None
    """None while the primary is in use; else `missing_env`, `forced` or
    `probe_failed` — why the fallback is writing."""
    reason: str | None = None


class SettingsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    tier: str
    generation_enabled: bool
    """What this workspace ACTUALLY resolves to. Differs from `tier` when
    routing gained a processor nobody has acknowledged yet."""
    effective_provider: str
    effective_tier: str
    processors: list[ProcessorView]
    """Processors in the data path that nobody has agreed to. Non-empty
    means an admin has something to look at."""
    needs_acknowledgement: list[ProcessorView]
    month_to_date_cents: int
    budget_cents: int
    """Whether this plan may choose the premium tier at all."""
    may_choose_premium: bool
    can_edit: bool
    """Sprint L2 — the backend writing notes on this deployment (the large
    model), and `small` the one behind classification, titles and names.
    None where nothing is routed."""
    writer: WriterView | None = None
    small_writer: WriterView | None = None


class AcknowledgedProcessor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=120)
    region: str = Field(max_length=120)


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["platform", "anthropic", "custom"] | None = None
    tier: Literal["standard", "premium"] | None = None
    generation_enabled: bool | None = None
    monthly_budget_cents: int | None = Field(default=None, ge=0)
    """The exact processors the admin is agreeing to. Must cover every
    processor the new setting would route to, or the change is refused."""
    acknowledge: list[AcknowledgedProcessor] = Field(default_factory=list, max_length=50)


def _required_processors() -> list[rules.Processor]:
    """Every processor a workspace on this environment can be routed to.

    Read from the registry rather than from a list in the code: this is
    the guarantee that the page and the router agree. Purposes and tiers
    come from the routing table itself, so a new route cannot appear
    without appearing here.
    """
    try:
        return rules.required_processors(_registry())
    except Exception:  # noqa: BLE001
        # No registry on this deployment (a dev Mac with no model
        # config). An empty list is honest: nothing is routed anywhere.
        logger.warning("ai_settings.registry_unavailable", exc_info=True)
        return []


# The other routers read the same list before starting a generation
# (Sprint L2): a processor nobody agreed to blocks the run before a byte
# leaves the laptop.
def required_processors() -> list[rules.Processor]:
    return _required_processors()


def _registry() -> Any:
    """The process's registry (probed at startup, fallback decided) when the
    service built one; else a fresh load — so the page and the router read
    the same object either way."""
    registry = getattr(get_state(), "model_registry", None)
    if registry is not None:
        return registry
    from models import Registry

    return Registry.load(
        app_settings.models_config,
        env=app_settings.registry_env(),
        environ=app_settings.registry_environ(),
        validate=False,
    )


def _writers() -> tuple[WriterView | None, WriterView | None]:
    """Sprint L2 — the "Notes are written by" line, from the registry."""
    try:
        from ..domain.model_routing import describe

        described = describe(_registry())
    except Exception:  # noqa: BLE001
        logger.warning("ai_settings.writer_unavailable", exc_info=True)
        return None, None
    if not described:
        return None, None
    small = described.pop("small", None)
    return WriterView(**described), (WriterView(**small) if small else None)


async def _plan(conn: Any, tenant_id: UUID) -> tuple[str, dict[str, Any]]:
    record = await conn.fetchrow("SELECT plan, plan_limits FROM tenants WHERE id = $1", tenant_id)
    if record is None:
        return "free", {}
    import json

    limits = record["plan_limits"]
    return str(record["plan"] or "free"), (
        json.loads(limits) if isinstance(limits, str) else (limits or {})
    )


def _view(
    row: rules.SettingsRow,
    *,
    processors: list[rules.Processor],
    spend: int,
    budget: int,
    plan: str,
    claims: Claims,
) -> SettingsView:
    provider, tier, unacknowledged = rules.effective(row, processors)
    agreed = row.acknowledged_keys
    writer, small_writer = _writers()
    return SettingsView(
        provider=row.provider,
        tier=row.tier,
        generation_enabled=row.generation_enabled,
        effective_provider=provider,
        effective_tier=tier,
        processors=[
            ProcessorView(
                name=p.name,
                region=p.region,
                purpose=p.purpose,
                tiers=list(p.tiers),
                acknowledged=p.key() in agreed,
            )
            for p in processors
        ],
        needs_acknowledgement=[
            ProcessorView(
                name=p.name,
                region=p.region,
                purpose=p.purpose,
                tiers=list(p.tiers),
                acknowledged=False,
            )
            for p in unacknowledged
        ],
        month_to_date_cents=spend,
        budget_cents=budget,
        may_choose_premium=rules.may_choose_premium(plan),
        can_edit=bool(_ADMIN_ROLES & set(claims.roles)),
        writer=writer,
        small_writer=small_writer,
    )


@router.get("/settings", response_model=SettingsView)
async def get_ai_settings(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> SettingsView:
    """Every member may see who processes their meetings."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await rules.fetch(conn, tenant_id=claims.tid)
        spend = await rules.month_to_date_cents(conn, tenant_id=claims.tid)
        plan, limits = await _plan(conn, claims.tid)
    return _view(
        row,
        processors=_required_processors(),
        spend=spend,
        budget=rules.budget_cents(row, limits),
        plan=plan,
        claims=claims,
    )


@router.put("/settings", response_model=SettingsView)
async def put_ai_settings(
    body: UpdateSettingsRequest,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> SettingsView:
    """Change the tier, the provider, the budget, or turn generation off.

    Refuses with 409 and the exact list when the change would route to a
    processor nobody has acknowledged. The list in the error is what the
    client shows in the dialog — so what the admin reads and what the
    router will do come from one place.
    """
    if not (_ADMIN_ROLES & set(claims.roles)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="only a workspace admin can change how meetings are processed",
        )

    state = get_state()
    processors = _required_processors()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await rules.fetch(conn, tenant_id=claims.tid)
        plan, limits = await _plan(conn, claims.tid)

        provider = body.provider or row.provider
        tier = body.tier or row.tier
        enabled = (
            row.generation_enabled if body.generation_enabled is None else body.generation_enabled
        )

        if tier == rules.PREMIUM and not rules.may_choose_premium(plan):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "plan_required",
                    "detail": "the premium tier is available on the Pro and Enterprise plans",
                    "plan": plan,
                },
            )

        offered = [p.model_dump() for p in body.acknowledge]
        missing = rules.missing_acknowledgement(row, processors, offered)
        # Only a change that REACHES a new processor needs acknowledging.
        # Turning generation off, or lowering a budget, never does.
        changing_routing = provider != row.provider or tier != row.tier
        if missing and (changing_routing or offered):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "processors_not_acknowledged",
                    "detail": "these processors have not been acknowledged for this workspace",
                    "processors": [{"name": p.name, "region": p.region} for p in missing],
                },
            )

        acknowledged = list(row.acknowledged or [])
        if offered:
            known = row.acknowledged_keys
            acknowledged += rules.stamp(
                [
                    rules.Processor(name=p["name"], region=p["region"])
                    for p in offered
                    if (p["name"].strip().casefold(), p["region"].strip().casefold()) not in known
                ],
                actor=claims.sub,
            )

        row = await rules.upsert(
            conn,
            tenant_id=claims.tid,
            provider=provider,
            tier=tier,
            generation_enabled=enabled,
            acknowledged=acknowledged,
            monthly_budget_cents=(
                body.monthly_budget_cents
                if body.monthly_budget_cents is not None
                else row.monthly_budget_cents
            ),
            updated_by=claims.sub,
        )
        spend = await rules.month_to_date_cents(conn, tenant_id=claims.tid)

    # The registry's cache would otherwise serve the old tier for a minute.
    source = getattr(state, "workspace_model_settings", None)
    if source is not None:
        source.invalidate(claims.tid)

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.AI_SETTINGS_CHANGED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="tenant",
        target_id=claims.tid,
        # Closed vocabulary and counts. Never a person's name, never a
        # processor's commercial terms.
        payload={
            "tier": row.tier,
            "provider": row.provider,
            "generation_enabled": row.generation_enabled,
            "acknowledged": len(row.acknowledged or []),
        },
        severity=Severity.INFO,
    )
    return _view(
        row,
        processors=processors,
        spend=spend,
        budget=rules.budget_cents(row, limits),
        plan=plan,
        claims=claims,
    )
