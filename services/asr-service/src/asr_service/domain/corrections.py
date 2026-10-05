"""Sprint TQ3 T2 — the spelling overlay's storage and lifecycle.

``transcript_corrections`` (migration 0066) holds what :mod:`entity_unify`
proposed for a job; the result view applies the accepted rows on every read.
The unifier runs once per job, on the first result read after completion
(``ensure_planned``) — after diarization, before anyone sees the text — and
again only on ``POST …/corrections:recompute``.

The workspace glossary is read here, read-only, from ``workspace_glossary``
(note-service's table, same database, same RLS — the precedent is
note-service reading ``transcription_jobs``). Calendar attendees are the
job's ``speaker_name_candidates``; the hint is ``vocabulary_hint``.

Every row is content: nothing here logs a spelling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg
from opentelemetry import metrics

from asr_models import EntityCorrectionView, TranscriptionOutput

from . import entity_unify

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.asr.service.corrections")
_unify_total = _meter.create_counter(
    "mdx_asr_entity_unify_total",
    description="Spelling-unifier runs by outcome (done | skipped_budget | error)",
    unit="1",
)
_unify_seconds = _meter.create_histogram(
    "mdx_asr_entity_unify_seconds",
    description="Wall time of one spelling-unifier run",
    unit="s",
)


@dataclass(frozen=True)
class Row:
    id: UUID
    from_forms: tuple[str, ...]
    to_text: str
    occurrences: tuple[dict[str, Any], ...]
    source: str
    confidence: float
    status: str
    decided_by: UUID | None

    def view(self) -> EntityCorrectionView:
        return EntityCorrectionView(
            id=self.id,
            from_forms=list(self.from_forms),
            to_text=self.to_text,
            occurrences_count=len(self.occurrences),
            source=self.source,  # type: ignore[arg-type]
            confidence=self.confidence,
            status=self.status,  # type: ignore[arg-type]
            decided=self.decided_by is not None,
        )

    def applied(self) -> entity_unify.Applied:
        return entity_unify.Applied(self.to_text, self.from_forms, self.occurrences)


def _row(r: Any) -> Row:
    occ = r["occurrences"]
    if isinstance(occ, str):
        occ = json.loads(occ)
    return Row(
        id=r["id"],
        from_forms=tuple(r["from_forms"]),
        to_text=r["to_text"],
        occurrences=tuple(occ),
        source=r["source"],
        confidence=float(r["confidence"]),
        status=r["status"],
        decided_by=r["decided_by"],
    )


@dataclass(frozen=True)
class JobState:
    status: str | None
    rev: int
    hint: str | None


async def job_state(conn: asyncpg.Connection, *, job_id: UUID) -> JobState | None:
    try:
        r = await conn.fetchrow(
            "SELECT entity_unify_status, corrections_rev, vocabulary_hint"
            " FROM transcription_jobs WHERE id = $1",
            job_id,
        )
    except asyncpg.UndefinedColumnError:
        return None  # migration 0066 not applied: no overlay, nothing breaks
    if r is None:
        return None
    return JobState(r["entity_unify_status"], int(r["corrections_rev"] or 0), r["vocabulary_hint"])


async def list_rows(conn: asyncpg.Connection, *, job_id: UUID) -> list[Row]:
    try:
        rows = await conn.fetch(
            "SELECT * FROM transcript_corrections WHERE job_id = $1 ORDER BY to_text", job_id
        )
    except asyncpg.UndefinedTableError:
        return []
    return [_row(r) for r in rows]


async def glossary_terms(conn: asyncpg.Connection) -> list[tuple[str, list[str]]]:
    """The workspace's live glossary terms and their misspellings."""
    try:
        rows = await conn.fetch(
            "SELECT term, heard_as FROM workspace_glossary WHERE deleted_at IS NULL"
        )
    except (asyncpg.UndefinedTableError, asyncpg.InsufficientPrivilegeError):
        return []
    return [(r["term"], list(r["heard_as"] or [])) for r in rows]


def hint_terms(hint: str | None) -> list[str]:
    return [t.strip() for t in (hint or "").split(",") if t.strip()]


def _budget(audio_seconds: float, *, per_hour: float, floor: float) -> float:
    return max(floor, per_hour * audio_seconds / 3600.0)


async def plan_for(
    output: TranscriptionOutput,
    *,
    glossary: list[tuple[str, list[str]]],
    attendees: list[str],
    hint: str | None,
    auto_apply: bool,
    per_hour: float,
    floor: float,
) -> tuple[str, list[entity_unify.Proposal], int]:
    """``(status, proposals, discarded)`` — off the event loop, within the
    budget (a run over it is dropped: ``skipped_budget``)."""
    audio_s = max((s.end_ms for s in output.segments), default=0) / 1000.0
    started = time.monotonic()
    try:
        result = await asyncio.to_thread(
            entity_unify.plan,
            output,
            language=output.language,
            glossary=glossary,
            attendees=attendees,
            hint_terms=hint_terms(hint),
            auto_apply=auto_apply,
        )
    except Exception as exc:  # noqa: BLE001 — a failed unifier never costs the transcript
        logger.warning("asr.entity_unify_failed", extra={"error_class": type(exc).__name__})
        _unify_total.add(1, {"outcome": "error"})
        return "error", [], 0
    elapsed = time.monotonic() - started
    _unify_seconds.record(elapsed)
    if elapsed > _budget(audio_s, per_hour=per_hour, floor=floor):
        _unify_total.add(1, {"outcome": "skipped_budget"})
        logger.warning(
            "asr.entity_unify_over_budget",
            extra={"seconds": round(elapsed, 3), "audio_seconds": round(audio_s)},
        )
        return "skipped_budget", [], 0
    _unify_total.add(1, {"outcome": "done"})
    return "done", result.proposals, result.discarded


