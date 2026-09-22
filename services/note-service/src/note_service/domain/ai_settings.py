"""Which model processes a workspace's meetings, and who they agreed to.

`libs/models` always had the seam — `Registry(settings_source=…)` — and
until now it was a constant returning `platform/standard` for everyone.
This is the table behind it, plus the one rule that makes the Data page
worth having:

    **A workspace is only ever routed to a processor its admin has
    acknowledged by name and region.**

The list an admin acknowledges is computed from the SAME registry object
that routes the calls (`processors_for_env()`), never from copy text. So
adding a backend to `config/models.yaml` cannot quietly put a new
processor in somebody's data path: until an admin acknowledges it, that
workspace keeps resolving to what it had. A disclosure page that can
drift from reality is worse than none, because people believe it.

Reads are cached for a minute: `resolve()` runs once per model call and a
per-call SELECT would put the settings table on the hot path of every
generation.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import asyncpg

from models import WorkspaceModelSettings

logger = logging.getLogger(__name__)

CACHE_SECONDS: Final = 60.0

PLATFORM: Final = "platform"
STANDARD: Final = "standard"
PREMIUM: Final = "premium"

# Which plans may choose the premium tier. Pricing itself is out of scope
# — this is only "who is allowed to ask".
PREMIUM_PLANS: Final[frozenset[str]] = frozenset({"pro", "enterprise"})

# What a workspace may spend on AI in a month when its plan says nothing
# and nobody set a budget. Deliberately present rather than unlimited: a
# runaway loop should cost a capped amount and say so.
DEFAULT_BUDGET_CENTS: Final = 2_000


@dataclass(frozen=True, slots=True)
class Processor:
    """One company that may process this workspace's meetings.

    Identity is (name, region) and nothing else: a processor that moved
    region is a NEW processor, because the region is most of what a
    customer is agreeing to.
    """

    name: str
    region: str
    """What it does with the data — one entry per routed operation."""
    purposes: tuple[str, ...] = ()
    """Which tiers reach it."""
    tiers: tuple[str, ...] = ()

    @property
    def purpose(self) -> str:
        return ", ".join(self.purposes)

    def key(self) -> tuple[str, str]:
        return self.name.strip().casefold(), self.region.strip().casefold()


@dataclass(slots=True)
class SettingsRow:
    tenant_id: UUID
    provider: str = PLATFORM
    tier: str = STANDARD
    generation_enabled: bool = True
    acknowledged: list[dict[str, Any]] | None = None
    monthly_budget_cents: int | None = None
    updated_at: datetime | None = None

    @property
    def acknowledged_keys(self) -> set[tuple[str, str]]:
        return {
            (str(p.get("name", "")).strip().casefold(), str(p.get("region", "")).strip().casefold())
            for p in (self.acknowledged or [])
        }

    def as_model_settings(self) -> WorkspaceModelSettings:
        return WorkspaceModelSettings(provider=self.provider, tier=self.tier)  # type: ignore[arg-type]


DEFAULT = SettingsRow(tenant_id=UUID(int=0))


def _row(record: asyncpg.Record) -> SettingsRow:
    raw = record["acknowledged_processors"]
    return SettingsRow(
        tenant_id=record["tenant_id"],
        provider=str(record["provider"]),
        tier=str(record["tier"]),
        generation_enabled=bool(record["generation_enabled"]),
        acknowledged=json.loads(raw) if isinstance(raw, str) else (raw or []),
        monthly_budget_cents=record["monthly_budget_cents"],
        updated_at=record["updated_at"],
    )


_COLUMNS: Final = (
    "tenant_id, provider, tier, generation_enabled, acknowledged_processors, "
    "monthly_budget_cents, updated_at"
)


async def fetch(conn: asyncpg.Connection, *, tenant_id: UUID) -> SettingsRow:
    """This workspace's settings, or the platform default.

    A workspace with no row is not misconfigured — it is every workspace
    that has never opened the page.
    """
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM workspace_model_settings WHERE tenant_id = $1", tenant_id
    )
    return _row(record) if record is not None else SettingsRow(tenant_id=tenant_id)


async def upsert(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    provider: str,
    tier: str,
    generation_enabled: bool,
    acknowledged: list[dict[str, Any]],
    monthly_budget_cents: int | None,
    updated_by: UUID,
) -> SettingsRow:
    record = await conn.fetchrow(
        f"""
        INSERT INTO workspace_model_settings (
            tenant_id, provider, tier, generation_enabled,
            acknowledged_processors, monthly_budget_cents, updated_by
        )
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
        ON CONFLICT (tenant_id) DO UPDATE SET
            provider = EXCLUDED.provider,
            tier = EXCLUDED.tier,
            generation_enabled = EXCLUDED.generation_enabled,
            acknowledged_processors = EXCLUDED.acknowledged_processors,
            monthly_budget_cents = EXCLUDED.monthly_budget_cents,
            updated_by = EXCLUDED.updated_by
        RETURNING {_COLUMNS}
        """,
        tenant_id,
        provider,
        tier,
        generation_enabled,
        json.dumps(acknowledged),
        monthly_budget_cents,
        updated_by,
    )
    return _row(record)


async def month_to_date_cents(conn: asyncpg.Connection, *, tenant_id: UUID) -> int:
    """What this workspace has spent on models this month, in whole cents."""
    total = await conn.fetchval(
        """
        SELECT coalesce(sum(cost_cents_est), 0) FROM model_usage_monthly
        WHERE tenant_id = $1 AND month = date_trunc('month', now())
        """,
        tenant_id,
    )
    return int(total or 0)


# ── The rules (pure) ────────────────────────────────────────────────


def budget_cents(row: SettingsRow, plan_limits: dict[str, Any] | None) -> int:
    """The cap that applies: the workspace's own, else the plan's, else
    the platform default."""
    if row.monthly_budget_cents is not None:
        return row.monthly_budget_cents
    limit = (plan_limits or {}).get("ai_cents_per_month")
    try:
        return int(limit) if limit is not None else DEFAULT_BUDGET_CENTS
    except (TypeError, ValueError):
        return DEFAULT_BUDGET_CENTS


def may_choose_premium(plan: str | None) -> bool:
    return (plan or "").strip().casefold() in PREMIUM_PLANS


def missing_acknowledgement(
    row: SettingsRow, required: list[Processor], offered: list[dict[str, Any]] | None
) -> list[Processor]:
    """Processors this change would introduce that nobody has agreed to.

    An empty list means the change is allowed. Matching is on (name,
    region) — a processor that moved region is a NEW processor, because
    the region is most of what a customer is agreeing to.
    """
    agreed = row.acknowledged_keys | {
        (str(p.get("name", "")).strip().casefold(), str(p.get("region", "")).strip().casefold())
        for p in (offered or [])
    }
    return [p for p in required if p.key() not in agreed]


def stamp(
    processors: list[Processor], *, actor: UUID, now: datetime | None = None
) -> list[dict[str, Any]]:
    """The acknowledgement as it is stored: who agreed, and when."""
    when = (now or datetime.now(UTC)).isoformat()
    return [
        {
            "name": p.name,
            "region": p.region,
            "acknowledged_by": str(actor),
            "acknowledged_at": when,
        }
        for p in processors
    ]


def effective(row: SettingsRow, required: list[Processor]) -> tuple[str, str, list[Processor]]:
    """``(provider, tier, processors not acknowledged)`` — what this
    workspace ACTUALLY resolves to.

    This is the safety valve for a routing change. If `config/models.yaml`
    starts routing a tier to a processor this workspace never agreed to,
    the workspace does not silently follow: it falls back to
    platform/standard, and the page tells the admin why.
    """
    unacknowledged = missing_acknowledgement(row, required, None)
    if unacknowledged:
        return PLATFORM, STANDARD, unacknowledged
    return row.provider, row.tier, []


# ── The registry's settings source ──────────────────────────────────


class WorkspaceSettings:
    """A `SettingsSource` backed by the table, cached for a minute.

    `resolve()` runs once per model call; a SELECT per call would put
    this table on the hot path of every generation. A minute is short
    enough that a tier change takes effect while an admin is still
    looking at the page.
    """

    def __init__(self, pool: Any, *, ttl: float = CACHE_SECONDS) -> None:
        self._pool = pool
        self._ttl = ttl
        self._cache: dict[str, tuple[float, WorkspaceModelSettings]] = {}
        self._rows: dict[str, SettingsRow] = {}

    def cached(self, workspace_id: str) -> WorkspaceModelSettings:
        """The synchronous call the registry makes."""
        hit = self._cache.get(workspace_id)
        if hit is not None and (time.monotonic() - hit[0]) < self._ttl:
            return hit[1]
        # Nothing cached and no way to await here: answer with the
        # platform default and let `refresh` fill the cache. Defaulting
        # DOWN (standard, platform) is the safe direction — it can only
        # ever route to fewer processors than the workspace agreed to.
        return hit[1] if hit else WorkspaceModelSettings()

    async def refresh(self, tenant_id: UUID) -> WorkspaceModelSettings:
        """Read the table and cache it. Called before a generation runs."""
        from db import tenant_connection

        try:
            async with tenant_connection(self._pool, tenant_id) as conn:
                row = await fetch(conn, tenant_id=tenant_id)
            settings = row.as_model_settings()
        except Exception:  # noqa: BLE001
            # The settings table being unreadable must not stop a note
            # being written; the platform default is always safe.
            logger.warning("ai_settings.unreadable", extra={"tenant": str(tenant_id)})
            row = SettingsRow(tenant_id=tenant_id)
            settings = WorkspaceModelSettings()
        self._cache[str(tenant_id)] = (time.monotonic(), settings)
        self._rows[str(tenant_id)] = row
        return settings

    def acknowledged(self, tenant_id: UUID) -> set[tuple[str, str]]:
        """What this workspace has agreed to, as of the last refresh.

        Empty when nothing is cached — which is the safe answer: it can
        only ever withhold a processor, never introduce one.
        """
        row = self._rows.get(str(tenant_id))
        return row.acknowledged_keys if row else set()

    def invalidate(self, tenant_id: UUID) -> None:
        self._cache.pop(str(tenant_id), None)
        self._rows.pop(str(tenant_id), None)
