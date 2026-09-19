"""The workspace's say over how notes leave it (Sprint 23, migration 0041).

Stored as JSON on the tenant row and validated here; `{}` is every
default, so a workspace that never opened the settings page behaves
exactly as before this sprint. Read on a tenant-scoped connection
(`tenants_self_select`) and cached in-process for a minute — the
acceptance bar is "visible within a minute", and a cross-instance
pub/sub for a value that changes a few times a year is not worth a
channel. Written through the SECURITY DEFINER helper, since app_role may
only SELECT `tenants`.

The one rule with a plan attached (G-1): only a paid workspace may turn
the page's product line off. The header is the price of the free tier.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

PAID_PLANS = frozenset({"pro", "enterprise"})
_TTL_SECONDS = 60.0


class SharingPolicy(BaseModel):
    # `ignore`, not `forbid`: rows written before a key was retired
    # (`require_finalized`, 0042) must still load.
    model_config = ConfigDict(extra="ignore")

    external_links_enabled: bool = True
    public_links_enabled: bool = True
    # Requests above are clipped, not refused.
    max_link_days: int = Field(default=180, ge=1, le=365)
    verified_recipients_required: bool = False
    product_email_enabled: bool = True
    cta_enabled: bool = True
    # Set by the abuse guard, cleared by an admin re-enabling mail.
    auto_disabled_reason: Literal["abuse_reports"] | None = None


class Constraints(BaseModel):
    """What a member's client needs to know — the effective rules, no
    admin-only detail."""

    model_config = ConfigDict(extra="forbid")

    external_links_enabled: bool
    public_links_enabled: bool
    max_link_days: int
    product_email_enabled: bool
    verified_recipients_required: bool


def constraints_of(policy: SharingPolicy) -> Constraints:
    return Constraints(
        external_links_enabled=policy.external_links_enabled,
        public_links_enabled=policy.public_links_enabled,
        max_link_days=policy.max_link_days,
        product_email_enabled=policy.product_email_enabled,
        verified_recipients_required=policy.verified_recipients_required,
    )


def cta_shown(policy: SharingPolicy, plan: str) -> bool:
    """G-1: free and legacy workspaces always carry the product line."""
    return policy.cta_enabled or plan not in PAID_PLANS


_cache: dict[UUID, tuple[float, SharingPolicy, str]] = {}


def invalidate(tenant_id: UUID) -> None:
    _cache.pop(tenant_id, None)


def _parse(raw: Any) -> SharingPolicy:
    if isinstance(raw, str | bytes):
        raw = json.loads(raw or "{}")
    try:
        return SharingPolicy.model_validate(raw or {})
    except Exception:  # noqa: BLE001 — a malformed row must not take sharing down
        return SharingPolicy()


async def load_policy(conn: asyncpg.Connection, *, tenant_id: UUID) -> tuple[SharingPolicy, str]:
    """(policy, plan) for the connection's tenant, cached for a minute."""
    hit = _cache.get(tenant_id)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2]
    row = await conn.fetchrow("SELECT sharing_policy, plan FROM tenants WHERE id = $1", tenant_id)
    policy = _parse(row["sharing_policy"]) if row else SharingPolicy()
    plan = str(row["plan"]) if row else "legacy"
    _cache[tenant_id] = (time.monotonic() + _TTL_SECONDS, policy, plan)
    return policy, plan


async def save_policy(conn: asyncpg.Connection, *, tenant_id: UUID, policy: SharingPolicy) -> None:
    await conn.execute(
        "SELECT public.set_tenant_sharing_policy($1, $2::jsonb)",
        tenant_id,
        json.dumps(policy.model_dump(mode="json")),
    )
    invalidate(tenant_id)


def changed_keys(before: SharingPolicy, after: SharingPolicy) -> list[str]:
    a, b = before.model_dump(), after.model_dump()
    return sorted(k for k in a if a[k] != b[k])
