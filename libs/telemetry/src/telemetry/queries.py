"""Read side of the telemetry tables for the read API (telemetry sprint 4).

Unlike ``store.py`` these raise: a read that fails must surface as an error, not as "no such
run". Every function takes a connection the caller opened with ``tenant_connection`` — the
rows are read under the tenant's RLS policies; cross-tenant callers first resolve the tenant
with the ids-only ``telemetry_*_tenant`` functions (0094).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from .schema import ClientEvent, LlmCall, ProcessingRun, RunContext, RunExport, SpanRecord

# One row per run for lists: identity, outcome and headline numbers; never content.
_SUMMARY = """
SELECT r.processing_run_id, r.tenant_id, r.recording_id, r.kind, r.reprocess_scope, r.trigger,
       r.status, r.error_category, r.submitted_at, r.finished_at, r.audio_duration_seconds,
       r.processing_wall_seconds, r.rtf, r.user_wait_seconds, r.telemetry_overhead_seconds,
       (SELECT s.attributes->>'backend' FROM telemetry_spans s
         WHERE s.processing_run_id = r.processing_run_id AND s.stage = 'asr_primary'
         ORDER BY s.start_wall_utc, s.end_wall_utc DESC LIMIT 1) AS asr_backend,
       (SELECT c.model FROM telemetry_llm_calls c
         WHERE c.processing_run_id = r.processing_run_id AND c.purpose <> 'provider_probe'
         ORDER BY c.llm_call_id DESC LIMIT 1) AS llm_model
  FROM telemetry_runs r
"""


def encode_cursor(submitted_at: datetime, run_id: UUID) -> str:
    raw = json.dumps({"s": submitted_at.isoformat(), "i": run_id.hex})
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    """Raises ``ValueError`` for anything that is not a cursor this module wrote."""
    try:
        obj = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
        return datetime.fromisoformat(obj["s"]), UUID(obj["i"])
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("invalid cursor") from exc


async def list_runs(
    conn: Any,
    *,
    limit: int,
    recording_id: UUID | None = None,
    status: str | None = None,
    requester: UUID | None = None,
    submitted_from: datetime | None = None,
    submitted_to: datetime | None = None,
    before: tuple[datetime, UUID] | None = None,
) -> list[dict[str, Any]]:
    """Newest first (``submitted_at DESC, processing_run_id DESC``); ``before`` is the keyset
    cursor of the last row already returned."""
    where: list[str] = []
    args: list[Any] = []

    def add(sql: str, value: Any) -> None:
        args.append(value)
        where.append(sql.format(n=len(args)))

    if recording_id is not None:
        add("r.recording_id = ${n}", recording_id)
    if status is not None:
        add("r.status = ${n}", status)
    if requester is not None:  # runs of recordings this person submitted (reprocesses included)
        add(
            "r.recording_id IN (SELECT id FROM transcription_jobs WHERE requester_sub = ${n})",
            requester,
        )
    if submitted_from is not None:
        add("r.submitted_at >= ${n}", submitted_from)
    if submitted_to is not None:
        add("r.submitted_at < ${n}", submitted_to)
    if before is not None:
        args += [before[0], before[1]]
        where.append(f"(r.submitted_at, r.processing_run_id) < (${len(args) - 1}, ${len(args)})")
    args.append(limit)
    sql = (
        _SUMMARY
        + (" WHERE " + " AND ".join(where) if where else "")
        + f" ORDER BY r.submitted_at DESC, r.processing_run_id DESC LIMIT ${len(args)}"
    )
    return [dict(row) for row in await conn.fetch(sql, *args)]


def _row(record: Any, drop: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in dict(record).items():
        if key in drop:
            continue
        if isinstance(value, str) and value[:1] in "{[" and key in {
            "attributes", "null_reasons", "other_model_activity", "effective_config",
            "device_asr", "device_diarization", "device_llm",
        }:  # fmt: skip
            value = json.loads(value)
        out[key] = value
    return out


async def fetch_export(conn: Any, run_id: UUID) -> RunExport | None:
    """The whole stored record of one run, or ``None`` when the tenant has no such run."""
    run = await conn.fetchrow("SELECT * FROM telemetry_runs WHERE processing_run_id = $1", run_id)
    if run is None:
        return None
    ctx = await conn.fetchrow(
        "SELECT * FROM telemetry_run_contexts WHERE processing_run_id = $1", run_id
    )
    spans = await conn.fetch(
        "SELECT * FROM telemetry_spans WHERE processing_run_id = $1 ORDER BY start_wall_utc, span_id",
        run_id,
    )
    llm = await conn.fetch(
        "SELECT * FROM telemetry_llm_calls WHERE processing_run_id = $1 ORDER BY llm_call_id",
        run_id,
    )
    events = await conn.fetch(
        "SELECT * FROM telemetry_client_events WHERE processing_run_id = $1"
        " ORDER BY client_wall_utc, event_id",
        run_id,
    )
    return RunExport(
        processing_run=ProcessingRun(**_row(run, drop=("created_at",))),
        run_context=RunContext(**_row(ctx)) if ctx else None,
        spans=[SpanRecord(**_row(s)) for s in spans],
        llm_calls=[LlmCall(**_row(c)) for c in llm],
        client_events=[ClientEvent(**_row(e)) for e in events],
    )


async def run_tenant(conn: Any, run_id: UUID) -> UUID | None:
    value = await conn.fetchval("SELECT telemetry_run_tenant($1)", run_id)
    return value if isinstance(value, UUID) else None


async def recording_tenant(conn: Any, recording_id: UUID) -> UUID | None:
    value = await conn.fetchval("SELECT telemetry_recording_tenant($1)", recording_id)
    return value if isinstance(value, UUID) else None


async def tenants_between(conn: Any, start: datetime, end: datetime) -> list[UUID]:
    return [r[0] for r in await conn.fetch("SELECT * FROM telemetry_tenants($1, $2)", start, end)]
