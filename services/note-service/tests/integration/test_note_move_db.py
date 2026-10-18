"""W5 against Postgres (RUN_DB_INTEGRATION=1): `move_note_to_workspace` moves every row it
names, refuses without changing anything, leaves a stub, queues the re-home; copy makes a
fresh note; the SQL family rule equals the Python one. Builds its own workspaces and
deletes them afterwards; point POSTGRES_PORT at a disposable database, not the dev one.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from db import create_pool, tenant_connection
from note_service.domain import note_move, visibility
from note_service.domain import notes_repository as repo

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1; needs a migrated database",
)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("POSTGRES_DB", "notes")
SU_DSN = f"postgresql://postgres:postgres@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"
APP_DSN = f"postgresql://app_role:app_role@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"

# Every table the function writes, for the before/after checksum of a refusal.
TABLES = (
    "notes",
    "note_meetings",
    "note_collaborators",
    "note_comments",
    "note_share_links",
    "share_link_responses",
    "note_space_items",
    "note_carried_items",
    "note_relocations",
    "transcription_jobs",
    "audio_files",
    "transcription_speaker_edits",
    "transcript_corrections",
    "jobs",
)


class World:
    """Three workspaces and four people: author (A owner, B member), colleague (A member),
    stranger (B member), admin (A admin). P is the author's personal workspace, X archived."""

    def __init__(self) -> None:
        self.a, self.b, self.p, self.x = uuid4(), uuid4(), uuid4(), uuid4()
        self.author, self.colleague, self.stranger, self.admin = uuid4(), uuid4(), uuid4(), uuid4()
        self.template = uuid4()
        self.custom_template = uuid4()


async def _build(su: asyncpg.Connection, w: World) -> None:
    for tid, kind, status in (
        (w.a, "team", "active"),
        (w.b, "team", "active"),
        (w.p, "personal", "active"),
        (w.x, "team", "archived"),
    ):
        await su.execute(
            "INSERT INTO tenants (id, name, display_name, kind, status, is_active)"
            " VALUES ($1, $2, $2, $3, $4, $5)",
            tid,
            f"w5-{tid.hex[:6]}",
            kind,
            status,
            status == "active",
        )
    for sub in (w.author, w.colleague, w.stranger, w.admin):
        await su.execute(
            "INSERT INTO identities (id, email, display_name) VALUES ($1, $2, 'P')",
            sub,
            f"w5-{sub}@example.test",
        )
    for tid, sub, role in (
        (w.a, w.author, "owner"),
        (w.a, w.colleague, "member"),
        (w.a, w.admin, "admin"),
        (w.b, w.author, "member"),
        (w.b, w.stranger, "member"),
        (w.p, w.author, "owner"),
        (w.x, w.author, "owner"),
    ):
        await su.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_sub, role) VALUES ($1, $2, $3)",
            tid,
            sub,
            role,
        )
    await su.execute(
        "INSERT INTO templates (id, tenant_id, code, name, language, category, schema_jsonb)"
        " VALUES ($1, NULL, $2, 'Client call', 'en', 'meetings', '{\"version\":\"1\"}'),"
        "        ($3, $4, $5, 'Ours', 'en', 'meetings', '{\"version\":\"1\"}')",
        w.template,
        f"client_call_w5_{w.a.hex[:6]}",
        w.custom_template,
        w.a,
        f"custom_w5_{w.a.hex[:6]}",
    )


async def _teardown(su: asyncpg.Connection, w: World) -> None:
    tenants = [w.a, w.b, w.p, w.x]
    await su.execute("SET session_replication_role = replica")  # FKs off for cleanup only
    for table in (*TABLES, "note_versions", "note_spaces", "tenant_memberships", "templates"):
        if table == "note_versions":
            await su.execute(
                "DELETE FROM note_versions WHERE note_id IN"
                " (SELECT id FROM notes WHERE tenant_id = ANY($1))",
                tenants,
            )
        else:
            await su.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1)", tenants)  # noqa: S608
    await su.execute("DELETE FROM note_code_counters WHERE tenant_id = ANY($1)", tenants)
    await su.execute("DELETE FROM tenants WHERE id = ANY($1)", tenants)
    await su.execute(
        "DELETE FROM identities WHERE id = ANY($1)", [w.author, w.colleague, w.stranger, w.admin]
    )
    await su.execute("SET session_replication_role = origin")


