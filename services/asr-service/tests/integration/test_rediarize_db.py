"""Speaker re-labelling, edits and erasure against the real schema and RLS.

Skipped unless RUN_DB_INTEGRATION=1 (needs `make dev-up && make migrate-up`).
Creates two throwaway tenants and deletes only their rows.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
import pytest

from asr_service.domain import repository
from db import create_pool, tenant_connection

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1 to run; needs `make dev-up && make migrate-up`",
)

HOST = os.environ.get("POSTGRES_HOST", "localhost")
PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB = os.environ.get("POSTGRES_DB", "notes")
APP_DSN = f"postgresql://app_role:app_role@{HOST}:{PORT}/{DB}"
WRITER_DSN = f"postgresql://tenant_writer:tenant_writer@{HOST}:{PORT}/{DB}"
SU_DSN = f"postgresql://postgres:postgres@{HOST}:{PORT}/{DB}"


@pytest.fixture
async def world() -> AsyncIterator[dict[str, object]]:
    tenants = [uuid4(), uuid4()]
    writer = await asyncpg.connect(WRITER_DSN)
    try:
        for t in tenants:
            await writer.execute(
                "INSERT INTO tenants (id, name, display_name) VALUES ($1, $2, $3)",
                t,
                f"s29-{t.hex[:8]}",
                "Sprint 29 test",
            )
    finally:
        await writer.close()
    pool = await create_pool(APP_DSN, application_name="s29-rediarize-test")
    try:
        yield {"pool": pool, "a": tenants[0], "b": tenants[1]}
    finally:
        await pool.close()
        su = await asyncpg.connect(SU_DSN)
        try:
            await su.execute(
                "DELETE FROM transcription_jobs WHERE tenant_id = ANY($1::uuid[])", tenants
            )
            await su.execute("DELETE FROM audio_files WHERE tenant_id = ANY($1::uuid[])", tenants)
            await su.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)
        finally:
            await su.close()


async def _job(pool: asyncpg.Pool, tenant: UUID, *, status: str = "complete") -> UUID:
    audio_id, job_id = uuid4(), uuid4()
    async with tenant_connection(pool, tenant) as c:
        await c.execute(
            """
            INSERT INTO audio_files (id, tenant_id, uploader_sub, mime_type, size_bytes,
                                     sha256, envelope_metadata, storage_uri)
            VALUES ($1, $2, $3, 'audio/wav', 1024, $4, '{"v":1}'::jsonb, $5)
            """,
            audio_id,
            tenant,
            uuid4(),
            b"\x00" * 32,
            f"minio://mdx-audio/{tenant}/{audio_id}.enc",
        )
        await c.execute(
            """
            INSERT INTO transcription_jobs (id, tenant_id, audio_id, requester_sub, language,
                                            status, result_storage_uri, speaker_names)
            VALUES ($1, $2, $3, $4, 'en', $5, $6, $7::jsonb)
            """,
            job_id,
            tenant,
            audio_id,
            uuid4(),
            status,
            f"minio://mdx-transcripts/{tenant}/{job_id}.json.enc",
            json.dumps({"SPEAKER_1": "Anna"}),
        )
    return job_id


async def _row(pool: asyncpg.Pool, tenant: UUID, job_id: UUID) -> asyncpg.Record:
    async with tenant_connection(pool, tenant) as c:
        row = await c.fetchrow("SELECT * FROM transcription_jobs WHERE id = $1", job_id)
    assert row is not None
    return row


async def test_claim_queues_once_and_counts_the_run(world: dict[str, object]) -> None:
    pool, a = world["pool"], world["a"]
    job = await _job(pool, a)  # type: ignore[arg-type]

    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        first = await repository.claim_rediarize(c, job_id=job, max_runs=5)
        second = await repository.claim_rediarize(c, job_id=job, max_runs=5)

    assert first is not None and first.refused is None
    assert (first.current_rev, first.target_rev) == (1, 2)
    assert first.request_id is not None
    assert second is not None and second.refused == "rediarize_in_progress"
    row = await _row(pool, a, job)  # type: ignore[arg-type]
    assert (row["diarization_status"], row["diarization_runs"]) == ("queued", 1)
    assert row["diarization_request_id"] == first.request_id
    assert row["status"] == "complete", "the transcript stays readable"
    view = repository._row_to_view(row)
    assert view.diarization_status == "queued"
    assert view.can_undo_rediarize is False


async def test_claim_refusals(world: dict[str, object]) -> None:
    pool, a = world["pool"], world["a"]
    running = await _job(pool, a, status="running")  # type: ignore[arg-type]
    capped = await _job(pool, a)  # type: ignore[arg-type]
    erased = await _job(pool, a)  # type: ignore[arg-type]
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        await c.execute("UPDATE transcription_jobs SET diarization_runs = 5 WHERE id = $1", capped)
        await c.execute(
            "UPDATE audio_files SET status = 'deleted' WHERE id = "
            "(SELECT audio_id FROM transcription_jobs WHERE id = $1)",
            erased,
        )
        refused = {
            job: (await repository.claim_rediarize(c, job_id=job, max_runs=5)).refused  # type: ignore[union-attr]
            for job in (running, capped, erased)
        }

    assert refused == {
        running: "job_not_complete",
        capped: "rediarize_limit",
        erased: "audio_unavailable",
    }
    row = await _row(pool, a, erased)  # type: ignore[arg-type]
    assert row["diarization_status"] is None, "a refusal writes nothing"


async def test_a_failed_enqueue_puts_the_row_back(world: dict[str, object]) -> None:
    pool, a = world["pool"], world["a"]
    job = await _job(pool, a)  # type: ignore[arg-type]
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        claim = await repository.claim_rediarize(c, job_id=job, max_runs=5)
        assert claim is not None
        await repository.release_rediarize_claim(c, job_id=job, claim=claim)

    row = await _row(pool, a, job)  # type: ignore[arg-type]
    assert (row["diarization_status"], row["diarization_runs"]) == (None, 0)


async def test_undo_restores_the_previous_labels_once(world: dict[str, object]) -> None:
    pool, a = world["pool"], world["a"]
    job = await _job(pool, a)  # type: ignore[arg-type]
    original = f"minio://mdx-transcripts/{a}/{job}.json.enc"
    rerun = f"minio://mdx-transcripts/{a}/{job}.r2.json.enc"
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        nothing = await repository.undo_rediarize(c, job_id=job)
        # What the worker leaves after a re-run.
        await c.execute(
            """
            UPDATE transcription_jobs
            SET previous_result_storage_uri = result_storage_uri,
                previous_speaker_names = speaker_names,
                result_storage_uri = $2, diarization_rev = 2,
                diarization_status = 'complete', speaker_names = '{}'::jsonb
            WHERE id = $1
            """,
            job,
            rerun,
        )
        undone = await repository.undo_rediarize(c, job_id=job)
        again = await repository.undo_rediarize(c, job_id=job)

    assert nothing is not None and nothing.refused == "nothing_to_undo"
    assert undone is not None and undone.refused is None
    assert (undone.rev, undone.undone_uri) == (3, rerun)
    assert again is not None and again.refused == "nothing_to_undo"
    row = await _row(pool, a, job)  # type: ignore[arg-type]
    assert row["result_storage_uri"] == original
    assert row["previous_result_storage_uri"] is None
    assert repository.parse_speaker_names(row["speaker_names"]) == {"SPEAKER_1": "Anna"}
    assert row["diarization_rev"] == 3, "the revision moves forward, never back"


async def test_another_tenant_can_neither_rerun_nor_undo(world: dict[str, object]) -> None:
    pool, a, b = world["pool"], world["a"], world["b"]
    job = await _job(pool, a)  # type: ignore[arg-type]

    async with tenant_connection(pool, b) as c:  # type: ignore[arg-type]
        assert await repository.claim_rediarize(c, job_id=job, max_runs=5) is None
        assert await repository.undo_rediarize(c, job_id=job) is None
        assert await repository.result_uri(c, job_id=job) is None

    row = await _row(pool, a, job)  # type: ignore[arg-type]
    assert (row["diarization_status"], row["diarization_runs"]) == (None, 0)


async def test_the_reaper_finds_and_fails_a_stranded_rerun(world: dict[str, object]) -> None:
    pool, a = world["pool"], world["a"]
    job = await _job(pool, a)  # type: ignore[arg-type]
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        await c.execute(
            "UPDATE transcription_jobs SET diarization_status = 'running', "
            "diarization_updated_at = now() - interval '2 hours' WHERE id = $1",
            job,
        )
    async with pool.acquire() as c:  # type: ignore[attr-defined]
        tenants = {
            r["tenant_id"]
            for r in await c.fetch("SELECT tenant_id FROM asr_tenants_with_stale_jobs(3600, 3600)")
        }
    assert a in tenants

    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        stale = await repository.list_stale_rediarize(
            c, running_grace_seconds=3600, queued_grace_seconds=3600, limit=10
        )
        assert [s.id for s in stale] == [job]
        assert not await repository.fail_rediarize(
            c, job_id=job, error="stranded", only_if_status="running", older_than_seconds=3 * 3600
        ), "still inside a longer grace window: left alone"
        assert await repository.fail_rediarize(
            c, job_id=job, error="stranded", only_if_status="running", older_than_seconds=3600
        )
        assert not await repository.fail_rediarize(
            c, job_id=job, error="stranded", only_if_status="running", older_than_seconds=3600
        ), "conditional: a second sweep changes nothing"

    row = await _row(pool, a, job)  # type: ignore[arg-type]
    assert (row["status"], row["diarization_status"], row["diarization_error"]) == (
        "complete",
        "failed",
        "stranded",
    )


# ── Speaker edits ─────────────────────────────────────────────────────


async def test_reassign_edits_reset_and_first_read(world: dict[str, object]) -> None:
    pool, a, b = world["pool"], world["a"], world["b"]
    job = await _job(pool, a)  # type: ignore[arg-type]
    actor = uuid4()
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        assert not await repository.has_corrections(c, job_id=job)
        edit = await repository.insert_speaker_edit(
            c,
            tenant_id=a,  # type: ignore[arg-type]
            job_id=job,
            result_rev=1,
            kind="reassign",
            from_label=None,
            to_label="SPEAKER_4",
            actor_sub=actor,
            segment_indices=[3, 4],
            creates_label=True,
        )
        assert (edit.segment_indices, edit.creates_label) == ([3, 4], True)
        assert await repository.has_corrections(c, job_id=job)
        with pytest.raises(asyncpg.CheckViolationError):
            async with c.transaction():
                await repository.insert_speaker_edit(
                    c,
                    tenant_id=a,  # type: ignore[arg-type]
                    job_id=job,
                    result_rev=1,
                    kind="reassign",
                    from_label=None,
                    to_label=None,
                    actor_sub=actor,
                    segment_indices=[],
                )
        assert await repository.mark_result_read(c, job_id=job)
        assert not await repository.mark_result_read(c, job_id=job), "set once"
    async with tenant_connection(pool, b) as c:  # type: ignore[arg-type]
        assert await repository.revert_live_edits(c, job_id=job, result_rev=1) == 0
        assert await repository.list_speaker_edits(c, job_id=job, result_rev=1) == []
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        assert await repository.revert_live_edits(c, job_id=job, result_rev=1) == 1
        assert await repository.revert_live_edits(c, job_id=job, result_rev=1) == 0
        # A reverted edit still reserves its label.
        assert await repository.all_edit_labels(c, job_id=job) == ["SPEAKER_4"]
        assert await repository.list_speaker_edits(c, job_id=job, result_rev=1) == []


async def test_capture_context_is_stored_on_the_row(world: dict[str, object]) -> None:
    pool, a, b = world["pool"], world["a"], world["b"]
    audio_id, job_id = uuid4(), uuid4()
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        await repository.insert_audio_row(
            c,
            audio_id=audio_id,
            tenant_id=a,  # type: ignore[arg-type]
            uploader_sub=uuid4(),
            mime_type="audio/wav",
            size_bytes=1024,
            duration_ms=1000,
            sha256=b"\x00" * 32,
            envelope_metadata={"v": 1},
            storage_uri=f"minio://mdx-audio/{a}/{audio_id}.enc",
        )
        await repository.insert_job_row(
            c,
            job_id=job_id,
            tenant_id=a,  # type: ignore[arg-type]
            audio_id=audio_id,
            requester_sub=uuid4(),
            language="en",
            model="large-v3",
            name_candidates=["Anna Keller", "Tom Berg"],
            capture_context={"source": "calendar_event", "client": "ios"},
        )
        assert await repository.name_candidates(c, job_id=job_id) == ["Anna Keller", "Tom Berg"]
        row = await c.fetchrow("SELECT capture_context FROM transcription_jobs WHERE id=$1", job_id)
        assert json.loads(row["capture_context"]) == {"source": "calendar_event", "client": "ios"}
    async with tenant_connection(pool, b) as c:  # type: ignore[arg-type]
        assert await repository.name_candidates(c, job_id=job_id) == []


# ── Name provenance ───────────────────────────────────────────────────


async def test_name_sources_persist_and_a_cleared_channel_name_is_remembered(
    world: dict[str, object],
) -> None:
    pool, a, b = world["pool"], world["a"], world["b"]
    job = await _job(pool, a)  # type: ignore[arg-type]
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        await c.execute(
            'UPDATE transcription_jobs SET speaker_name_sources = \'{"SPEAKER_1": "channel"}\' '
            "WHERE id = $1",
            job,
        )
        updated = await repository.update_name_sources(
            c, job_id=job, names={"SPEAKER_2": "Olena"}, sources={"SPEAKER_2": "picklist"}
        )
        assert updated == {"SPEAKER_1": "cleared", "SPEAKER_2": "picklist"}
        assert await repository.name_sources(c, job_id=job) == updated
    async with tenant_connection(pool, b) as c:  # type: ignore[arg-type]
        assert await repository.name_sources(c, job_id=job) == {}


# ── Job erasure ───────────────────────────────────────────────────────


class _Store:
    def __init__(self, *, sticky: bool = False) -> None:
        self.deleted: list[str] = []
        self.sticky = sticky  # a delete that silently does not take (bad credentials)

    async def delete(self, *, key: str) -> None:
        if not self.sticky:
            self.deleted.append(key)

    async def exists(self, *, key: str) -> bool:
        return self.sticky


async def test_erasing_a_job_removes_every_revision_edit_and_row(world: dict[str, object]) -> None:
    from asr_service.domain import job_erasure

    pool, a, b = world["pool"], world["a"], world["b"]
    job = await _job(pool, a)  # type: ignore[arg-type]
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        await c.execute("UPDATE transcription_jobs SET diarization_rev = 4 WHERE id = $1", job)
        await repository.insert_speaker_edit(
            c,
            tenant_id=a,
            job_id=job,
            result_rev=4,
            kind="merge",  # type: ignore[arg-type]
            from_label="SPEAKER_2",
            to_label="SPEAKER_1",
            actor_sub=uuid4(),
        )
    # Privileged operator flow (0004): not app_role.
    op = await asyncpg.connect(SU_DSN)
    try:
        assert await job_erasure.plan(op, tenant_id=b, job_id=job) is None  # type: ignore[arg-type]
        plan = await job_erasure.plan(op, tenant_id=a, job_id=job)  # type: ignore[arg-type]
        assert plan is not None
        with pytest.raises(job_erasure.ErasureError):
            await job_erasure.erase(
                op, transcripts=_Store(sticky=True), audio=_Store(), erase_plan=plan
            )
        assert await op.fetchval("SELECT count(*) FROM transcription_jobs WHERE id = $1", job) == 1
        transcripts, audio = _Store(), _Store()
        counts = await job_erasure.erase(op, transcripts=transcripts, audio=audio, erase_plan=plan)
        assert transcripts.deleted == [
            f"{a}/{job}.json.enc",
            f"{a}/{job}.r2.json.enc",
            f"{a}/{job}.r3.json.enc",
            f"{a}/{job}.r4.json.enc",
            f"{a}/{job}.r5.json.enc",
        ], "including the revision a failed re-run may have left beyond the row"
        assert audio.deleted == [plan.audio_key]
        assert (counts["jobs"], counts["speaker_edits"], counts["audio_rows"]) == (1, 1, 1)
        assert await op.fetchval("SELECT count(*) FROM transcription_jobs WHERE id = $1", job) == 0
        assert (
            await op.fetchval(
                "SELECT count(*) FROM transcription_speaker_edits WHERE job_id = $1", job
            )
            == 0
        )
    finally:
        await op.close()


async def test_a_job_still_running_is_not_erased(world: dict[str, object]) -> None:
    from asr_service.domain import job_erasure

    pool, a = world["pool"], world["a"]
    job = await _job(pool, a, status="running")  # type: ignore[arg-type]
    op = await asyncpg.connect(SU_DSN)
    try:
        with pytest.raises(job_erasure.ErasureError):
            await job_erasure.plan(op, tenant_id=a, job_id=job)  # type: ignore[arg-type]
    finally:
        await op.close()


async def test_dismissals_are_a_capped_set_and_tenant_scoped(world: dict[str, object]) -> None:
    pool, a, b = world["pool"], world["a"], world["b"]
    job = await _job(pool, a)  # type: ignore[arg-type]
    async with tenant_connection(pool, a) as c:  # type: ignore[arg-type]
        assert await repository.dismiss_suggestion(
            c, job_id=job, label="SPEAKER_2", name="Anna Keller"
        )
        assert not await repository.dismiss_suggestion(
            c, job_id=job, label="SPEAKER_2", name="anna  keller"
        ), "set semantics"
        for i in range(40):
            await repository.dismiss_suggestion(c, job_id=job, label="SPEAKER_3", name=f"N{i}")
        pairs = await repository.dismissed_suggestions(c, job_id=job)
        assert len(pairs) == repository.MAX_DISMISSED_SUGGESTIONS
        audio = await repository.audio_state(c, job_id=job)
        assert audio is not None and audio.audio_status == "stored"
        assert (audio.diarization_runs, audio.diarization_status) == (0, None)
        # Scoped to the labelling: after a re-run the "no" no longer applies.
        await c.execute("UPDATE transcription_jobs SET diarization_rev = 2 WHERE id = $1", job)
        assert await repository.dismissed_suggestions(c, job_id=job, result_rev=2) == []
        assert await repository.dismiss_suggestion(
            c, job_id=job, label="SPEAKER_2", name="Anna Keller"
        )
    async with tenant_connection(pool, b) as c:  # type: ignore[arg-type]
        assert (
            await repository.dismiss_suggestion(c, job_id=job, label="SPEAKER_2", name="X") is None
        )
        assert await repository.audio_state(c, job_id=job) is None
