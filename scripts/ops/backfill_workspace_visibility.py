#!/usr/bin/env python3
"""W5: a team workspace shares by default — also the notes written before W3.

Every live ``private`` note in a team workspace whose visibility nobody chose becomes
``workspace``, except person-centred notes (1:1, interview, voice memo — the
`visibility.is_sensitive` rule) and notes whose author once made them private (an
audited ``note.visibility_changed → private``; those are marked ``author`` and never
looked at again). Each change is a product action: ``visibility_source='backfill'``,
one audit row per note, one notice per author. Personal workspaces are never changed;
a workspace-visible note found there is reported.

Dry run by default. Idempotent: only ``visibility_source='default'`` notes are candidates.

    DB_APP_ROLE_DSN=... DB_AUDIT_WRITER_DSN=... REDIS_URL=... \\
      uv run --project services/note-service python scripts/ops/backfill_workspace_visibility.py \\
      [--tenant <uuid> | --all-tenants] [--apply]

In production (``MDX_ENV=prod``) it refuses to run without ``--tenant`` unless
``--all-tenants`` is given: roll one workspace at a time and watch the lock rate.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import asyncpg

from audit import AuditWriter, Severity
from db import tenant_connection
from note_service import audit_kinds
from note_service.collaboration_metrics import visibility_backfill
from note_service.domain import notes_repository as repo
from note_service.domain import sharing_policy
from note_service.domain.visibility import is_sensitive

BATCH = 500
PAUSE_S = 0.15
REASON = "backfill_w5"


@dataclass(slots=True)
class Plan:
    change: list[tuple[UUID, UUID]] = field(default_factory=list)  # (note_id, author)
    sensitive: list[UUID] = field(default_factory=list)
    author_choice: list[UUID] = field(default_factory=list)


def classify(rows: list[Any], author_chose_private: set[str]) -> Plan:
    """The per-note rule, pure: ``rows`` are candidates (live, private, source default)."""
    plan = Plan()
    for r in rows:
        if is_sensitive(
            meeting_type=r["meeting_type"],
            meeting_type_detected=r["meeting_type_detected"],
            template_code=r["template_code"],
        ):
            plan.sensitive.append(r["id"])
        elif str(r["id"]) in author_chose_private:
            plan.author_choice.append(r["id"])
        else:
            plan.change.append((r["id"], r["primary_author_id"]))
    return plan


_CANDIDATES = """
    SELECT n.id, n.primary_author_id, m.meeting_type, m.meeting_type_detected,
           t.code AS template_code
      FROM notes n
      LEFT JOIN note_meetings m ON m.note_id = n.id
      LEFT JOIN templates t ON t.id = n.template_id
     WHERE n.deleted_at IS NULL AND n.visibility = 'private'
       AND n.visibility_source = 'default'