async def _note(
    su: asyncpg.Connection,
    w: World,
    *,
    tenant: UUID | None = None,
    template: UUID | None = None,
    meeting_type: str | None = "client",
    detected: str | None = None,
    visibility_value: str = "workspace",
    source: str = "default",
    with_media: bool = False,
    job: UUID | None = None,
) -> UUID:
    """A live note with a version; optionally a meeting, a job, audio and their overlays."""
    tenant = tenant or w.a
    note_id, version_id = uuid4(), uuid4()
    await su.execute(
        "INSERT INTO notes (id, tenant_id, code, title, status, template_id, primary_author_id,"
        " visibility, visibility_source)"
        " VALUES ($1,$2,$3,'w5','draft',$4,$5,$6::note_visibility,$7)",
        note_id,
        tenant,
        f"W5-{note_id.hex[:8]}",
        template or w.template,
        w.author,
        visibility_value,
        source,
    )
    await su.execute(
        "INSERT INTO note_versions (id, note_id, version_number, created_by, content_jsonb,"
        " rendered_text) VALUES ($1,$2,1,$3,$4::jsonb,'body')",
        version_id,
        note_id,
        w.author,
        json.dumps(
            {
                "template_id": str(template or w.template),
                "template_schema_version": 1,
                "title": "w5",
                "sections": [
                    {
                        "section_key": "summary",
                        "text": "We agreed.",
                        "transcript_segment_ids": [str(uuid4())],
                    }
                ],
            }
        ),
    )
    await su.execute("UPDATE notes SET current_version_id = $1 WHERE id = $2", version_id, note_id)
    if with_media and job is None:
        audio, job = uuid4(), uuid4()
        await su.execute(
            "INSERT INTO audio_files (id, tenant_id, uploader_sub, mime_type, size_bytes, sha256,"
            " envelope_metadata, storage_uri) VALUES ($1,$2,$3,'audio/ogg',1,'\\x00','{}',$4)",
            audio,
            tenant,
            w.author,
            f"minio://audio/{tenant}/{audio}.enc",
        )
        await su.execute(
            "INSERT INTO transcription_jobs (id, tenant_id, audio_id, requester_sub, language,"
            " status, result_storage_uri) VALUES ($1,$2,$3,$4,'en','complete',$5)",
            job,
            tenant,
            audio,
            w.author,
            f"minio://transcripts/{tenant}/{job}.json.enc",
        )
        await su.execute(
            "INSERT INTO transcription_speaker_edits (tenant_id, job_id, seq, kind, from_label,"
            " to_label, actor_sub) VALUES ($1,$2,1,'merge','SPEAKER_2','SPEAKER_1',$3)",
            tenant,
            job,
            w.author,
        )
        await su.execute(
            "INSERT INTO transcript_corrections (tenant_id, job_id, kind, from_forms, to_text,"
            " occurrences, source, confidence, status) VALUES"
            " ($1,$2,'entity','{Acmee}','Acme','[]','user',1,'accepted')",
            tenant,
            job,
        )
    if meeting_type is not None:
        await su.execute(
            "INSERT INTO note_meetings (note_id, tenant_id, created_by, state, client_capture_id,"
            " meeting_type, meeting_type_detected, started_at, asr_job_id)"
            " VALUES ($1,$2,$3,'ready',$4,$5,$6,now(),$7)",
            note_id,
            tenant,
            w.author,
            uuid4(),
            meeting_type,
            detected,
            job,
        )
    return note_id


async def _checksum(su: asyncpg.Connection, w: World) -> str:
    parts = []
    for table in TABLES:
        parts.append(
            await su.fetchval(
                f"SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), ''))"  # noqa: S608
                f" FROM {table} t WHERE tenant_id = ANY($1)",
                [w.a, w.b, w.p, w.x],
            )
        )
    return "".join(parts)


@pytest_asyncio.fixture
async def env() -> AsyncIterator[tuple[asyncpg.Connection, asyncpg.Pool, World]]:
    su = await asyncpg.connect(SU_DSN)
    pool = await create_pool(APP_DSN, application_name="w5-itest", min_size=1, max_size=4)
    w = World()
    await _build(su, w)
    try:
        yield su, pool, w
    finally:
        await _teardown(su, w)
        await pool.close()
        await su.close()


async def _fetch(pool: asyncpg.Pool, tenant: UUID, note_id: UUID) -> repo.NoteRow:
    async with tenant_connection(pool, tenant) as conn:
        note = await repo.fetch_note(conn, note_id=note_id)
    assert note is not None
    return note


