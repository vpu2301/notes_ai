"""0016 list badge — search hits carry who can open each note (RUN_DB_INTEGRATION=1).

The notes list shows Private / Shared with N / Workspace / Public on
hover; all four states come from one search query, so this pins that
query's `visibility`, `shared_with_count` and `has_public_link` columns,
including a revoked or expired link no longer counting as public.

Needs `make dev-up && make migrate-up && make seed` (tenants, templates).
"""

from __future__ import annotations

import json
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from db import create_pool, tenant_connection

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1; needs dev-up + migrate-up + seed",
)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("POSTGRES_DB", "notes")
SU_DSN = f"postgresql://postgres:postgres@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"
APP_DSN = f"postgresql://app_role:app_role@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"

TENANT_A = UUID("00000000-0000-0000-0000-00000000000a")
MARK = "itest-access"


async def _seed_note(
    su: asyncpg.Connection, *, visibility: str, shared_with: list[UUID]
) -> tuple[UUID, UUID]:
    """Minimal note + current version. Returns (note_id, author_sub)."""
    member = await su.fetchval("SELECT sub FROM users WHERE tenant_id=$1 LIMIT 1", TENANT_A)
    template_id = await su.fetchval("SELECT id FROM templates LIMIT 1")
    assert member and template_id, "run `make seed` first"
    note_id, version_id = uuid4(), uuid4()
    await su.execute(
        "INSERT INTO notes (id, tenant_id, code, title, status, template_id,"
        " primary_author_id, co_author_ids, visibility, shared_with_ids)"
        " VALUES ($1,$2,$3,$4,'draft',$5,$6,'{}',$7::note_visibility,$8)",
        note_id,
        TENANT_A,
        f"{MARK}-{str(note_id)[:8]}",
        f"{MARK} note",
        template_id,
        member,
        visibility,
        shared_with,
    )
    content = {"template_id": str(template_id), "sections": []}
    await su.execute(
        "INSERT INTO note_versions (id, note_id, version_number, created_by,"
        " content_jsonb, rendered_text)"
        " VALUES ($1,$2,1,$3,$4,$5)",
        version_id,
        note_id,
        member,
        json.dumps(content),
        MARK,
    )
    await su.execute("UPDATE notes SET current_version_id=$2 WHERE id=$1", note_id, version_id)
    return note_id, member


async def _link(
    su: asyncpg.Connection,
    note_id: UUID,
    author: UUID,
    *,
    revoked: bool = False,
    expired: bool = False,
) -> None:
    await su.execute(
        "INSERT INTO note_share_links (tenant_id, note_id, token_hash, created_by,"
        " expires_at, revoked_at)"
        " VALUES ($1,$2,$3,$4,"
        " CASE WHEN $5 THEN now() - interval '1 day' END,"
        " CASE WHEN $6 THEN now() END)",
        TENANT_A,
        note_id,
        f"{MARK}-{uuid4().hex}",
        author,
        expired,
        revoked,
    )


async def test_search_hits_carry_sharing_state():
    from note_service.domain import search as searchmod

    su = await asyncpg.connect(SU_DSN)
    pool = await create_pool(APP_DSN, application_name=MARK, min_size=1, max_size=2)
    try:
        private, author = await _seed_note(su, visibility="private", shared_with=[])
        shared, _ = await _seed_note(su, visibility="private", shared_with=[uuid4(), uuid4()])
        workspace, _ = await _seed_note(su, visibility="workspace", shared_with=[])
        public, _ = await _seed_note(su, visibility="private", shared_with=[])
        await _link(su, public, author)
        revoked, _ = await _seed_note(su, visibility="private", shared_with=[])
        await _link(su, revoked, author, revoked=True)
        expired, _ = await _seed_note(su, visibility="private", shared_with=[])
        await _link(su, expired, author, expired=True)

        # No viewer: the access clause is not what is under test.
        filters = searchmod.SearchFilters(q=MARK)
        async with tenant_connection(pool, TENANT_A) as conn:
            hits, _, _ = await searchmod.search_notes(conn, filters=filters, limit=200, cursor=None)
        by_id = {h.note_id: h for h in hits}

        state = {
            name: (by_id[nid].visibility, by_id[nid].shared_with_count, by_id[nid].has_public_link)
            for name, nid in {
                "private": private,
                "shared": shared,
                "workspace": workspace,
                "public": public,
                "revoked": revoked,
                "expired": expired,
            }.items()
        }
        assert state == {
            "private": ("private", 0, False),
            "shared": ("private", 2, False),
            "workspace": ("workspace", 0, False),
            "public": ("private", 0, True),
            "revoked": ("private", 0, False),
            "expired": ("private", 0, False),
        }
    finally:
        notes = "SELECT id FROM notes WHERE title LIKE $1"
        await su.execute(f"DELETE FROM note_share_links WHERE note_id IN ({notes})", f"{MARK}%")
        await su.execute("UPDATE notes SET current_version_id=NULL WHERE title LIKE $1", f"{MARK}%")
        await su.execute(f"DELETE FROM note_versions WHERE note_id IN ({notes})", f"{MARK}%")
        await su.execute("DELETE FROM notes WHERE title LIKE $1", f"{MARK}%")
        await su.close()
        await pool.close()
