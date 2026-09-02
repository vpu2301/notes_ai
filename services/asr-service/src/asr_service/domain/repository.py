"""Repository functions for asr-service.

Lives in ``domain/`` so router/adapter layers cannot accidentally bypass
it. Every query is tenant-scoped via :func:`db.tenant_connection`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from asr_models import JobStatus, TranscriptionJobView


async def insert_audio_row(
    conn: asyncpg.Connection,
    *,
    audio_id: UUID,
    tenant_id: UUID,
    uploader_sub: UUID,
    mime_type: str,
    size_bytes: int,
    duration_ms: int,
    sha256: bytes,
    envelope_metadata: dict[str, Any],
    storage_uri: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO audio_files
            (id, tenant_id, uploader_sub, mime_type, size_bytes,
             duration_ms, sha256, envelope_metadata, storage_uri, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, 'stored')
        """,
        audio_id,
        tenant_id,
        uploader_sub,
        mime_type,
        size_bytes,
        duration_ms,
        sha256,
        json.dumps(envelope_metadata),
        storage_uri,
    )


async def insert_job_row(
    conn: asyncpg.Connection,
    *,
    job_id: UUID,
    tenant_id: UUID,
    audio_id: UUID,
    requester_sub: UUID,
    language: str,
    model: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO transcription_jobs
            (id, tenant_id, audio_id, requester_sub, language, model)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        job_id,
        tenant_id,
        audio_id,
        requester_sub,
        language,
        model,
    )


async def get_job(conn: asyncpg.Connection, *, job_id: UUID) -> TranscriptionJobView | None:
    row = await conn.fetchrow(
        "SELECT * FROM transcription_jobs WHERE id = $1",
        job_id,
    )
    if row is None:
        return None
    return _row_to_view(row)


async def list_jobs(
    conn: asyncpg.Connection,
    *,
    limit: int,
    status: JobStatus | None = None,
    since: datetime | None = None,
) -> list[TranscriptionJobView]:
    where_parts: list[str] = []
    args: list[Any] = []
    if status is not None:
        where_parts.append(f"j.status = ${len(args) + 1}")
        args.append(str(status))
    if since is not None:
        where_parts.append(f"j.queued_at >= ${len(args) + 1}")
        args.append(since)
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    args.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT j.*
        FROM transcription_jobs j
        {where_sql}
        ORDER BY j.queued_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    return [_row_to_view(r) for r in rows]


async def request_cancel(conn: asyncpg.Connection, *, job_id: UUID) -> str | None:
    """Mark the job for cancellation; return the new status or ``None``
    if it cannot be cancelled (already terminal).
    """
    row = await conn.fetchrow(
        "SELECT status FROM transcription_jobs WHERE id = $1 FOR UPDATE",
        job_id,
    )
    if row is None:
        return None
    current = str(row["status"])
    if current == "queued":
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET status='cancelled', finished_at=now(), cancel_requested=true
            WHERE id = $1
            """,
            job_id,
        )
        return "cancelled"
    if current == "running":
        await conn.execute(
            "UPDATE transcription_jobs SET cancel_requested=true WHERE id = $1",
            job_id,
        )
        return "cancel_requested"
    return None


async def fail_job(
    conn: asyncpg.Connection,
    *,
    job_id: UUID,
    error_kind: str,
    error_detail: str,
    only_if_status: tuple[str, ...] = ("queued", "running"),
) -> bool:
    """Move a job to ``failed``; return whether this call is what moved it.

    ``only_if_status`` is the interlock. The reaper and the enqueue path
    both write terminal failures from outside the worker that owns the
    job, and a job that came back to life between the read and the write
    must keep its own outcome — a transcript already stored must never be
    overwritten by a late "the worker looked dead".
    """
    row = await conn.fetchrow(
        """
        UPDATE transcription_jobs
        SET status='failed',
            error_kind=$2,
            error_detail=$3,
            finished_at=now()
        WHERE id = $1 AND status = ANY($4::text[])
        RETURNING id
        """,
        job_id,
        error_kind,
        error_detail[:1024],
        list(only_if_status),
    )
    return row is not None


@dataclass(slots=True)
class StaleJobRow:
    """A job that has outlived the process or the queue that owned it."""

    id: UUID
    status: str
    requester_sub: UUID
    started_at: datetime | None


async def list_stale_jobs(
    conn: asyncpg.Connection,
    *,
    running_grace_seconds: float,
    queued_grace_seconds: float,
    limit: int,
) -> list[StaleJobRow]:
    """Jobs stranded mid-flight, oldest first.

    Two shapes, one query:

    - ``running`` past ``running_grace_seconds`` — the worker that claimed
      it died between marking it running and writing an outcome. Nothing
      else in the system ever revisits that row.
    - ``queued`` past ``queued_grace_seconds`` — the enqueue landed but the
      message did not survive (a flushed Redis, a stream trimmed under
      load), so no worker will ever claim it.

    Both windows are wall-clock only; the reaper applies its own
    liveness interlock before it collects anything.
    """
    rows = await conn.fetch(
        """
        SELECT id, status, requester_sub, started_at
        FROM transcription_jobs
        WHERE (status = 'running' AND started_at < now()
                   - make_interval(secs => $1::double precision))
           OR (status = 'queued'  AND queued_at  < now()
                   - make_interval(secs => $2::double precision))
        ORDER BY queued_at
        LIMIT $3
        """,
        float(running_grace_seconds),
        float(queued_grace_seconds),
        limit,
    )
    return [
        StaleJobRow(
            id=r["id"],
            status=str(r["status"]),
            requester_sub=r["requester_sub"],
            started_at=r["started_at"],
        )
        for r in rows
    ]


async def count_active_jobs(conn: asyncpg.Connection, *, tenant_id: UUID) -> int:
    """Return the number of queued + running jobs for the tenant.

    Used by the rate-limit check (per-tenant concurrent cap).
    """
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS n
        FROM transcription_jobs
        WHERE status IN ('queued','running')
        """,
    )
    return int(row["n"]) if row is not None else 0


def _row_to_view(row: asyncpg.Record) -> TranscriptionJobView:
    return TranscriptionJobView(
        id=row["id"],
        tenant_id=row["tenant_id"],
        audio_id=row["audio_id"],
        requester_sub=row["requester_sub"],
        language=row["language"],
        detected_language=row.get("detected_language"),
        model=row["model"],
        status=JobStatus(row["status"]),
        error_kind=row["error_kind"],
        error_detail=row["error_detail"],
        queued_at=row["queued_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        attempts=int(row["attempts"]),
        cancel_requested=bool(row.get("cancel_requested") or False),
    )