async def _count(su: asyncpg.Connection, table: str, column: str, value: UUID, tenant: UUID) -> int:
    return int(
        await su.fetchval(
            f"SELECT count(*) FROM {table} WHERE {column} = $1 AND tenant_id = $2",  # noqa: S608
            value,
            tenant,
        )
    )


@pytest.mark.asyncio
async def test_a_move_takes_the_whole_note_and_leaves_a_stub(env) -> None:  # noqa: ANN001
    su, pool, w = env
    note_id = await _note(su, w, with_media=True)
    job = await su.fetchval("SELECT asr_job_id FROM note_meetings WHERE note_id = $1", note_id)
    audio = await su.fetchval("SELECT audio_id FROM transcription_jobs WHERE id = $1", job)
    # Colleague is not in B (pruned); stranger is (kept, though they joined B for other reasons).
    for sub in (w.colleague, w.stranger):
        await su.execute(
            "INSERT INTO note_collaborators (note_id, tenant_id, user_sub, role, granted_by)"
            " VALUES ($1,$2,$3,'view',$4)",
            note_id,
            w.a,
            sub,
            w.author,
        )
    await su.execute(
        "INSERT INTO note_comments (tenant_id, note_id, author_sub, anchor_kind, body)"
        " VALUES ($1,$2,$3,'note','ok')",
        w.a,
        note_id,
        w.author,
    )
    link = uuid4()
    await su.execute(
        "INSERT INTO note_share_links (id, tenant_id, note_id, token_hash, created_by, kind, label)"
        " VALUES ($1,$2,$3,$4,$5,'recipient','Tom')",
        link,
        w.a,
        note_id,
        f"h-{link}",
        w.author,
    )
    await su.execute(
        "INSERT INTO share_link_responses (tenant_id, note_id, link_id, kind, item_key)"
        " VALUES ($1,$2,$3,'confirm','k1')",
        w.a,
        note_id,
        link,
    )
    space = await su.fetchval(
        "INSERT INTO note_spaces (tenant_id, user_sub, name) VALUES ($1,$2,'Clients') RETURNING id",
        w.a,
        w.author,
    )
    await su.execute(
        "INSERT INTO note_space_items (tenant_id, user_sub, note_id, space_id) VALUES ($1,$2,$3,$4)",
        w.a,
        w.author,
        note_id,
        space,
    )
    # A later meeting in A that carried this one's items forward.
    later = await _note(su, w)
    await su.execute(
        "UPDATE note_meetings SET previous_note_id = $1 WHERE note_id = $2", note_id, later
    )
    await su.execute(
        "INSERT INTO note_carried_items (tenant_id, note_id, from_note_id, item_key, state)"
        " VALUES ($1,$2,$3,'k1','open')",
        w.a,
        later,
        note_id,
    )

    note = await _fetch(pool, w.a, note_id)
    moved = await note_move.move(app_pool=pool, note=note, actor=w.author, to_tenant_id=w.b)

    assert moved.media_state == "rehoming" and moved.job_id == job and moved.audio_ids == [audio]
    assert moved.code.startswith("NOTE-")
    for table, column, value in (
        ("notes", "id", note_id),
        ("note_meetings", "note_id", note_id),
        ("note_comments", "note_id", note_id),
        ("note_share_links", "note_id", note_id),
        ("share_link_responses", "note_id", note_id),
        ("transcription_jobs", "id", job),
        ("audio_files", "id", audio),
        ("transcription_speaker_edits", "job_id", job),
        ("transcript_corrections", "job_id", job),
    ):
        assert await _count(su, table, column, value, w.a) == 0, table
        assert await _count(su, table, column, value, w.b) == 1, table
    collaborators = await su.fetch(
        "SELECT user_sub, tenant_id FROM note_collaborators WHERE note_id = $1", note_id
    )
    assert [(r["user_sub"], r["tenant_id"]) for r in collaborators] == [(w.stranger, w.b)]
    assert (
        await su.fetchval("SELECT count(*) FROM note_space_items WHERE note_id = $1", note_id) == 0
    )
    assert (
        await su.fetchval(
            "SELECT count(*) FROM note_carried_items WHERE from_note_id = $1", note_id
        )
        == 0
    )
    assert (
        await su.fetchval("SELECT previous_note_id FROM note_meetings WHERE note_id = $1", later)
        is None
    )
    # The re-home job, queued in the same transaction under the target.
    job_row = await su.fetchrow(
        "SELECT tenant_id, payload FROM jobs WHERE kind = 'note.rehome_media'"
        " AND payload->>'note_id' = $1",
        str(note_id),
    )
    assert job_row["tenant_id"] == w.b
    # The stub in A, and the old link still resolves (to B now).
    stub = await su.fetchrow("SELECT * FROM note_relocations WHERE note_id = $1", note_id)
    assert stub["tenant_id"] == w.a and stub["to_tenant_id"] == w.b
    assert stub["was_workspace_visible"] is True
    assert set(stub["collaborator_subs"]) == {w.colleague, w.stranger}
    resolved = await su.fetchrow("SELECT * FROM resolve_note_share_link($1)", f"h-{link}")
    assert resolved["tenant_id"] == w.b
    # The transcript stays shut, even for the author, until the media is home.
    async with tenant_connection(pool, w.b) as conn:
        access = await conn.fetchrow(
            "SELECT * FROM note_access_for_job($1, $2, $3)", job, w.author, ["member"]
        )
    assert access["level"] == "manage" and access["transcript"] is False
    # The source no longer sees the job (RLS), and the stub is readable there.
    async with tenant_connection(pool, w.a) as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM transcription_jobs WHERE id = $1", job) == 0
        )
        assert (
            await conn.fetchval("SELECT count(*) FROM note_relocations WHERE note_id = $1", note_id)
            == 1
        )
    # ...and only there: the target (or anyone else) cannot read where it came from.
    async with tenant_connection(pool, w.b) as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM note_relocations WHERE note_id = $1", note_id)
            == 0
        )


