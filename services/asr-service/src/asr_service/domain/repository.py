"""Repository functions for asr-service.

Lives in ``domain/`` so router/adapter layers cannot accidentally bypass
it. Every query is tenant-scoped via :func:`db.tenant_connection`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from asr_models import JobStatus, TranscriptionJobView

from .speaker_edits import SpeakerEdit


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


# Sprint I2 T2: whether `transcription_jobs.vocabulary_hint` (migration
# 0061) exists on this database. Probed once at startup; a service running
# ahead of the migration keeps accepting jobs and stores no hint (with a
# warning), never fails one.
HINT_COLUMN_PRESENT: bool = True


async def probe_hint_column(pool: asyncpg.Pool) -> bool:
    global HINT_COLUMN_PRESENT  # noqa: PLW0603 — a startup fact, read by every insert
    async with pool.acquire() as conn:
        present = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
            " WHERE table_name = 'transcription_jobs' AND column_name = 'vocabulary_hint')"
        )
    HINT_COLUMN_PRESENT = bool(present)
    if not HINT_COLUMN_PRESENT:
        logging.getLogger(__name__).warning(
            "asr.vocabulary_hint_column_missing",
            extra={"migration": "0061_transcription_vocabulary_hint"},
        )
    return HINT_COLUMN_PRESENT


async def insert_job_row(
    conn: asyncpg.Connection,
    *,
    job_id: UUID,
    tenant_id: UUID,
    audio_id: UUID,
    requester_sub: UUID,
    language: str,
    model: str,
    name_candidates: list[str] | None = None,
    capture_context: dict[str, str] | None = None,
    vocabulary_hint: str | None = None,
) -> None:
    if HINT_COLUMN_PRESENT:
        await conn.execute(
            """
            INSERT INTO transcription_jobs
                (id, tenant_id, audio_id, requester_sub, language, model,
                 speaker_name_candidates, capture_context, vocabulary_hint)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9)
            """,
            job_id,
            tenant_id,
            audio_id,
            requester_sub,
            language,
            model,
            json.dumps(name_candidates or []),
            json.dumps(capture_context or {}),
            vocabulary_hint,
        )
        return
    await conn.execute(
        """
        INSERT INTO transcription_jobs
            (id, tenant_id, audio_id, requester_sub, language, model,
             speaker_name_candidates, capture_context)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb)
        """,
        job_id,
        tenant_id,
        audio_id,
        requester_sub,
        language,
        model,
        json.dumps(name_candidates or []),
        json.dumps(capture_context or {}),
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


async def set_speaker_names(
    conn: asyncpg.Connection, *, job_id: UUID, names: dict[str, str]
) -> dict[str, str] | None:
    """Replace the job's speaker naming; return the stored mapping, or
    ``None`` when the job does not exist (in this tenant)."""
    row = await conn.fetchrow(
        """
        UPDATE transcription_jobs
        SET speaker_names = $2::jsonb
        WHERE id = $1
        RETURNING speaker_names
        """,
        job_id,
        json.dumps(names),
    )
    if row is None:
        return None
    return parse_speaker_names(row["speaker_names"])


# ── Speaker edits (Sprint 28) ──────────────────────────────────────────


_EDIT_COLUMNS = (
    "id, kind, from_label, to_label, segment_indices, result_rev, seq, created_at, creates_label"
)


async def list_speaker_edits(
    conn: asyncpg.Connection, *, job_id: UUID, result_rev: int
) -> list[SpeakerEdit]:
    """Live (not reverted) edits of one diarization run, in ``seq`` order."""
    rows = await conn.fetch(
        f"""
        SELECT {_EDIT_COLUMNS} FROM transcription_speaker_edits
        WHERE job_id = $1 AND result_rev = $2 AND reverted_at IS NULL
        ORDER BY seq
        """,
        job_id,
        result_rev,
    )
    return [_row_to_edit(r) for r in rows]


async def lock_job_for_edit(conn: asyncpg.Connection, *, job_id: UUID) -> asyncpg.Record | None:
    """Row-lock the job: serialises edits so ``seq`` allocation never races."""
    return await conn.fetchrow(
        """
        SELECT id, tenant_id, status, diarization_rev, speaker_names,
               diarization_status, result_storage_uri
        FROM transcription_jobs WHERE id = $1 FOR UPDATE
        """,
        job_id,
    )


async def insert_speaker_edit(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    job_id: UUID,
    result_rev: int,
    kind: str,
    from_label: str | None,
    to_label: str | None,
    actor_sub: UUID,
    segment_indices: list[int] | None = None,
    creates_label: bool = False,
) -> SpeakerEdit:
    row = await conn.fetchrow(
        f"""
        INSERT INTO transcription_speaker_edits
            (tenant_id, job_id, result_rev, seq, kind, from_label, to_label, actor_sub,
             segment_indices, creates_label)
        VALUES ($1, $2, $3,
                (SELECT coalesce(max(seq), 0) + 1 FROM transcription_speaker_edits
                 WHERE job_id = $2),
                $4, $5, $6, $7, $8, $9)
        RETURNING {_EDIT_COLUMNS}
        """,
        tenant_id,
        job_id,
        result_rev,
        kind,
        from_label,
        to_label,
        actor_sub,
        segment_indices,
        creates_label,
    )
    return _row_to_edit(row)


async def get_speaker_edit(
    conn: asyncpg.Connection, *, job_id: UUID, edit_id: UUID
) -> tuple[SpeakerEdit, bool] | None:
    """The edit (resolved together with its job, never by id alone) and
    whether it is already reverted."""
    row = await conn.fetchrow(
        f"""
        SELECT {_EDIT_COLUMNS}, reverted_at IS NOT NULL AS reverted
        FROM transcription_speaker_edits WHERE id = $1 AND job_id = $2
        """,
        edit_id,
        job_id,
    )
    if row is None:
        return None
    return _row_to_edit(row), bool(row["reverted"])


async def revert_speaker_edit(conn: asyncpg.Connection, *, edit_id: UUID) -> None:
    await conn.execute(
        "UPDATE transcription_speaker_edits SET reverted_at = now() WHERE id = $1",
        edit_id,
    )


def _row_to_edit(row: asyncpg.Record) -> SpeakerEdit:
    return SpeakerEdit(
        id=row["id"],
        kind=row["kind"],
        from_label=row["from_label"],
        to_label=row["to_label"],
        segment_indices=list(row["segment_indices"] or []),
        result_rev=int(row["result_rev"]),
        seq=int(row["seq"]),
        created_at=row["created_at"],
        creates_label=bool(row.get("creates_label") or False),
    )


# ── Speaker re-labelling (Sprint 29) ─────────────────────────────────


async def get_job_and_result_uri(
    conn: asyncpg.Connection, *, job_id: UUID
) -> tuple[TranscriptionJobView, str | None] | None:
    """The view and its artifact from ONE row read: rev, names and the
    artifact they describe must come from the same moment (a re-run swaps
    all three at once)."""
    row = await conn.fetchrow("SELECT * FROM transcription_jobs WHERE id = $1", job_id)
    if row is None:
        return None
    uri = row.get("result_storage_uri")
    return _row_to_view(row), (str(uri) if uri else None)


async def result_uri(conn: asyncpg.Connection, *, job_id: UUID) -> str | None:
    """Where the job's CURRENT transcript artifact lives. A re-run writes a
    new ``.r{rev}`` object and repoints this; every read must follow it."""
    row = await conn.fetchrow(
        "SELECT result_storage_uri FROM transcription_jobs WHERE id = $1", job_id
    )
    return str(row["result_storage_uri"]) if row and row["result_storage_uri"] else None


def key_from_uri(uri: str) -> str:
    """``minio://bucket/<key>`` → ``<key>``."""
    return uri.split("://", 1)[-1].split("/", 1)[1]


