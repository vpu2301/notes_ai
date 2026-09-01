#!/usr/bin/env python3
"""Seed the dev database with sample + system content (``make seed``).

Four idempotent passes, in order:

1. ``seed.sql`` — dev tenants, users, memberships, branding (must match
   infra/keycloak/realm-export.json; see the comments in the SQL file).
2. System note templates — every JSON file in ``infra/seeds/templates/``
   is upserted via the ``upsert_system_template()`` SQL function
   (migration 0008). The JSON is the authoritative, PR-reviewable copy.
3. Voice commands — ``infra/postgres/seed/voice_commands_<lang>.json``
   fixtures. The seeder DELETEs a language before re-inserting it, so
   removed commands disappear on re-seed.
4. Autocomplete starter corpus — a small English business phrase +
   snippet set (system scope) so /autocomplete/suggest has something to
   serve on a fresh stack. ON CONFLICT DO NOTHING.

Connects as the DB superuser (dev stack), which bypasses RLS — the
system-scope rows (tenant_id IS NULL) are exactly the rows app_role can
never write.

Usage::

    python scripts/seed/seed.py
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

# ── Autocomplete starter corpus (system scope, English) ──────────────
# Shape mirrors autocomplete_phrases: (phrase, specialty, section_hint).
# Phrases are ≤ 80 chars (DB CHECK) and carry no personal data.
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
        # The JSONB schema (libs/template_models) calls the browse facet
        # `specialty`; the DB column is the generic `category`.
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
        # Clean slate for this language so re-seeds drop removed commands.
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


async def main() -> int:
    print(f"Seeding {DB_NAME} on {DB_HOST}:{DB_PORT}…")
    conn = await asyncpg.connect(DSN)
    try:
        await _run_seed_sql(conn)
        await _seed_templates(conn)
        await _seed_voice_commands(conn)
        await _seed_autocomplete(conn)
    finally:
        await conn.close()
    print("Seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
