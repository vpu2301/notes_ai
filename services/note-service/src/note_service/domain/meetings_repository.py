"""``note_meetings`` + ``note_user_line_times`` (migration 0049).

The capture's lifecycle sidecar. Every function takes an RLS-scoped
connection from ``tenant_connection`` — the tenant predicate is the
policy's, not a WHERE clause here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import asyncpg

# The states a capture passes through. `recording` → `uploading` →
# `transcribing` → `generating` → `ready`, with `no_audio` (discarded or
# never recorded) and `failed` as the two ways out.
STATES: Final = (
    "recording",
    "uploading",
    "transcribing",
    "generating",
    "ready",
    "no_audio",
    "failed",
)
# States the sweeper may reclaim: the client stopped talking to us before
# there was anything to transcribe.
STALE_STATES: Final = ("recording", "uploading")

MEETING_TYPES: Final = ("auto", "client", "team", "sales", "one_on_one", "interview")


@dataclass(slots=True)
class MeetingRow:
    note_id: UUID
    tenant_id: UUID
    created_by: UUID
    state: str
    client_capture_id: UUID
    asr_job_id: UUID | None
    meeting_type: str
    started_at: datetime
    calendar_context: dict[str, Any]
    # Sprint 36 — which series this meeting belongs to, and what the note
    # before it was. None for a one-off.
    series_key: str | None = None
    series_source: str | None = None
    previous_note_id: UUID | None = None
    # What detection thought, and how. The template is never switched on
    # the strength of it without a user action.
    meeting_type_detected: str | None = None
    detected_by: str | None = None


def _row(record: asyncpg.Record) -> MeetingRow:
    raw = record["calendar_context"]
    return MeetingRow(
        note_id=record["note_id"],
        tenant_id=record["tenant_id"],
        created_by=record["created_by"],
        state=str(record["state"]),
        client_capture_id=record["client_capture_id"],
        asr_job_id=record["asr_job_id"],
        meeting_type=str(record["meeting_type"]),
        started_at=record["started_at"],
        calendar_context=json.loads(raw) if isinstance(raw, str) else (raw or {}),
        series_key=record["series_key"],
        series_source=record["series_source"],
        previous_note_id=record["previous_note_id"],
        meeting_type_detected=record["meeting_type_detected"],
        detected_by=record["detected_by"],
    )


_COLUMNS: Final = (
    "note_id, tenant_id, created_by, state, client_capture_id, asr_job_id, "
    "meeting_type, started_at, calendar_context, series_key, series_source, "
    "previous_note_id, meeting_type_detected, detected_by"
)


async def create(
    conn: asyncpg.Connection,
    *,
    note_id: UUID,
    tenant_id: UUID,
    created_by: UUID,
    client_capture_id: UUID,
    meeting_type: str,
    started_at: datetime,
    calendar_context: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO note_meetings (
            note_id, tenant_id, created_by, state, client_capture_id,
            meeting_type, started_at, calendar_context
        )
        VALUES ($1, $2, $3, 'recording', $4, $5, $6, $7::jsonb)
        """,
        note_id,
        tenant_id,
        created_by,
        client_capture_id,
        meeting_type,
        started_at,
        json.dumps(calendar_context),
    )


async def fetch(conn: asyncpg.Connection, *, note_id: UUID) -> MeetingRow | None:
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM note_meetings WHERE note_id = $1", note_id
    )
    return _row(record) if record is not None else None


async def find_by_capture(
    conn: asyncpg.Connection, *, client_capture_id: UUID
) -> MeetingRow | None:
    """The idempotency lookup: the same capture retried, or a second
    device that started from the same event."""
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM note_meetings WHERE client_capture_id = $1",
        client_capture_id,
    )
    return _row(record) if record is not None else None


async def set_state(conn: asyncpg.Connection, *, note_id: UUID, state: str) -> None:
    await conn.execute("UPDATE note_meetings SET state = $2 WHERE note_id = $1", note_id, state)


async def bind_job(conn: asyncpg.Connection, *, note_id: UUID, asr_job_id: UUID) -> None:
    """Point the capture at its transcription job and move to
    ``transcribing``. ``notes.source_asr_job_id`` is set in the same
    statement pair by the caller, inside one transaction."""
    await conn.execute(
        """
        UPDATE note_meetings
        SET asr_job_id = $2, state = 'transcribing'
        WHERE note_id = $1
        """,
        note_id,
        asr_job_id,
    )


# ── Line times ──────────────────────────────────────────────────────


async def put_line_times(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    lines: list[tuple[str, int]],
) -> int:
    """Upsert-if-absent: the FIRST keystroke of a line is what anchors it,
    so a later report of the same key is ignored. Returns rows written.

    One round trip — the clients flush a whole batch with each autosave.
    """
    if not lines:
        return 0
    keys = [key for key, _ in lines]
    offsets = [offset for _, offset in lines]
    written: int = await conn.fetchval(
        """
        WITH ins AS (
            INSERT INTO note_user_line_times (tenant_id, note_id, line_key, offset_ms)
            SELECT $1, $2, k, o
            FROM unnest($3::text[], $4::int[]) AS t(k, o)
            ON CONFLICT (note_id, line_key) DO NOTHING
            RETURNING 1
        )
        SELECT count(*) FROM ins
        """,
        tenant_id,
        note_id,
        keys,
        offsets,
    )
    return int(written)


