"""The worker's re-run SQL against the real schema (migration 0044).

Unit tests fake the job row; this runs ``_rediarize_one`` with a real
app_role pool (RLS on), fake object stores and a fake diarizer: the claim,
the swap, the idempotent redelivery and the failure write are the real
statements.

Skipped unless RUN_DB_INTEGRATION=1. Creates one throwaway tenant and
deletes only its rows.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import asyncpg
import numpy as np
import pytest

from asr_models import JobEnqueuePayload
from asr_worker import processor
from db import create_pool, tenant_connection
from tests.unit.test_rediarize import _THREE, _Audit, _Diarizer, _NoAsr, _Store, _transcript

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1 to run; needs `make dev-up && make migrate-up`",
)

HOST = os.environ.get("POSTGRES_HOST", "localhost")
PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB = os.environ.get("POSTGRES_DB", "notes")
BUCKET = "mdx-transcripts"


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    tenant, job, audio, request = uuid4(), uuid4(), uuid4(), uuid4()
    writer = await asyncpg.connect(f"postgresql://tenant_writer:tenant_writer@{HOST}:{PORT}/{DB}")
    try:
        await writer.execute(
            "INSERT INTO tenants (id, name, display_name) VALUES ($1, $2, 'S29 worker test')",
            tenant,
            f"s29w-{tenant.hex[:8]}",
        )
    finally:
        await writer.close()
    pool = await create_pool(
        f"postgresql://app_role:app_role@{HOST}:{PORT}/{DB}", application_name="s29-worker-test"
    )
    original_key = f"{tenant}/{job}.json.enc"
    async with tenant_connection(pool, tenant) as c:
        await c.execute(
            """
            INSERT INTO audio_files (id, tenant_id, uploader_sub, mime_type, size_bytes,
                                     sha256, envelope_metadata, storage_uri)
            VALUES ($1, $2, $3, 'audio/wav', 1024, $4, '{"v":1}'::jsonb, $5)
            """,
            audio,
            tenant,
            uuid4(),
            b"\x00" * 32,
            f"minio://mdx-audio/{tenant}/{audio}.enc",
        )
        await c.execute(
            """
            INSERT INTO transcription_jobs (id, tenant_id, audio_id, requester_sub, language,
                status, result_storage_uri, speaker_names, diarization_status,
                diarization_request_id)
            VALUES ($1, $2, $3, $4, 'en', 'complete', $5, $6::jsonb, 'queued', $7)
            """,
            job,
            tenant,
            audio,
            uuid4(),
            f"minio://{BUCKET}/{original_key}",
            json.dumps({"SPEAKER_1": "Anna"}),
            request,
        )
    transcripts = _Store(BUCKET)
    transcripts.objects[original_key] = _transcript().model_dump_json().encode()
    audio_store = _Store("mdx-audio")
    audio_store.objects[f"{tenant}/{audio}.enc"] = b"fake"
    state = type(
        "S",
        (),
        {
            "app_pool": pool,
            "audio_store": audio_store,
            "transcript_store": transcripts,
            "audit_writer": _Audit(),
            "diarizer": _Diarizer(_THREE),
            "shadow_diarizer": None,
            "engine": _NoAsr(),
        },
    )()

    async def decode(_b: bytes, **_kw: Any) -> np.ndarray:
        return np.zeros(16_000 * 20, dtype=np.float32)

    monkeypatch.setattr(processor, "decode_to_pcm", decode)
    try:
        yield {
            "state": state,
            "pool": pool,
            "tenant": tenant,
            "job": job,
            "audio": audio,
            "request": request,
            "transcripts": transcripts,
            "original_key": original_key,
        }
    finally:
        await pool.close()
        su = await asyncpg.connect(f"postgresql://postgres:postgres@{HOST}:{PORT}/{DB}")
        try:
            await su.execute("DELETE FROM transcription_jobs WHERE tenant_id = $1", tenant)
            await su.execute("DELETE FROM audio_files WHERE tenant_id = $1", tenant)
            await su.execute("DELETE FROM tenants WHERE id = $1", tenant)
        finally:
            await su.close()


def _payload(w: dict[str, Any], rev: int = 2) -> JobEnqueuePayload:
    return JobEnqueuePayload(
        job_id=w["job"],
        tenant_id=w["tenant"],
        audio_id=w["audio"],
        language="auto",
        diarize=True,
        requester_sub=uuid4(),
        task="rediarize",
        target_rev=rev,
        rediarize_id=w["request"],
        num_speakers=3,
    )


async def _row(w: dict[str, Any]) -> asyncpg.Record:
    async with tenant_connection(w["pool"], w["tenant"]) as c:
        return await c.fetchrow("SELECT * FROM transcription_jobs WHERE id = $1", w["job"])


async def test_rerun_swaps_revisions_in_the_real_row(world: dict[str, Any]) -> None:
    await processor._rediarize_one(world["state"], _payload(world))
    await processor._rediarize_one(world["state"], _payload(world))  # duplicate delivery

    row = await _row(world)
    new_key = processor.revision_key(world["tenant"], world["job"], 2)
    assert row["status"] == "complete"
    assert (row["diarization_status"], row["diarization_rev"]) == ("complete", 2)
    assert row["result_storage_uri"] == f"minio://{BUCKET}/{new_key}"
    assert row["previous_result_storage_uri"] == f"minio://{BUCKET}/{world['original_key']}"
    assert json.loads(row["speaker_names"]) == {"SPEAKER_1": "Anna"}
    assert json.loads(row["previous_speaker_names"]) == {"SPEAKER_1": "Anna"}
    assert json.loads(row["metadata"])["diarization"]["hint_num_speakers"] == 3
    assert world["transcripts"].puts == [new_key], "the duplicate did nothing"


async def test_a_failed_rerun_is_recorded_on_the_real_row(world: dict[str, Any]) -> None:
    world["state"].audio_store.objects.clear()

    with pytest.raises(processor._NonRetryableError):
        await processor._rediarize_one(world["state"], _payload(world))

    row = await _row(world)
    assert (row["status"], row["diarization_status"], row["diarization_error"]) == (
        "complete",
        "failed",
        "audio_missing",
    )
    assert row["diarization_rev"] == 1
