"""Which model processes a workspace's meetings: the table behind
`Registry(settings_source=…)`. A workspace is only ever routed to a processor
its admin has acknowledged by name and region, and the list is computed from
the SAME registry that routes the calls. Reads are cached for a minute.
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

# Which plans may choose the premium tier.
PREMIUM_PLANS: Final[frozenset[str]] = frozenset({"pro", "enterprise"})

# Monthly AI budget when neither plan nor admin set one; capped on purpose.
DEFAULT_BUDGET_CENTS: Final = 2_000


@dataclass(frozen=True, slots=True)
class Processor:
    """One company that may process this workspace's meetings; identity is (name, region)."""

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
    """This workspace's settings, or the platform default (no row is normal)."""
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


# What each operation's processor does with the data, in words a customer can check against a DPA.
PURPOSES: Final[dict[str, str]] = {
    "transcribe": "turning your recordings into text",
    "summarize": "writing your meeting notes",
    "understand": "answering questions about a note",
    "embed": "search",
    "classify": "recognising what kind of recording it is",
    "title": "naming your notes",
    "entities": "correcting names in your notes",
}


def required_processors(registry: Any) -> list[Processor]:
    """Every processor a workspace on this environment can be routed to, read from
    the registry that routes the calls so a new route cannot appear without appearing here."""
    merged: dict[tuple[str, str], Processor] = {}
    for info, operation, tier in registry.processor_routes():
        name, region = (info.name or ""), (info.region or "")
        if not name:
            continue
        key = (name.casefold(), region.casefold())
        found = merged.get(key)
        purposes = set(found.purposes if found else ())
        tiers = set(found.tiers if found else ())
        purposes.add(PURPOSES.get(operation, operation))
        tiers.add(tier)
        merged[key] = Processor(
            name=name, region=region, purposes=tuple(sorted(purposes)), tiers=tuple(sorted(tiers))
        )
    return list(merged.values())


# ── The rules (pure) ────────────────────────────────────────────────


def budget_cents(row: SettingsRow, plan_limits: dict[str, Any] | None) -> int:
    """The workspace's own cap, else the plan's, else the platform default."""
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
    """Processors this change would introduce that nobody has agreed to; empty means allowed."""
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
    """``(provider, tier, processors not acknowledged)``: what this workspace ACTUALLY
    resolves to. A routing change to an unacknowledged processor falls back to platform/standard."""
    unacknowledged = missing_acknowledgement(row, required, None)
    if unacknowledged:
        return PLATFORM, STANDARD, unacknowledged
    return row.provider, row.tier, []


# ── The registry's settings source ──────────────────────────────────


class WorkspaceSettings:
    """A `SettingsSource` backed by the table, cached for a minute (`resolve()` runs per model call)."""

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
        # Nothing cached and no way to await: the platform default is the safe direction.
        return hit[1] if hit else WorkspaceModelSettings()

    async def refresh(self, tenant_id: UUID) -> WorkspaceModelSettings:
        """Read the table and cache it. Called before a generation runs."""
        from db import tenant_connection

        try:
            async with tenant_connection(self._pool, tenant_id) as conn:
                row = await fetch(conn, tenant_id=tenant_id)
            settings = row.as_model_settings()
        except Exception:  # noqa: BLE001
            # An unreadable table must not stop a note; the platform default is safe.
            logger.warning("ai_settings.unreadable", extra={"tenant": str(tenant_id)})
            row = SettingsRow(tenant_id=tenant_id)
            settings = WorkspaceModelSettings()
        self._cache[str(tenant_id)] = (time.monotonic(), settings)
        self._rows[str(tenant_id)] = row
        return settings

    def acknowledged(self, tenant_id: UUID) -> set[tuple[str, str]]:
        """What this workspace has agreed to, as of the last refresh; empty when nothing is cached."""
        row = self._rows.get(str(tenant_id))
        return row.acknowledged_keys if row else set()

    def invalidate(self, tenant_id: UUID) -> None:
        self._cache.pop(str(tenant_id), None)
        self._rows.pop(str(tenant_id), None)