async def line_times(conn: asyncpg.Connection, *, note_id: UUID) -> dict[str, int]:
    rows = await conn.fetch(
        "SELECT line_key, offset_ms FROM note_user_line_times WHERE note_id = $1",
        note_id,
    )
    return {str(r["line_key"]): int(r["offset_ms"]) for r in rows}


# ── Sweeper ─────────────────────────────────────────────────────────


async def sweep_stale(conn: asyncpg.Connection, *, older_than_hours: int) -> list[UUID]:
    """``recording``/``uploading`` older than the cutoff → ``no_audio``.

    A crashed client, a tab closed mid-meeting, a phone that never came
    back. Nothing is deleted: the note keeps whatever the author typed and
    becomes an ordinary note.
    """
    rows = await conn.fetch(
        """
        UPDATE note_meetings
        SET state = 'no_audio'
        WHERE state = ANY($1::text[])
          AND updated_at < now() - make_interval(hours => $2)
        RETURNING note_id
        """,
        list(STALE_STATES),
        older_than_hours,
    )
    return [r["note_id"] for r in rows]


# ── Series and carry-over (Sprint 36, migration 0051) ───────────────


async def set_series(
    conn: asyncpg.Connection,
    *,
    note_id: UUID,
    series_key: str | None,
    series_source: str | None,
    previous_note_id: UUID | None,
) -> None:
    await conn.execute(
        """
        UPDATE note_meetings
        SET series_key = $2, series_source = $3, previous_note_id = $4
        WHERE note_id = $1
        """,
        note_id,
        series_key,
        series_source,
        previous_note_id,
    )


async def previous_in_series(
    conn: asyncpg.Connection, *, series_key: str, before: datetime, exclude: UUID
) -> list[UUID]:
    """Notes in this series that started earlier, newest first.

    A LIST rather than one row on purpose: the caller checks each against
    the author's own visibility and takes the newest it may read, so a
    colleague's private note does not blank out the carry-over (ADR-0057).
    """
    rows = await conn.fetch(
        """
        SELECT note_id FROM note_meetings
        WHERE series_key = $1 AND started_at < $2 AND note_id <> $3
        ORDER BY started_at DESC
        LIMIT 10
        """,
        series_key,
        before,
        exclude,
    )
    return [r["note_id"] for r in rows]


async def set_detected_type(
    conn: asyncpg.Connection, *, note_id: UUID, detected: str, detected_by: str
) -> None:
    await conn.execute(
        "UPDATE note_meetings SET meeting_type_detected = $2, detected_by = $3 WHERE note_id = $1",
        note_id,
        detected,
        detected_by,
    )


async def set_meeting_type(conn: asyncpg.Connection, *, note_id: UUID, meeting_type: str) -> None:
    await conn.execute(
        "UPDATE note_meetings SET meeting_type = $2 WHERE note_id = $1", note_id, meeting_type
    )


async def put_carried_items(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    from_note_id: UUID,
    items: list[tuple[str, int]],
) -> int:
    """Insert the carried items once. Re-running is a no-op: the author
    may have ticked or dropped some since, and re-opening them would
    undo their decision."""
    if not items:
        return 0
    written: int = await conn.fetchval(
        """
        WITH ins AS (
            INSERT INTO note_carried_items
                (tenant_id, note_id, from_note_id, item_key, position, state)
            SELECT $1, $2, $3, k, p, 'open'
            FROM unnest($4::text[], $5::int[]) AS t(k, p)
            ON CONFLICT (note_id, from_note_id, item_key) DO NOTHING
            RETURNING 1
        )
        SELECT count(*) FROM ins
        """,
        tenant_id,
        note_id,
        from_note_id,
        [key for key, _ in items],
        [pos for _, pos in items],
    )
    return int(written)


async def carried_items(conn: asyncpg.Connection, *, note_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT from_note_id, item_key, position, state, done_quote,
               done_start_ms, done_end_ms, done_speaker
        FROM note_carried_items
        WHERE note_id = $1
        ORDER BY position
        """,
        note_id,
    )


async def set_carried_state(
    conn: asyncpg.Connection,
    *,
    note_id: UUID,
    item_key: str,
    state: str,
    done_quote: str | None = None,
    done_start_ms: int | None = None,
    done_end_ms: int | None = None,
    done_speaker: str | None = None,
) -> bool:
    row = await conn.fetchrow(
        """
        UPDATE note_carried_items
        SET state = $3, done_quote = $4, done_start_ms = $5,
            done_end_ms = $6, done_speaker = $7
        WHERE note_id = $1 AND item_key = $2
        RETURNING item_key
        """,
        note_id,
        item_key,
        state,
        done_quote,
        done_start_ms,
        done_end_ms,
        done_speaker,
    )
    return row is not None