async def store(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    job_id: UUID,
    status: str,
    proposals: list[entity_unify.Proposal],
) -> bool:
    """Write a plan and the job's status, once. Returns False when another
    reader got there first (the status was set meanwhile).

    A row a person decided (``decided_by`` set) is never overwritten by a
    recompute; the system's own rows are refreshed."""
    claimed = await conn.fetchval(
        "UPDATE transcription_jobs SET entity_unify_status = $2,"
        " corrections_rev = corrections_rev + 1"
        " WHERE id = $1 AND entity_unify_status IS NULL RETURNING corrections_rev",
        job_id,
        status,
    )
    if claimed is None:
        return False
    await _upsert(conn, tenant_id=tenant_id, job_id=job_id, proposals=proposals)
    return True


async def _upsert(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    job_id: UUID,
    proposals: list[entity_unify.Proposal],
) -> None:
    for p in proposals:
        await conn.execute(
            """
            INSERT INTO transcript_corrections
                (tenant_id, job_id, kind, from_forms, to_text, occurrences, source,
                 confidence, status)
            VALUES ($1, $2, 'entity', $3, $4, $5::jsonb, $6, $7, $8)
            ON CONFLICT (job_id, to_text) DO UPDATE SET
                from_forms = EXCLUDED.from_forms,
                occurrences = EXCLUDED.occurrences,
                source = EXCLUDED.source,
                confidence = EXCLUDED.confidence,
                status = EXCLUDED.status,
                updated_at = now()
            WHERE transcript_corrections.decided_by IS NULL
            """,
            tenant_id,
            job_id,
            list(p.from_forms),
            p.to_text,
            json.dumps(list(p.occurrences)),
            p.source,
            p.confidence,
            p.status,
        )


async def recompute(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    job_id: UUID,
    status: str,
    proposals: list[entity_unify.Proposal],
) -> int:
    """``POST …/corrections:recompute``: refresh the system's rows, keep the
    people's decisions; the new ``corrections_rev``."""
    await _upsert(conn, tenant_id=tenant_id, job_id=job_id, proposals=proposals)
    rev = await conn.fetchval(
        "UPDATE transcription_jobs SET entity_unify_status = $2,"
        " corrections_rev = corrections_rev + 1 WHERE id = $1 RETURNING corrections_rev",
        job_id,
        status,
    )
    return int(rev or 0)


class StaleRevError(Exception):
    pass


class ToTextTakenError(Exception):
    pass


async def decide(
    conn: asyncpg.Connection,
    *,
    job_id: UUID,
    correction_id: UUID,
    status: str,
    to_text: str | None,
    decided_by: UUID,
    expected_rev: int,
) -> tuple[Row, int] | None:
    """Accept or reject one correction (idempotent). ``None``: no such
    correction on this job (or another tenant's). Raises
    :class:`StaleRevError` when ``expected_rev`` is not the current one."""
    async with conn.transaction():
        rev = await conn.fetchval(
            "SELECT corrections_rev FROM transcription_jobs WHERE id = $1 FOR UPDATE", job_id
        )
        if rev is None:
            return None
        current = await conn.fetchrow(
            "SELECT * FROM transcript_corrections WHERE id = $1 AND job_id = $2",
            correction_id,
            job_id,
        )
        if current is None:
            return None
        before = _row(current)
        new_text = to_text if (to_text and status == "accepted") else before.to_text
        if before.status == status and new_text == before.to_text:
            return before, int(rev)  # idempotent: the same decision again
        if int(rev) != expected_rev:
            raise StaleRevError
        if new_text != before.to_text:
            taken = await conn.fetchval(
                "SELECT 1 FROM transcript_corrections WHERE job_id = $1 AND to_text = $2 AND id <> $3",
                job_id,
                new_text,
                correction_id,
            )
            if taken:
                raise ToTextTakenError
        updated = await conn.fetchrow(
            """
            UPDATE transcript_corrections
            SET status = $3, to_text = $4, decided_by = $5, updated_at = now(),
                source = CASE WHEN $4 <> to_text THEN 'user' ELSE source END
            WHERE id = $1 AND job_id = $2
            RETURNING *
            """,
            correction_id,
            job_id,
            status,
            new_text,
            decided_by,
        )
        new_rev = await conn.fetchval(
            "UPDATE transcription_jobs SET corrections_rev = corrections_rev + 1"
            " WHERE id = $1 RETURNING corrections_rev",
            job_id,
        )
    return _row(updated), int(new_rev)
