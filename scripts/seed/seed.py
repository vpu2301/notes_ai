#!/usr/bin/env python3
"""Seed the dev database (``make seed``): seed.sql (tenants, users, memberships), system
templates from infra/seeds/templates/, voice commands, the autocomplete starter corpus.
Idempotent; connects as the superuser because system-scope rows are what app_role can never write.

    DATABASE_URL=postgresql://... python scripts/seed/seed.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_SQL = Path(__file__).parent / "seed.sql"
TEMPLATES_DIR = REPO_ROOT / "infra" / "seeds" / "templates"
VOICE_COMMANDS_DIR = REPO_ROOT / "infra" / "postgres" / "seed"

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_NAME = os.getenv("POSTGRES_DB", "notes")
DSN = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
)

# Autocomplete starter corpus: (phrase, specialty, section_hint), <= 80 chars
# (DB CHECK), no personal data.
STARTER_PHRASES: list[tuple[str, str, str]] = [
    # meetings / general
    ("Action items:", "meetings", "action_items"),
    ("Decision made:", "meetings", "decisions"),
    ("Next steps agreed:", "meetings", "action_items"),
    ("Follow up with the client by", "meetings", "action_items"),
    ("Attendees:", "meetings", "attendees"),
    ("Agenda for today:", "meetings", "agenda"),
    ("Key takeaways:", "meetings", "discussion"),
    ("Meeting adjourned at", "meetings", "discussion"),
    ("No objections were raised", "meetings", "decisions"),
    ("Agreed to revisit next quarter", "meetings", "decisions"),
    ("Owner to be confirmed", "meetings", "action_items"),
    ("Scheduled a follow-up call for", "meetings", "action_items"),
    ("Blocked by", "general", "risks"),
    ("Waiting on a response from", "general", "action_items"),
    ("Deadline moved to", "general", "next_steps"),
    # sales
    ("Sent the proposal to", "sales", "next_steps"),
    ("Budget approved for", "sales", "context"),
    ("Decision maker is", "sales", "contact"),
    ("The main objection was pricing", "sales", "objections"),
    ("Pricing discussion postponed until", "sales", "objections"),
    ("Requested a product demo", "sales", "next_steps"),
    ("Contract renewal is due in", "sales", "context"),
    # projects
    ("On track for the planned release", "projects", "status_summary"),
    ("At risk due to", "projects", "risks"),
    ("Shipped to production on", "projects", "progress"),
    ("Scope reduced to meet the deadline", "projects", "risks"),
    ("Dependencies resolved with the platform team", "projects", "progress"),
    # people / hiring
    ("Positive feedback from the team on", "people", "feedback"),
    ("Growth goal for this quarter:", "people", "growth"),
    ("Discussed career development plans", "people", "growth"),
    ("Recommend moving forward with the candidate", "hiring", "recommendation"),
]

# (trigger, expansion, cursor_position)
STARTER_SNIPPETS: list[tuple[str, str, int]] = [
    ("agenda", "Agenda:\n1. ", 11),
    ("actions", "Action items:\n- ", 16),
    ("decision", "Decision made: ", 15),
    ("next", "Next steps:\n- ", 14),
    ("summary", "Summary: ", 9),
]


async def _run_seed_sql(conn: asyncpg.Connection) -> None:
    print(f"-- seed.sql → {DB_NAME}")
    await conn.execute(SEED_SQL.read_text("utf-8"))


async def _seed_templates(conn: asyncpg.Connection) -> None:
    files = sorted(TEMPLATES_DIR.glob("*.json"))
    if not files:
        print(f"warn: no template files in {TEMPLATES_DIR}")
        return
    for path in files:
        doc = json.loads(path.read_text("utf-8"))
        # The JSONB schema calls the facet `specialty`; the DB column is `category`.
        category = doc.get("category") or doc["specialty"]
        row_id = await conn.fetchval(
            """
            SELECT upsert_system_template(
                $1::text, $2::text, $3::text, $4::text,
                $5::smallint, $6::jsonb
            )
            """,
            doc["code"],
            doc["name"],
            doc["language"],
            category,
            int(doc.get("schema_version", 1)),
            json.dumps(doc),
        )
        print(f"-- template {path.name} → {row_id}")


async def _seed_voice_commands(conn: asyncpg.Connection) -> None:
    for path in sorted(VOICE_COMMANDS_DIR.glob("voice_commands_*.json")):
        language = path.stem.split("_")[-1]
        commands = json.loads(path.read_text("utf-8"))
        # Re-seeds drop removed commands.
        await conn.execute("DELETE FROM voice_commands WHERE language = $1", language)
        for cmd in commands:
            await conn.execute(
                """
                INSERT INTO voice_commands
                    (intent, language, phrases,
                     requires_pause_before_ms, min_avg_probability,
                     is_section_command, is_option_command,
                     exact_match_only)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8)
                """,
                cmd["intent"],
                language,
                json.dumps(cmd["phrases"]),
                int(cmd.get("requires_pause_before_ms", 200)),
                float(cmd.get("min_avg_probability", 0.85)),
                bool(cmd.get("is_section_command", False)),
                bool(cmd.get("is_option_command", False)),
                bool(cmd.get("exact_match_only", False)),
            )
        print(f"-- voice commands {language}: {len(commands)}")


async def _seed_autocomplete(conn: asyncpg.Connection) -> None:
    inserted = 0
    for phrase, specialty, section_hint in STARTER_PHRASES:
        result = await conn.execute(
            """
            INSERT INTO autocomplete_phrases
                (tenant_id, owner_user_id, phrase, language, specialty,
                 section_hint, source, source_kind, source_ref, review_engine)
            VALUES (NULL, NULL, $1, 'en', $2, $3, 'system',
                    'seed', 'seed:scripts/seed/seed.py', 'human')
            ON CONFLICT DO NOTHING
            """,
            phrase,
            specialty,
            section_hint,
        )
        inserted += int(result.split()[-1])
    print(f"-- autocomplete phrases: {inserted} inserted ({len(STARTER_PHRASES)} in set)")

    inserted = 0
    for trigger, expansion, cursor in STARTER_SNIPPETS:
        result = await conn.execute(
            """
            INSERT INTO autocomplete_snippets
                (tenant_id, owner_user_id, trigger, expansion,
                 cursor_position, language, source)
            VALUES (NULL, NULL, $1, $2, $3, 'en', 'system')
            ON CONFLICT DO NOTHING
            """,
            trigger,
            expansion,
            cursor,
        )
        inserted += int(result.split()[-1])
    print(f"-- autocomplete snippets: {inserted} inserted ({len(STARTER_SNIPPETS)} in set)")


# The dev room device: seeded here, not in seed.sql, because the row stores a
# hash computed from the known dev secret (the realm's `room-device-demo`).
# Service credentials are deliberately NOT seeded (declared-but-unused clients).
DEV_DEVICE_TENANT = "00000000-0000-0000-0000-00000000000a"
DEV_DEVICE_ID = "0000000d-0000-0000-0000-00000000d0e1"
DEV_DEVICE_SECRET = "dev-room-device-secret"  # noqa: S105 — dev realm parity


async def _seed_dev_device(conn: asyncpg.Connection) -> None:
    import hashlib

    exists = await conn.fetchval("SELECT 1 FROM service_credentials WHERE id = $1", DEV_DEVICE_ID)
    if exists:
        print("-- dev room device: already present")
        return
    await conn.execute(
        """
        INSERT INTO service_credentials (id, kind, tenant_id, name, roles)
        VALUES ($1, 'device', $2, 'Demo meeting room', ARRAY['device'])
        ON CONFLICT (id) DO NOTHING
        """,
        DEV_DEVICE_ID,
        DEV_DEVICE_TENANT,
    )
    await conn.execute(
        """
        INSERT INTO service_credential_secrets (credential_id, secret_hash, secret_prefix)
        VALUES ($1, $2, 'devdemo0')
        ON CONFLICT (secret_hash) DO NOTHING
        """,
        DEV_DEVICE_ID,
        hashlib.sha256(DEV_DEVICE_SECRET.encode()).hexdigest(),
    )
    print(f"-- dev room device: {DEV_DEVICE_ID} (tenant A, secret in the runbook)")


# A workspace is only routed to a processor its admin acknowledged by (name,
# region); both dev processors are acknowledged for the seeded tenants so
# `make seed` writes notes either way. Real workspaces always see the dialog.
DEV_TENANTS = (
    "00000000-0000-0000-0000-00000000000a",
    "00000000-0000-0000-0000-00000000000b",
)
SEED_ACTOR = "0a000000-0000-0000-0000-00000000000a"  # admin@tenant-a


def _dev_processors() -> list[dict[str, str]]:
    """Every processor the dev routing can reach, from the registry itself (placeholder key),
    never typed: a list that can drift from the routing is the failure the Data page prevents.
    """
    sys.path.insert(0, str(REPO_ROOT / "libs" / "models" / "src"))
    from models import Registry

    environ = {**os.environ, "MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY") or "seed"}
    registry = Registry.load(
        REPO_ROOT / "config" / "models.yaml", env="dev", environ=environ, validate=False
    )
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for info in registry.processors_for_env():
        seen[(info.name.casefold(), info.region.casefold())] = {
            "name": info.name,
            "region": info.region,
        }
    return list(seen.values())


async def _seed_ai_processors(conn: asyncpg.Connection) -> None:
    from datetime import UTC, datetime

    try:
        processors = _dev_processors()
    except Exception as exc:  # noqa: BLE001 — a missing models.yaml is not a seed failure
        print(f"-- ai processors: skipped ({type(exc).__name__})")
        return
    if not processors:
        print("-- ai processors: nothing routed in dev")
        return
    when = datetime.now(UTC).isoformat()
    for tenant in DEV_TENANTS:
        row = await conn.fetchrow(
            "SELECT acknowledged_processors FROM workspace_model_settings WHERE tenant_id = $1",
            tenant,
        )
        current = row["acknowledged_processors"] if row else []
        current = json.loads(current) if isinstance(current, str) else list(current or [])
        known = {
            (str(p.get("name", "")).casefold(), str(p.get("region", "")).casefold())
            for p in current
        }
        added = [
            {**p, "acknowledged_by": SEED_ACTOR, "acknowledged_at": when}
            for p in processors
            if (p["name"].casefold(), p["region"].casefold()) not in known
        ]
        if not added and row:
            continue
        await conn.execute(
            """
            INSERT INTO workspace_model_settings
                (tenant_id, provider, tier, generation_enabled, acknowledged_processors, updated_by)
            VALUES ($1, 'platform', 'standard', true, $2::jsonb, $3)
            ON CONFLICT (tenant_id) DO UPDATE SET
                acknowledged_processors = EXCLUDED.acknowledged_processors,
                updated_by = EXCLUDED.updated_by
            """,
            tenant,
            json.dumps([*current, *added]),
            SEED_ACTOR,
        )
    names = ", ".join(f"{p['name']} ({p['region']})" for p in processors)
    print(f"-- ai processors acknowledged for the dev tenants: {names}")


async def main() -> int:
    print(f"Seeding {DB_NAME} on {DB_HOST}:{DB_PORT}…")
    conn = await asyncpg.connect(DSN)
    try:
        await _run_seed_sql(conn)
        await _seed_templates(conn)
        await _seed_voice_commands(conn)
        await _seed_autocomplete(conn)
        await _seed_dev_device(conn)
        await _seed_ai_processors(conn)
    finally:
        await conn.close()
    print("Seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