"""


async def _author_choices(audit_pool: asyncpg.Pool, tenant_id: UUID) -> set[str]:
    async with tenant_connection(audit_pool, tenant_id) as conn:  # audit.events is RLS-scoped
        rows = await conn.fetch(
            "SELECT DISTINCT target_id FROM audit.events"
            " WHERE tenant_id = $1 AND kind = $2 AND payload_jcs->'payload'->>'to' = 'private'",
            tenant_id,
            audit_kinds.NOTE_VISIBILITY_CHANGED,
        )
    return {str(r["target_id"]) for r in rows}


async def _apply(
    pool: asyncpg.Pool, writer: AuditWriter, tenant_id: UUID, plan: Plan
) -> Counter[UUID]:
    """Writes in batches; returns changed notes per author."""
    for start in range(0, len(plan.author_choice), BATCH):
        async with tenant_connection(pool, tenant_id) as conn:
            for note_id in plan.author_choice[start : start + BATCH]:
                await repo.set_visibility_source(conn, note_id=note_id, source="author")
    per_author: Counter[UUID] = Counter()
    for start in range(0, len(plan.change), BATCH):
        batch = plan.change[start : start + BATCH]
        async with tenant_connection(pool, tenant_id) as conn:
            for note_id, _author in batch:
                await repo.set_visibility(
                    conn, note_id=note_id, visibility="workspace", source="backfill"
                )
        for note_id, author in batch:
            await writer.write_event(
                tenant_id=tenant_id,
                kind=audit_kinds.NOTE_VISIBILITY_CHANGED,
                actor_sub=None,
                actor_role="ops",
                target_kind="note",
                target_id=note_id,
                payload={
                    "from": "private",
                    "to": "workspace",
                    "reason": REASON,
                    "source": "backfill",
                },
                severity=Severity.INFO,
            )
            per_author[author] += 1
        await asyncio.sleep(PAUSE_S)
    return per_author


async def run(
    *,
    pool: asyncpg.Pool,
    audit_pool: asyncpg.Pool,
    redis: Any,
    only: UUID | None,
    apply: bool,
) -> dict[UUID, dict[str, int]]:
    """Per workspace: candidates / skipped_sensitive / skipped_author_choice / personal_violations."""
    from note_service.notifications import emit_workspace_notes_shared

    if only is not None:
        tenants = [only]
    else:
        async with pool.acquire() as conn:
            tenants = [r["id"] for r in await conn.fetch("SELECT public.active_tenant_ids() AS id")]
    writer = AuditWriter(audit_pool)
    report: dict[UUID, dict[str, int]] = {}
    for tenant_id in tenants:
        async with tenant_connection(pool, tenant_id) as conn:
            kind = await sharing_policy.tenant_kind(conn, tenant_id=tenant_id)
            if kind != "team":
                # The invariant: nothing in Personal is workspace-visible. Reported, never fixed here.
                violations = await conn.fetchval(
                    "SELECT count(*) FROM notes WHERE deleted_at IS NULL AND visibility = 'workspace'"
                )
                report[tenant_id] = {"personal_violations": int(violations or 0)}
                continue
            rows = await conn.fetch(_CANDIDATES)
        plan = classify(rows, await _author_choices(audit_pool, tenant_id))
        report[tenant_id] = {
            "candidates": len(plan.change),
            "skipped_sensitive": len(plan.sensitive),
            "skipped_author_choice": len(plan.author_choice),
        }
        if not apply:
            continue
        per_author = await _apply(pool, writer, tenant_id, plan)
        visibility_backfill.add(len(plan.change), {"outcome": "changed"})
        visibility_backfill.add(len(plan.sensitive), {"outcome": "sensitive"})
        visibility_backfill.add(len(plan.author_choice), {"outcome": "author_choice"})
        for author, count in per_author.items():
            await emit_workspace_notes_shared(
                redis, tenant_id=tenant_id, author_sub=author, count=count
            )
    return report


async def main(args: argparse.Namespace) -> int:
    if os.environ.get("MDX_ENV") == "prod" and args.tenant is None and not args.all_tenants:
        print("production: pass --tenant <uuid> (or --all-tenants deliberately)", file=sys.stderr)
        return 2
    dsn, audit_dsn = os.environ.get("DB_APP_ROLE_DSN"), os.environ.get("DB_AUDIT_WRITER_DSN")
    if not dsn or not audit_dsn:
        print("DB_APP_ROLE_DSN and DB_AUDIT_WRITER_DSN must be set", file=sys.stderr)
        return 2
    from redis.asyncio import Redis

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    audit_pool = await asyncpg.create_pool(audit_dsn, min_size=1, max_size=2)
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    try:
        report = await run(
            pool=pool, audit_pool=audit_pool, redis=redis, only=args.tenant, apply=args.apply
        )
    finally:
        await pool.close()
        await audit_pool.close()
        await redis.aclose()
    mode = "applied" if args.apply else "dry run"
    for tenant_id, counts in report.items():
        print(f"{mode} {tenant_id}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tenant", type=UUID, default=None)
    ap.add_argument("--all-tenants", action="store_true")
    ap.add_argument("--apply", action="store_true", help="write; without it, print counts only")
    sys.exit(asyncio.run(main(ap.parse_args())))