@dataclass(slots=True)
class RediarizeClaim:
    """Outcome of asking for a re-run. ``refused`` is a problem code."""

    refused: str | None = None
    request_id: UUID | None = None
    audio_id: UUID | None = None
    requester_sub: UUID | None = None
    target_rev: int = 0
    current_rev: int = 0
    prior_status: str | None = None
    prior_error: str | None = None


async def claim_rediarize(
    conn: asyncpg.Connection, *, job_id: UUID, max_runs: int
) -> RediarizeClaim | None:
    """Check and mark a re-run as queued, in one transaction.

    ``None`` = no such job in this tenant. The checks and the write share a
    row lock, so two concurrent requests cannot both get through.
    """
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT j.status, j.diarization_status, j.diarization_error, j.diarization_runs,
                   j.diarization_rev, j.audio_id, j.requester_sub, a.status AS audio_status
            FROM transcription_jobs j
            LEFT JOIN audio_files a ON a.id = j.audio_id
            WHERE j.id = $1
            FOR UPDATE OF j
            """,
            job_id,
        )
        if row is None:
            return None
        rev = int(row["diarization_rev"] or 1)
        if row["status"] != "complete":
            return RediarizeClaim(refused="job_not_complete", current_rev=rev)
        if row["diarization_status"] in ("queued", "running"):
            return RediarizeClaim(refused="rediarize_in_progress", current_rev=rev)
        if int(row["diarization_runs"] or 0) >= max_runs:
            return RediarizeClaim(refused="rediarize_limit", current_rev=rev)
        if row["audio_status"] in (None, "deleted"):
            # Retention or erasure took the recording: there is nothing to
            # listen to again. (An object lost under a live row surfaces as
            # the worker's `audio_missing` on the re-run instead.)
            return RediarizeClaim(refused="audio_unavailable", current_rev=rev)
        request_id = await conn.fetchval(
            """
            UPDATE transcription_jobs
            SET diarization_status = 'queued',
                diarization_error = NULL,
                diarization_runs = diarization_runs + 1,
                diarization_updated_at = now(),
                diarization_request_id = gen_random_uuid()
            WHERE id = $1
            RETURNING diarization_request_id
            """,
            job_id,
        )
    return RediarizeClaim(
        request_id=request_id,
        audio_id=row["audio_id"],
        requester_sub=row["requester_sub"],
        target_rev=rev + 1,
        current_rev=rev,
        prior_status=row["diarization_status"],
        prior_error=row["diarization_error"],
    )


async def release_rediarize_claim(
    conn: asyncpg.Connection, *, job_id: UUID, claim: RediarizeClaim
) -> None:
    """The enqueue failed: put the row back as it was, run not counted."""
    await conn.execute(
        """
        UPDATE transcription_jobs
        SET diarization_status = $2,
            diarization_error = $3,
            diarization_runs = GREATEST(diarization_runs - 1, 0),
            diarization_updated_at = now(),
            diarization_request_id = NULL
        WHERE id = $1 AND diarization_status = 'queued' AND diarization_request_id = $4
        """,
        job_id,
        claim.prior_status,
        claim.prior_error,
        claim.request_id,
    )


@dataclass(slots=True)
class UndoOutcome:
    refused: str | None = None
    rev: int = 0
    # The labelling that was undone; the caller deletes its artifact.
    undone_uri: str | None = None


async def undo_rediarize(conn: asyncpg.Connection, *, job_id: UUID) -> UndoOutcome | None:
    """Swap back to the labelling the last re-run replaced — one step only.

    The names go back with it (the re-run saved them), and the revision
    moves FORWARD: edits made on the undone labelling must not come back
    to life on the restored one either.
    """
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT diarization_status, diarization_rev, result_storage_uri,
                   previous_result_storage_uri
            FROM transcription_jobs WHERE id = $1 FOR UPDATE
            """,
            job_id,
        )
        if row is None:
            return None
        rev = int(row["diarization_rev"] or 1)
        if row["diarization_status"] in ("queued", "running"):
            return UndoOutcome(refused="rediarize_in_progress", rev=rev)
        if row["previous_result_storage_uri"] is None:
            return UndoOutcome(refused="nothing_to_undo", rev=rev)
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET result_storage_uri = previous_result_storage_uri,
                previous_result_storage_uri = NULL,
                speaker_names = COALESCE(previous_speaker_names, '{}'::jsonb),
                previous_speaker_names = NULL,
                diarization_rev = diarization_rev + 1,
                diarization_status = 'complete',
                diarization_error = NULL,
                diarization_updated_at = now()
            WHERE id = $1
            """,
            job_id,
        )
    return UndoOutcome(rev=rev + 1, undone_uri=str(row["result_storage_uri"]))


@dataclass(slots=True)
class StaleRediarizeRow:
    id: UUID
    diarization_status: str
    requester_sub: UUID


async def list_stale_rediarize(
    conn: asyncpg.Connection,
    *,
    running_grace_seconds: float,
    queued_grace_seconds: float,
    limit: int,
) -> list[StaleRediarizeRow]:
    """Re-runs stranded mid-flight (a dead worker, a lost message)."""
    rows = await conn.fetch(
        """
        SELECT id, diarization_status, requester_sub
        FROM transcription_jobs
        WHERE (diarization_status = 'running' AND diarization_updated_at < now()
                   - make_interval(secs => $1::double precision))
           OR (diarization_status = 'queued'  AND diarization_updated_at < now()
                   - make_interval(secs => $2::double precision))
        ORDER BY diarization_updated_at
        LIMIT $3
        """,
        float(running_grace_seconds),
        float(queued_grace_seconds),
        limit,
    )
    return [
        StaleRediarizeRow(
            id=r["id"],
            diarization_status=str(r["diarization_status"]),
            requester_sub=r["requester_sub"],
        )
        for r in rows
    ]


async def fail_rediarize(
    conn: asyncpg.Connection,
    *,
    job_id: UUID,
    error: str,
    only_if_status: str,
    older_than_seconds: float = 0.0,
) -> bool:
    """Fail a re-run (never the job); conditional like :func:`fail_job` —
    on the status the sweep saw AND on it still being past the grace window,
    so a re-run that moved on between the scan and here is left alone."""
    row = await conn.fetchrow(
        """
        UPDATE transcription_jobs
        SET diarization_status = 'failed', diarization_error = $2,
            diarization_updated_at = now()
        WHERE id = $1 AND diarization_status = $3
          AND diarization_updated_at < now() - make_interval(secs => $4::double precision)
        RETURNING id
        """,
        job_id,
        error,
        only_if_status,
        float(older_than_seconds),
    )
    return row is not None


# ── Sprint 30: reset, capture context, learn loop ─────────────────────


async def revert_live_edits(conn: asyncpg.Connection, *, job_id: UUID, result_rev: int) -> int:
    """Revert every live edit of one revision; how many were reverted."""
    rows = await conn.fetch(
        """
        UPDATE transcription_speaker_edits SET reverted_at = now()
        WHERE job_id = $1 AND result_rev = $2 AND reverted_at IS NULL
        RETURNING id
        """,
        job_id,
        result_rev,
    )
    return len(rows)


async def all_edit_labels(conn: asyncpg.Connection, *, job_id: UUID) -> list[str]:
    """Every label any edit of this job ever named — reverted and older
    revisions included (label allocation must never reuse one)."""
    rows = await conn.fetch(
        "SELECT from_label, to_label FROM transcription_speaker_edits WHERE job_id = $1",
        job_id,
    )
    return [label for r in rows for label in (r["from_label"], r["to_label"]) if label]


async def name_sources(conn: asyncpg.Connection, *, job_id: UUID) -> dict[str, str]:
    """How each name came about (``typed``/``picklist``/``channel``/``cleared``…)."""
    raw = await conn.fetchval(
        "SELECT speaker_name_sources FROM transcription_jobs WHERE id = $1", job_id
    )
    return parse_speaker_names(raw)


def merge_name_sources(
    current: dict[str, str], *, names: dict[str, str], sources: dict[str, str]
) -> dict[str, str]:
    """The stored provenance after a rename (pure; the rules live here).

    A label whose name the platform set from the channel and that is no
    longer named becomes ``cleared`` — the one fact that must outlive the
    name, so the channel name is never re-applied. A label named by a
    person takes the source the client reported (``typed`` by default).
    """
    updated = dict(current)
    for label, source in current.items():
        if source == "channel" and label not in names:
            updated[label] = "cleared"
    for label in names:
        if label in sources:
            updated[label] = sources[label]
        elif label not in updated or updated[label] == "cleared":
            updated[label] = "typed"
    return updated


async def update_name_sources(
    conn: asyncpg.Connection,
    *,
    job_id: UUID,
    names: dict[str, str],
    sources: dict[str, str],
) -> dict[str, str]:
    """Persist :func:`merge_name_sources` for one job."""
    current = parse_speaker_names(
        await conn.fetchval(
            "SELECT speaker_name_sources FROM transcription_jobs WHERE id = $1", job_id
        )
    )
    updated = merge_name_sources(current, names=names, sources=sources)
    if updated != current:
        await conn.execute(
            "UPDATE transcription_jobs SET speaker_name_sources = $2::jsonb WHERE id = $1",
            job_id,
            json.dumps(updated),
        )
    return updated


MAX_DISMISSED_SUGGESTIONS = 32


async def dismissed_suggestions(
    conn: asyncpg.Connection, *, job_id: UUID, result_rev: int | None = None
) -> list[tuple[str, str]]:
    """Dismissed (label, name) pairs — of one labelling revision when
    ``result_rev`` is given. A re-run or undo re-numbers speakers, so a
    "no" said about SPEAKER_2 of revision 1 says nothing about revision 3's
    SPEAKER_2 (pre-scoping entries count as revision 1)."""
    raw = await conn.fetchval(
        "SELECT dismissed_name_suggestions FROM transcription_jobs WHERE id = $1", job_id
    )
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    return [
        (str(item["label"]), str(item["name"]))
        for item in raw
        if isinstance(item, dict)
        and "label" in item
        and "name" in item
        and (result_rev is None or int(item.get("rev", 1)) == result_rev)
    ]


async def dismiss_suggestion(
    conn: asyncpg.Connection, *, job_id: UUID, label: str, name: str
) -> bool | None:
    """Remember a person's "no" for the CURRENT labelling (set semantics,
    ≤ 32 pairs). ``None`` = no such job in this tenant; ``False`` = already
    dismissed (idempotent)."""
    row = await conn.fetchrow(
        """
        SELECT dismissed_name_suggestions, diarization_rev
        FROM transcription_jobs WHERE id = $1 FOR UPDATE
        """,
        job_id,
    )
    if row is None:
        return None
    rev = int(row["diarization_rev"] or 1)
    raw = row["dismissed_name_suggestions"]
    items = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    key = (label, " ".join(name.casefold().split()), rev)
    for item in items:
        if (
            item.get("label"),
            " ".join(str(item.get("name", "")).casefold().split()),
            int(item.get("rev", 1)),
        ) == key:
            return False
    items = [*items, {"label": label, "name": name, "rev": rev}][-MAX_DISMISSED_SUGGESTIONS:]
    await conn.execute(
        "UPDATE transcription_jobs SET dismissed_name_suggestions = $2::jsonb WHERE id = $1",
        job_id,
        json.dumps(items),
    )
    return True


@dataclass(slots=True)
class AudioState:
    audio_id: UUID
    audio_status: str
    diarization_runs: int
    diarization_status: str | None


async def audio_state(conn: asyncpg.Connection, *, job_id: UUID) -> AudioState | None:
    """What decides whether a re-run is possible, from one row read: the
    recording's status and the job's re-run budget and state."""
    row = await conn.fetchrow(
        """
        SELECT a.id, a.status, j.diarization_runs, j.diarization_status
        FROM transcription_jobs j JOIN audio_files a ON a.id = j.audio_id
        WHERE j.id = $1
        """,
        job_id,
    )
    if row is None:
        return None
    return AudioState(
        audio_id=row["id"],
        audio_status=str(row["status"]),
        diarization_runs=int(row["diarization_runs"] or 0),
        diarization_status=row["diarization_status"],
    )


async def name_candidates(conn: asyncpg.Connection, *, job_id: UUID) -> list[str]:
    """Names offered for renaming (content: result view only, never the
    job view that tenant admins list for stats)."""
    raw = await conn.fetchval(
        "SELECT speaker_name_candidates FROM transcription_jobs WHERE id = $1", job_id
    )
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [str(v) for v in raw] if isinstance(raw, list) else []


async def mark_result_read(conn: asyncpg.Connection, *, job_id: UUID) -> bool:
    """Record the first time the transcript was opened; True only that once."""
    row = await conn.fetchrow(
        """
        UPDATE transcription_jobs SET result_first_read_at = now()
        WHERE id = $1 AND result_first_read_at IS NULL
        RETURNING id
        """,
        job_id,
    )
    return row is not None


async def has_corrections(conn: asyncpg.Connection, *, job_id: UUID) -> bool:
    """Whether a person has corrected this job's speakers before (any edit
    ever, or a re-run) — so "first correction" is counted once per job."""
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (SELECT 1 FROM transcription_speaker_edits WHERE job_id = $1)
                OR COALESCE((SELECT diarization_runs > 0 FROM transcription_jobs
                             WHERE id = $1), false)
            """,
            job_id,
        )
    )


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
        speaker_names=parse_speaker_names(row.get("speaker_names")),
        diarization_rev=int(row.get("diarization_rev") or 1),
        diarization_status=row.get("diarization_status"),
        diarization_error=row.get("diarization_error"),
        diarization_runs=int(row.get("diarization_runs") or 0),
        can_undo_rediarize=row.get("previous_result_storage_uri") is not None,
        vocabulary_hint=row.get("vocabulary_hint"),
    )


def parse_speaker_names(raw: object) -> dict[str, str]:
    """``speaker_names`` column → dict. No jsonb codec is registered on
    the pool, so asyncpg hands the column back as text; rows that predate
    migration 0018 (or a NULL from a test stub) read as empty."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v}
