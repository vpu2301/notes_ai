"""Erasure finds a moved job's objects where its row's URIs say (W5)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from asr_service.domain import job_erasure

TENANT, OLD, JOB, AUDIO = uuid4(), uuid4(), uuid4(), uuid4()


class _Conn:
    def __init__(self, row: dict) -> None:
        self.row = row

    async def fetchrow(self, sql: str, *args: object) -> dict:
        return self.row


def _row(**over: object) -> dict:
    base = {
        "audio_id": AUDIO,
        "diarization_rev": 1,
        "status": "complete",
        "diarization_status": None,
        "result_storage_uri": f"minio://transcripts/{TENANT}/{JOB}.json.enc",
        "previous_result_storage_uri": None,
        "audio_uri": f"minio://audio/{TENANT}/{AUDIO}.enc",
        "rehoming": False,
    }
    return {**base, **over}


@pytest.mark.asyncio
async def test_an_unmoved_job_erases_what_it_always_did() -> None:
    plan = await job_erasure.plan(_Conn(_row()), tenant_id=TENANT, job_id=JOB)
    assert plan is not None
    assert plan.transcript_keys == job_erasure.transcript_keys(TENANT, JOB, 1)
    assert plan.audio_key == f"{TENANT}/{AUDIO}.enc"


@pytest.mark.asyncio
async def test_objects_left_under_the_old_workspace_are_included() -> None:
    row = _row(
        result_storage_uri=f"minio://transcripts/{OLD}/{JOB}.json.enc",
        audio_uri=f"minio://audio/{OLD}/{AUDIO}.enc",
    )
    plan = await job_erasure.plan(_Conn(row), tenant_id=TENANT, job_id=JOB)
    assert plan is not None
    assert set(job_erasure.transcript_keys(OLD, JOB, 1)) <= set(plan.transcript_keys)
    assert set(job_erasure.transcript_keys(TENANT, JOB, 1)) <= set(plan.transcript_keys)
    assert plan.audio_key == f"{OLD}/{AUDIO}.enc"


@pytest.mark.asyncio
async def test_a_job_whose_note_is_moving_is_refused() -> None:
    with pytest.raises(job_erasure.ErasureError):
        await job_erasure.plan(_Conn(_row(rehoming=True)), tenant_id=TENANT, job_id=JOB)
