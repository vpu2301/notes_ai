"""``note_generations`` + ``note_generated_items``.

Every function takes an RLS-scoped connection; the tenant predicate is
the policy's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import asyncpg

from .meeting_doc.verify import VerifiedFact

QUEUED: Final = "queued"
RUNNING: Final = "running"
PARTIAL: Final = "partial"
COMPLETE: Final = "complete"
FAILED: Final = "failed"
SUPERSEDED: Final = "superseded"
LIVE_STATUSES: Final = (QUEUED, RUNNING)


@dataclass(slots=True)
class GenerationRow:
    id: UUID
    note_id: UUID
    job_id: UUID
    requested_by: UUID
    reason: str
    status: str
    step: str | None
    windows_total: int | None
    windows_done: int | None
    windows_failed: int | None
    failed_ranges: list[list[int]]
    prompt_version: str
    backend: str | None
    model_id: str | None
    transcript_rev: int
    snapshot_key: str | None
    stats: dict[str, Any]
    error_kind: str | None
    created_at: datetime
    finished_at: datetime | None


_COLUMNS: Final = (
    "id, note_id, job_id, requested_by, reason, status, step, windows_total, "
    "windows_done, windows_failed, failed_ranges, prompt_version, backend, "
    "model_id, transcript_rev, snapshot_key, stats, error_kind, created_at, finished_at"
)


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    return json.loads(value) if isinstance(value, str) else value


def _row(record: asyncpg.Record) -> GenerationRow:
    return GenerationRow(
        id=record["id"],
        note_id=record["note_id"],
        job_id=record["job_id"],
        requested_by=record["requested_by"],
        reason=str(record["reason"]),
        status=str(record["status"]),
        step=record["step"],
        windows_total=record["windows_total"],
        windows_done=record["windows_done"],
        windows_failed=record["windows_failed"],
        failed_ranges=_loads(record["failed_ranges"], []),
        prompt_version=str(record["prompt_version"]),
        backend=record["backend"],
        model_id=record["model_id"],
        transcript_rev=int(record["transcript_rev"]),
        snapshot_key=record["snapshot_key"],
        stats=_loads(record["stats"], {}),
        error_kind=record["error_kind"],
        created_at=record["created_at"],
        finished_at=record["finished_at"],
    )


async def create(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    job_id: UUID,
    requested_by: UUID,
    reason: str,
    prompt_version: str,
    transcript_rev: int,
    snapshot_key: str | None,
    generation_id: UUID | None = None,
) -> UUID:
    """Start a run. Raises ``UniqueViolationError`` when one is already live (the
    regenerate route's 409). ``generation_id`` MUST be the id the snapshot was
    sealed with (AAD + object key), or the worker can never unwrap it."""
    stored: UUID = await conn.fetchval(
        """
        INSERT INTO note_generations (
            id, tenant_id, note_id, job_id, requested_by, reason, status,
            prompt_version, transcript_rev, snapshot_key
        )
        VALUES (COALESCE($9, gen_random_uuid()), $1, $2, $3, $4, $5, 'queued', $6, $7, $8)
        RETURNING id
        """,
        tenant_id,
        note_id,
        job_id,
        requested_by,
        reason,
        prompt_version,
        transcript_rev,
        snapshot_key,
        generation_id,
    )
    return stored


async def fetch(conn: asyncpg.Connection, *, generation_id: UUID) -> GenerationRow | None:
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM note_generations WHERE id = $1", generation_id
    )
    return _row(record) if record is not None else None


async def latest_for_note(conn: asyncpg.Connection, *, note_id: UUID) -> GenerationRow | None:
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM note_generations WHERE note_id = $1 "
        "ORDER BY created_at DESC LIMIT 1",
        note_id,
    )
    return _row(record) if record is not None else None


async def last_written(
    conn: asyncpg.Connection, *, note_id: UUID, before: UUID
) -> GenerationRow | None:
    """The last run that actually wrote something (superseded runs count): its
    `section_hashes` say whether a section is still ours to rewrite."""
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM note_generations "
        "WHERE note_id = $1 AND id <> $2 "
        "AND status IN ('complete','partial','superseded') "
        "ORDER BY created_at DESC LIMIT 1",
        note_id,
        before,
    )
    return _row(record) if record is not None else None


async def mark(
    conn: asyncpg.Connection,
    *,
    generation_id: UUID,
    status: str | None = None,
    step: str | None = None,
    windows_total: int | None = None,
    windows_done: int | None = None,
    windows_failed: int | None = None,
    failed_ranges: list[list[int]] | None = None,
    backend: str | None = None,
    model_id: str | None = None,
    stats: dict[str, Any] | None = None,
    error_kind: str | None = None,
    finished: bool = False,
) -> None:
    """Update whatever was passed; leave the rest alone."""
    sets: list[str] = []
    args: list[Any] = []

    def add(column: str, value: Any, cast: str = "") -> None:
        args.append(value)
        sets.append(f"{column} = ${len(args) + 1}{cast}")

    if status is not None:
        add("status", status)
    if step is not None:
        add("step", step)
    if windows_total is not None:
        add("windows_total", windows_total)
    if windows_done is not None:
        add("windows_done", windows_done)
    if windows_failed is not None:
        add("windows_failed", windows_failed)
    if failed_ranges is not None:
        add("failed_ranges", json.dumps(failed_ranges), "::jsonb")
    if backend is not None:
        add("backend", backend)
    if model_id is not None:
        add("model_id", model_id)
    if stats is not None:
        add("stats", json.dumps(stats), "::jsonb")
    if error_kind is not None:
        add("error_kind", error_kind)
    if finished:
        sets.append("finished_at = now()")
    if not sets:
        return
    await conn.execute(
        f"UPDATE note_generations SET {', '.join(sets)} WHERE id = $1", generation_id, *args
    )


async def supersede_previous(conn: asyncpg.Connection, *, note_id: UUID, keep: UUID) -> None:
    """Older runs' items stop being the note's evidence."""
    await conn.execute(
        """
        UPDATE note_generated_items SET placement = 'superseded'
        WHERE note_id = $1 AND generation_id <> $2
          AND placement IN ('written', 'suggested', 'evidence')
        """,
        note_id,
        keep,
    )


async def put_items(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    generation_id: UUID,
    facts: list[tuple[VerifiedFact, str, str]],
    audience_of: Any = None,
) -> int:
    """``[(fact, section_key, placement)]`` → rows; idempotent on ``(note_id, generation_id, item_key)``."""
    if not facts:
        return 0
    written = 0
    for fact, section_key, placement in facts:
        result = await conn.execute(
            """
            INSERT INTO note_generated_items (
                tenant_id, note_id, generation_id, item_key, kind, section_key,
                text, owner_label, due_text, due_date, explicit, confidence,
                flags, quote, start_ms, end_ms, speaker_label, speaker_name,
                placement, audience
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::text[],$14,$15,$16,$17,$18,$19,$20)
            ON CONFLICT (note_id, generation_id, item_key) DO NOTHING
            """,
            tenant_id,
            note_id,
            generation_id,
            fact.item_key,
            fact.kind,
            section_key,
            fact.text,
            fact.owner_label,
            fact.due_text,
            fact.due_date,
            fact.explicit,
            fact.confidence,
            fact.flags,
            fact.quote,
            fact.start_ms,
            fact.end_ms,
            fact.speaker_label,
            fact.speaker_name,
            placement,
            # Internal-by-kind never leaves the workspace, whatever the note's sharing says.
            audience_of(fact) if audience_of else "all",
        )
        if result.endswith(" 1"):
            written += 1
    return written


async def put_lines(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    generation_id: UUID,
    rows: list[dict[str, Any]],
) -> int:
    """One row per written LINE: text, kind, citations, evidence of the first cited
    fact. Idempotent like ``put_items``; ``corrections`` and ``mentions`` are JSON lists."""
    written = 0
    for row in rows:
        result = await conn.execute(
            """
            INSERT INTO note_generated_items (
                tenant_id, note_id, generation_id, item_key, kind, section_key,
                text, owner_label, due_text, due_date, explicit, confidence,
                flags, quote, start_ms, end_ms, speaker_label, speaker_name,
                placement, audience, cites, certainty, attributed_to, corrections, mentions,
                parent_key, payload
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::text[],$14,$15,$16,$17,$18,
                    $19,$20,$21::text[],$22,$23,$24::jsonb,$25::jsonb,$26,$27::jsonb)
            ON CONFLICT (note_id, generation_id, item_key) DO NOTHING
            """,
            tenant_id,
            note_id,
            generation_id,
            row["item_key"],
            row["kind"],
            row["section_key"],
            row["text"],
            row.get("owner_label"),
            row.get("due_text"),
            row.get("due_date"),
            bool(row.get("explicit", False)),
            float(row.get("confidence", 0.7)),
            list(row.get("flags") or []),
            row["quote"],
            int(row["start_ms"]),
            int(row["end_ms"]),
            row.get("speaker_label"),
            row.get("speaker_name"),
            row["placement"],
            row.get("audience", "all"),
            list(row.get("cites") or [])[:16],
            row.get("certainty"),
            row.get("attributed_to"),
            json.dumps(list(row.get("corrections") or [])[:8]),
            json.dumps(list(row.get("mentions") or [])[:8]),
            row.get("parent_key"),
            json.dumps(row["payload"]) if row.get("payload") else None,
        )
        if result.endswith(" 1"):
            written += 1
    return written


async def items_for_note(
    conn: asyncpg.Connection, *, note_id: UUID, current_only: bool = False
) -> list[asyncpg.Record]:
    """The note's generated rows; ``current_only``: the latest run that wrote."""
    current = (
        "AND generation_id = (SELECT id FROM note_generations WHERE note_id = $1 "
        "AND status IN ('complete','partial') ORDER BY created_at DESC LIMIT 1)"
        if current_only
        else ""
    )
    return await conn.fetch(
        f"""
        SELECT item_key, kind, section_key, text, owner_label, due_text, due_date,
               explicit, confidence, flags, quote, start_ms, end_ms,
               speaker_label, speaker_name, placement, audience,
               cites, certainty, attributed_to, corrections, mentions, parent_key, payload
        FROM note_generated_items
        WHERE note_id = $1 AND placement IN ('written', 'suggested', 'evidence') {current}
        ORDER BY start_ms
        """,
        note_id,
    )


async def regenerations_today(conn: asyncpg.Connection, *, note_id: UUID) -> int:
    """Runs this note has had in the last day (the regenerate cap)."""
    total: int = await conn.fetchval(
        "SELECT count(*) FROM note_generations "
        "WHERE note_id = $1 AND created_at > now() - interval '1 day'",
        note_id,
    )
    return int(total)


async def internal_item_keys(conn: asyncpg.Connection, *, note_id: UUID) -> set[str]:
    """Keys of lines the engine marked internal by kind; the client document drops them."""
    rows = await conn.fetch(
        """
        SELECT item_key FROM note_generated_items
        WHERE note_id = $1 AND audience = 'internal'
          AND placement IN ('written', 'suggested')
        """,
        note_id,
    )
    return {str(r["item_key"]) for r in rows}


async def flag_counts(conn: asyncpg.Connection, *, note_id: UUID) -> dict[str, int]:
    """``{flag: how many written lines carry it}``. Counts only."""
    rows = await conn.fetch(
        """
        SELECT unnest(flags) AS flag, count(*) AS n
        FROM note_generated_items
        WHERE note_id = $1 AND placement = 'written'
        GROUP BY 1
        """,
        note_id,
    )
    return {str(r["flag"]): int(r["n"]) for r in rows}


async def suggested_count(conn: asyncpg.Connection, *, note_id: UUID) -> int:
    total: int = await conn.fetchval(
        "SELECT count(*) FROM note_generated_items WHERE note_id = $1 AND placement = 'suggested'",
        note_id,
    )
    return int(total)


async def clear_snapshot(conn: asyncpg.Connection, *, generation_id: UUID) -> str | None:
    """Forget where the transcript snapshot was; returns the key. The caller deletes the object."""
    return await conn.fetchval(
        "UPDATE note_generations SET snapshot_key = NULL "
        "WHERE id = $1 AND snapshot_key IS NOT NULL RETURNING snapshot_key",
        generation_id,
    )


async def stale_snapshots(
    conn: asyncpg.Connection, *, older_than_hours: int = 24, limit: int = 500
) -> list[tuple[UUID, str]]:
    """Snapshots still on disk after the generation that needed them (worker died first)."""
    rows = await conn.fetch(
        f"""
        SELECT id, snapshot_key FROM note_generations
        WHERE snapshot_key IS NOT NULL
          AND created_at < now() - make_interval(hours => $1)
          AND status <> '{QUEUED}'
        ORDER BY created_at
        LIMIT $2
        """,
        older_than_hours,
        limit,
    )
    return [(r["id"], r["snapshot_key"]) for r in rows]