@pytest.mark.asyncio
async def test_moving_back_clears_the_first_stub(env) -> None:  # noqa: ANN001
    su, pool, w = env
    note_id = await _note(su, w)
    await note_move.move(
        app_pool=pool, note=await _fetch(pool, w.a, note_id), actor=w.author, to_tenant_id=w.b
    )
    back = await note_move.move(
        app_pool=pool, note=await _fetch(pool, w.b, note_id), actor=w.author, to_tenant_id=w.a
    )
    stubs = await su.fetch(
        "SELECT tenant_id, to_tenant_id FROM note_relocations WHERE note_id = $1", note_id
    )
    assert [(r["tenant_id"], r["to_tenant_id"]) for r in stubs] == [(w.b, w.a)]
    assert back.media_state == "ready"  # nothing to re-home without media


@pytest.mark.asyncio
async def test_visibility_follows_the_destination(env) -> None:  # noqa: ANN001
    su, pool, w = env
    locked = await _note(su, w, visibility_value="private", source="author")
    plain = await _note(su, w, visibility_value="private", source="default")
    one_on_one = await _note(su, w, meeting_type="one_on_one", visibility_value="workspace")
    to_personal = await _note(su, w)
    for note_id in (locked, plain, one_on_one):
        await note_move.move(
            app_pool=pool, note=await _fetch(pool, w.a, note_id), actor=w.author, to_tenant_id=w.b
        )
    personal = await note_move.move(
        app_pool=pool, note=await _fetch(pool, w.a, to_personal), actor=w.author, to_tenant_id=w.p
    )
    rows = {
        r["id"]: (r["visibility"], r["visibility_source"])
        for r in await su.fetch(
            "SELECT id, visibility::text, visibility_source FROM notes WHERE id = ANY($1)",
            [locked, plain, one_on_one, to_personal],
        )
    }
    assert rows[locked] == ("private", "author")  # the author's lock travels
    assert rows[plain] == ("workspace", "default")
    assert rows[one_on_one] == ("private", "default")
    assert rows[to_personal] == ("private", "default") and personal.visibility == "private"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "member_not_author",
        "random_target",
        "archived_target",
        "same_workspace",
        "someone_elses_personal",
        "generation_queued",
        "media_shared",
        "custom_template",
        "rehoming",
    ],
)
async def test_refusals_change_nothing(env, case: str) -> None:  # noqa: ANN001
    su, pool, w = env
    actor, target = w.author, w.b
    note_id = await _note(
        su,
        w,
        with_media=case == "media_shared",
        template=w.custom_template if case == "custom_template" else None,
    )
    expected = {
        "member_not_author": "insufficient_role",
        "random_target": "not_a_member",
        "archived_target": "target_unavailable",
        "same_workspace": "same_workspace",
        "someone_elses_personal": "not_a_member",
        "generation_queued": "generation_in_progress",
        "media_shared": "media_shared",
        "custom_template": "custom_template",
        "rehoming": "media_in_progress",
    }[case]
    if case == "member_not_author":
        actor = w.colleague
    elif case == "random_target":
        target = uuid4()
    elif case == "archived_target":
        target = w.x
    elif case == "same_workspace":
        target = w.a
    elif case == "someone_elses_personal":
        # The admin moving the author's note into the author's Personal.
        actor, target = w.admin, w.p
        await su.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_sub, role) VALUES ($1,$2,'member')",
            w.p,
            w.admin,
        )
    elif case == "generation_queued":
        await su.execute(
            "INSERT INTO jobs (tenant_id, kind, payload) VALUES ($1,'note.generate',$2::jsonb)",
            w.a,
            json.dumps({"note_id": str(note_id)}),
        )
    elif case == "media_shared":
        job = await su.fetchval("SELECT asr_job_id FROM note_meetings WHERE note_id = $1", note_id)
        other = await _note(su, w, meeting_type=None)
        await su.execute(
            "UPDATE notes SET source_asr_job_id = $1, deleted_at = now() WHERE id = $2", job, other
        )
    elif case == "rehoming":
        await su.execute("UPDATE notes SET media_state = 'rehoming' WHERE id = $1", note_id)

    note = await _fetch(pool, w.a, note_id)
    before = await _checksum(su, w)
    with pytest.raises(note_move.RefusedError) as refused:
        await note_move.move(app_pool=pool, note=note, actor=actor, to_tenant_id=target)
    assert refused.value.code == expected
    assert await _checksum(su, w) == before


