"""Erase one ASR job completely (DSAR / tenant request): objects, then rows.

Objects first (every delete VERIFIED; the storage client swallows errors), rows last,
so a half-done erase can simply be run again. Operator role: every statement filters
by ``tenant_id`` explicitly. A job still transcribing or re-labelling is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class _Store(Protocol):
    async def delete(self, *, key: str) -> None: ...

    async def exists(self, *, key: str) -> bool: ...


class ErasureError(Exception):
    """The job cannot be erased right now (still running, or a delete failed)."""


@dataclass(frozen=True)
class ErasePlan:
    tenant_id: UUID
    job_id: UUID
    audio_id: UUID
    transcript_keys: list[str]
    audio_key: str


def transcript_keys(tenant_id: UUID, job_id: UUID, diarization_rev: int) -> list[str]:
    """Every transcript object a job can have: original + r2…r{rev+1} (a re-run writes
    its artifact before the row moves)."""
    keys = [f"{tenant_id}/{job_id}.json.enc"]
    keys += [f"{tenant_id}/{job_id}.r{n}.json.enc" for n in range(2, max(1, diarization_rev) + 2)]
    return keys


async def plan(conn: Any, *, tenant_id: UUID, job_id: UUID) -> ErasePlan | None:
    row = await conn.fetchrow(
        """
        SELECT audio_id, diarization_rev, status, diarization_status
        FROM transcription_jobs WHERE id = $1 AND tenant_id = $2
        """,
        job_id,
        tenant_id,
    )
    if row is None:
        return None
    if row["status"] in ("queued", "running") or row["diarization_status"] in (
        "queued",
        "running",
    ):
        raise ErasureError(
            "the job is still transcribing or re-labelling; cancel it or wait, then erase"
        )
    return ErasePlan(
        tenant_id=tenant_id,
        job_id=job_id,
        audio_id=row["audio_id"],
        transcript_keys=transcript_keys(tenant_id, job_id, int(row["diarization_rev"] or 1)),
        audio_key=f"{tenant_id}/{row['audio_id']}.enc",
    )


async def erase(
    conn: Any, *, transcripts: _Store, audio: _Store, erase_plan: ErasePlan
) -> dict[str, int]:
    """Delete objects (verified), then rows. Returns counts only."""
    for key in erase_plan.transcript_keys:
        await _delete_verified(transcripts, key)
    await _delete_verified(audio, erase_plan.audio_key)
    edits = await conn.fetchval(
        "SELECT count(*) FROM transcription_speaker_edits WHERE job_id = $1 AND tenant_id = $2",
        erase_plan.job_id,
        erase_plan.tenant_id,
    )
    jobs = await conn.execute(
        "DELETE FROM transcription_jobs WHERE id = $1 AND tenant_id = $2",
        erase_plan.job_id,
        erase_plan.tenant_id,
    )
    audio_rows = await conn.execute(
        "DELETE FROM audio_files WHERE id = $1 AND tenant_id = $2",
        erase_plan.audio_id,
        erase_plan.tenant_id,
    )
    return {
        "transcript_objects": len(erase_plan.transcript_keys),
        "audio_objects": 1,
        "jobs": _count(jobs),
        "speaker_edits": int(edits or 0),
        "audio_rows": _count(audio_rows),
    }


async def _delete_verified(store: _Store, key: str) -> None:
    await store.delete(key=key)
    if await store.exists(key=key):
        raise ErasureError("an object could not be deleted; no rows were touched")


def _count(status: str) -> int:
    """asyncpg command tag → row count ("DELETE 1" → 1)."""
    try:
        return int(str(status).split()[-1])
    except (ValueError, IndexError):
        return 0
