"""``note_synthesis_jobs`` repository (spec item 1).

Thin SQL wrapper, run on a tenant-scoped connection (``db.tenant_connection``)
so RLS does the isolation. A synthesis job is a *read-only* artefact: it
records the per-section synthesised text for one (note, version, section
set, language) so the UI can diff/revert. It never mutates the note.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg


@dataclass(slots=True)
class SynthesisJobRow:
    id: UUID
    note_id: UUID
    version_number: int
    language: str
    status: str
    sections: list[dict[str, Any]]


def _decode_sections(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    return list(raw) if isinstance(raw, list) else []


def _row_to_job(row: asyncpg.Record) -> SynthesisJobRow:
    return SynthesisJobRow(
        id=row["id"],
        note_id=row["note_id"],
        version_number=int(row["version_number"]),
        language=row["language"],
        status=row["status"],
        sections=_decode_sections(row["sections_jsonb"]),
    )


async def find_completed_job(
    conn: asyncpg.Connection, *, note_id: UUID, request_hash: str
) -> SynthesisJobRow | None:
    """Idempotency lookup by the request hash (per tenant via RLS)."""
    row = await conn.fetchrow(
        """
        SELECT id, note_id, version_number, language, status, sections_jsonb
        FROM note_synthesis_jobs
        WHERE note_id = $1 AND request_hash = $2 AND status = 'completed'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        note_id,
        request_hash,
    )
    return _row_to_job(row) if row is not None else None


async def fetch_job(
    conn: asyncpg.Connection, *, job_id: UUID, note_id: UUID
) -> SynthesisJobRow | None:
    row = await conn.fetchrow(
        """
        SELECT id, note_id, version_number, language, status, sections_jsonb
        FROM note_synthesis_jobs
        WHERE id = $1 AND note_id = $2
        """,
        job_id,
        note_id,
    )
    return _row_to_job(row) if row is not None else None


async def insert_job(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    version_number: int,
    language: str,
    sections: list[dict[str, Any]],
    request_hash: str,
    status: str = "completed",
) -> UUID:
    """Persist a completed job. On the idempotency unique violation, return
    the existing job's id instead (concurrent identical request)."""
    try:
        job_id: UUID = await conn.fetchval(
            """
            INSERT INTO note_synthesis_jobs (
                tenant_id, note_id, version_number, language,
                sections_jsonb, request_hash, status
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
            RETURNING id
            """,
            tenant_id,
            note_id,
            version_number,
            language,
            json.dumps(sections),
            request_hash,
            status,
        )
        return job_id
    except asyncpg.UniqueViolationError:
        existing = await find_completed_job(conn, note_id=note_id, request_hash=request_hash)
        if existing is None:
            raise
        return existing.id