@pytest.mark.asyncio
async def test_a_copy_is_a_new_note_without_the_recording(env) -> None:  # noqa: ANN001
    su, pool, w = env
    note_id = await _note(su, w, with_media=True)
    note = await _fetch(pool, w.a, note_id)
    copy_id, code = await note_move.copy(app_pool=pool, note=note, actor=w.author, to_tenant_id=w.b)
    row = await su.fetchrow("SELECT * FROM notes WHERE id = $1", copy_id)
    assert row["tenant_id"] == w.b and row["code"] == code
    assert row["copied_from_note_id"] == note_id and row["copied_from_tenant_id"] == w.a
    assert row["source_asr_job_id"] is None and row["visibility"] == "workspace"
    meeting = await su.fetchrow("SELECT * FROM note_meetings WHERE note_id = $1", copy_id)
    assert meeting["asr_job_id"] is None and meeting["meeting_type"] == "client"
    async with tenant_connection(pool, w.b) as conn:
        copy_note = await repo.fetch_note(conn, note_id=copy_id)
        assert copy_note is not None
        version = await repo.fetch_version(conn, version_id=copy_note.current_version_id)
    source_version = await su.fetchval(
        "SELECT content_jsonb FROM note_versions WHERE note_id = $1", note_id
    )
    assert version is not None
    assert [s.text for s in version.content.sections] == ["We agreed."]
    assert all(s.transcript_segment_ids == [] for s in version.content.sections)
    assert "transcript_segment_ids" in str(source_version)
    # The original is where it was, untouched.
    assert await _count(su, "notes", "id", note_id, w.a) == 1


@pytest.mark.asyncio
async def test_copy_needs_a_creating_role_in_the_target(env) -> None:  # noqa: ANN001
    su, pool, w = env
    note_id = await _note(su, w)
    note = await _fetch(pool, w.a, note_id)
    with pytest.raises(note_move.RefusedError) as refused:
        await note_move.copy(app_pool=pool, note=note, actor=w.colleague, to_tenant_id=w.b)
    assert refused.value.code == "not_a_member"


@pytest.mark.asyncio
async def test_the_sql_family_rule_equals_the_python_one(env) -> None:  # noqa: ANN001
    su, _pool, w = env
    cases = [
        ("client", None, None),
        ("one_on_one", None, None),
        ("interview", None, None),
        ("auto", "voice_memo", None),
        ("auto", "one_on_one", None),
        ("team", "podcast_broadcast", None),
        (None, None, "interview_debrief_en"),
        (None, None, "voice_memo_de"),
        (None, None, "one_on_one_uk"),
        (None, None, "oneXonXone"),
        (None, None, "client_call_en"),
    ]
    for meeting_type, detected, template_code in cases:
        template = w.template
        if template_code:
            template = await su.fetchval(
                "INSERT INTO templates (tenant_id, code, name, language, category, schema_jsonb)"
                " VALUES ($1, $2, 't', 'en', 'meetings', '{}') RETURNING id",
                w.a,
                f"{template_code}_{uuid4().hex[:6]}",
            )
        note_id = await _note(
            su, w, template=template, meeting_type=meeting_type, detected=detected
        )
        sql = await su.fetchval("SELECT default_visibility_for_note($1)::text", note_id)
        code = await su.fetchval("SELECT code FROM templates WHERE id = $1", template)
        python = visibility.default_for_note(
            "team", meeting_type=meeting_type, meeting_type_detected=detected, template_code=code
        )
        assert sql == python, (meeting_type, detected, template_code)


class _Store:
    """Objects sealed with (tenant, aad), as the envelope does."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[UUID, bytes, bytes]] = {}

    async def exists(self, *, key: str) -> bool:
        return key in self.objects

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes) -> bytes:
        sealed_for, sealed_aad, data = self.objects[key]
        assert (sealed_for, sealed_aad) == (tenant_id, aad), "envelope refused"
        return data

    async def put(self, *, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        self.objects[key] = (tenant_id, aad, plaintext)

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_the_rehome_job_brings_audio_and_every_revision_home(env) -> None:  # noqa: ANN001
    from note_service.jobs import rehome_media

    su, pool, w = env
    note_id = await _note(su, w, with_media=True)
    job = await su.fetchval("SELECT asr_job_id FROM note_meetings WHERE note_id = $1", note_id)
    audio = await su.fetchval("SELECT audio_id FROM transcription_jobs WHERE id = $1", job)
    await su.execute(
        "UPDATE transcription_jobs SET diarization_rev = 2, previous_result_storage_uri = $2"
        " WHERE id = $1",
        job,
        f"minio://transcripts/{w.a}/{job}.r2.json.enc",
    )
    audio_store, transcripts = _Store(), _Store()
    audio_store.objects[f"{w.a}/{audio}.enc"] = (w.a, audio.bytes, b"ogg")
    for key in (f"{w.a}/{job}.json.enc", f"{w.a}/{job}.r2.json.enc", f"{w.a}/{job}.r3.json.enc"):
        transcripts.objects[key] = (w.a, job.bytes, b"{}")

    await note_move.move(
        app_pool=pool, note=await _fetch(pool, w.a, note_id), actor=w.author, to_tenant_id=w.b
    )
    payload = await su.fetchval(
        "SELECT payload FROM jobs WHERE kind = 'note.rehome_media' AND payload->>'note_id' = $1",
        str(note_id),
    )
    audits: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audits.append(kwargs)

    from types import SimpleNamespace

    result = await rehome_media.handle_rehome(
        app_pool=pool,
        stores={"audio": audio_store, "transcripts": transcripts},
        audit_writer=SimpleNamespace(write_event=_write_event),
        tenant_id=w.b,
        payload=json.loads(payload) if isinstance(payload, str) else dict(payload),
    )
    assert result["keys"] == 5  # r2, r3, previous (r2 again, already home), audio, current
    assert set(audio_store.objects) == {f"{w.b}/{audio}.enc"}
    assert set(transcripts.objects) == {
        f"{w.b}/{job}.json.enc",
        f"{w.b}/{job}.r2.json.enc",
        f"{w.b}/{job}.r3.json.enc",
    }
    assert all(t == w.b for t, _aad, _data in transcripts.objects.values())
    row = await su.fetchrow(
        "SELECT result_storage_uri, previous_result_storage_uri FROM transcription_jobs WHERE id = $1",
        job,
    )
    assert row["result_storage_uri"] == f"minio://transcripts/{w.b}/{job}.json.enc"
    assert row["previous_result_storage_uri"] == f"minio://transcripts/{w.b}/{job}.r2.json.enc"
    assert await su.fetchval("SELECT storage_uri FROM audio_files WHERE id = $1", audio) == (
        f"minio://audio/{w.b}/{audio}.enc"
    )
    assert await su.fetchval("SELECT media_state FROM notes WHERE id = $1", note_id) == "ready"
    assert [a["kind"] for a in audits] == ["note.media_rehomed"]
    # Run again: nothing left to do, nothing broken.
    again = await rehome_media.handle_rehome(
        app_pool=pool,
        stores={"audio": audio_store, "transcripts": transcripts},
        audit_writer=SimpleNamespace(write_event=_write_event),
        tenant_id=w.b,
        payload=json.loads(payload) if isinstance(payload, str) else dict(payload),
    )
    assert again["bytes"] == 0


@pytest.mark.asyncio
async def test_the_backfill_opens_plain_notes_and_respects_choices(env) -> None:  # noqa: ANN001
    import importlib.util
    import sys
    from pathlib import Path

    from audit import AuditWriter, Severity

    su, pool, w = env
    path = Path(__file__).resolve().parents[4] / "scripts/ops/backfill_workspace_visibility.py"
    spec = importlib.util.spec_from_file_location("backfill_w5_itest", path)
    assert spec and spec.loader
    backfill = importlib.util.module_from_spec(spec)
    sys.modules["backfill_w5_itest"] = backfill
    spec.loader.exec_module(backfill)
    backfill.PAUSE_S = 0

    plain = [await _note(su, w, visibility_value="private") for _ in range(5)]
    for meeting_type, detected in (
        ("one_on_one", None),
        ("interview", None),
        ("auto", "voice_memo"),
    ):
        await _note(su, w, visibility_value="private", meeting_type=meeting_type, detected=detected)
    chosen = [await _note(su, w, visibility_value="private") for _ in range(2)]
    for _ in range(4):
        await _note(su, w, visibility_value="workspace")
    # A workspace-visible note in Personal breaks the invariant: reported, not fixed.
    await _note(su, w, tenant=w.p, visibility_value="workspace", meeting_type=None)

    audit_pool = await create_pool(
        f"postgresql://audit_writer:audit_writer@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}",
        application_name="w5-itest-audit",
        min_size=1,
        max_size=2,
    )
    writer = AuditWriter(audit_pool)
    for note_id in chosen:
        await writer.write_event(
            tenant_id=w.a,
            kind="note.visibility_changed",
            actor_sub=w.author,
            actor_role="member",
            target_kind="note",
            target_id=note_id,
            payload={"from": "workspace", "to": "private"},
            severity=Severity.INFO,
        )
    told: list[tuple] = []

    class _Redis:
        async def xadd(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            told.append((args, kwargs))

    try:
        dry = await backfill.run(
            pool=pool, audit_pool=audit_pool, redis=_Redis(), only=w.a, apply=False
        )
        assert dry[w.a] == {"candidates": 5, "skipped_sensitive": 3, "skipped_author_choice": 2}
        assert (
            await su.fetchval(
                "SELECT count(*) FROM notes WHERE tenant_id = $1 AND visibility = 'workspace'", w.a
            )
            == 4
        )

        await backfill.run(pool=pool, audit_pool=audit_pool, redis=_Redis(), only=w.a, apply=True)
        assert len(told) == 1  # one notice for the one author who had notes changed
        rows = {
            r["id"]: (r["visibility"], r["visibility_source"])
            for r in await su.fetch(
                "SELECT id, visibility::text, visibility_source FROM notes WHERE tenant_id = $1",
                w.a,
            )
        }
        assert all(rows[n] == ("workspace", "backfill") for n in plain)
        assert all(rows[n] == ("private", "author") for n in chosen)
        assert (
            await su.fetchval(
                "SELECT count(*) FROM notes WHERE tenant_id = $1 AND visibility = 'private'"
                " AND visibility_source = 'default'",
                w.a,
            )
            == 3
        )  # only the person-centred notes stay private by default
        assert (
            await su.fetchval(
                "SELECT count(*) FROM audit.events WHERE tenant_id = $1"
                " AND kind = 'note.visibility_changed' AND payload_jcs->'payload'->>'reason' = 'backfill_w5'",
                w.a,
            )
            == 5
        )

        again = await backfill.run(
            pool=pool, audit_pool=audit_pool, redis=_Redis(), only=w.a, apply=True
        )
        assert len(told) == 1  # nothing changed, nobody told again
        assert again[w.a] == {"candidates": 0, "skipped_sensitive": 3, "skipped_author_choice": 0}

        personal = await backfill.run(
            pool=pool, audit_pool=audit_pool, redis=_Redis(), only=w.p, apply=True
        )
        assert personal[w.p] == {"personal_violations": 1}
    finally:
        await audit_pool.close()  # audit.events is immutable: its rows stay (disposable DB)
