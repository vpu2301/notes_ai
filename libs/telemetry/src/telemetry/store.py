"""Fail-open, append-only persistence for telemetry (STORAGE.md §2).

Nothing here raises into the caller: a failed write is counted in
``mdx_telemetry_write_errors_total{entity}``, logged at most once a minute per entity, and
dropped. Span rows are buffered (thread-safe) and flushed by a background task, at run finish
and on close; the `started` begin-row of a long span is replaced once by its end row."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from db import tenant_connection

from . import metrics, overhead
from .queries import fetch_export
from .schema import ClientEvent, LlmCall, ProcessingRun, RunContext, RunExport, SpanRecord

logger = logging.getLogger("telemetry.store")

_SPAN_SQL = """
INSERT INTO telemetry_spans (span_id, processing_run_id, tenant_id, parent_span_id, stage, name,
    attempt, status, error_category, error_class, start_monotonic_ns, end_monotonic_ns,
    start_wall_utc, end_wall_utc, clock_source, process_id, host, attributes, is_parallel_with)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb,$19)
ON CONFLICT (span_id) DO UPDATE SET
    status = EXCLUDED.status, error_category = EXCLUDED.error_category,
    error_class = EXCLUDED.error_class, end_monotonic_ns = EXCLUDED.end_monotonic_ns,
    end_wall_utc = EXCLUDED.end_wall_utc, attributes = EXCLUDED.attributes,
    is_parallel_with = EXCLUDED.is_parallel_with
WHERE telemetry_spans.status = 'started'
"""
_RUN_COLUMNS = (
    "processing_run_id", "tenant_id", "recording_id", "note_id", "note_generation_id", "kind",
    "reprocess_scope", "trigger", "telemetry_schema_version", "status", "error_category",
    "submitted_at", "started_at", "finished_at", "audio_duration_seconds", "created_by",
    "concurrent_runs_at_start", "other_model_activity", "retention_until", "trace_id",
    "null_reasons",
)  # fmt: skip
_JSON_RUN = {"other_model_activity", "null_reasons"}
_CONTEXT_COLUMNS = (
    "processing_run_id", "tenant_id", "telemetry_schema_version", "app_commit", "app_build",
    "os_name", "os_version", "arch", "chip_model", "memory_total_bytes", "execution_mode",
    "effective_config", "device_asr", "device_diarization", "device_llm",
    "memory_pressure_start", "memory_pressure_end", "process_rss_start", "process_rss_end",
    "swap_used_start", "swap_used_end", "container_mem_limit", "null_reasons",
)  # fmt: skip
_JSON_CONTEXT = {
    "effective_config",
    "device_asr",
    "device_diarization",
    "device_llm",
    "null_reasons",
}


def _insert(
    table: str,
    columns: tuple[str, ...],
    json_cols: set[str],
    conflict: str,
    computed: dict[str, str] | None = None,
) -> str:
    """``INSERT``; ``computed`` replaces a column's placeholder with an SQL expression of it."""
    computed = computed or {}
    values = ", ".join(
        computed.get(c, "${i}::jsonb" if c in json_cols else "${i}").format(i=i)
        for i, c in enumerate(columns, 1)
    )
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values}) {conflict}"


# The open-run count is taken in the same statement (one round trip at submission).
_RUN_SQL = _insert(
    "telemetry_runs",
    _RUN_COLUMNS,
    _JSON_RUN,
    "ON CONFLICT DO NOTHING",
    computed={
        "concurrent_runs_at_start": "COALESCE(${i}, telemetry_open_runs())",
        "null_reasons": "${i}::jsonb - 'concurrent_runs_at_start'",
    },
)
_CONTEXT_SQL = _insert(
    "telemetry_run_contexts", _CONTEXT_COLUMNS, _JSON_CONTEXT, "ON CONFLICT DO NOTHING"
)


_MARK_RUNNING_SQL = """
UPDATE telemetry_runs
   SET status = 'running', started_at = COALESCE(started_at, now()), attempts = attempts + 1,
       other_model_activity = other_model_activity || $2::jsonb
 WHERE processing_run_id = $1 AND status IN ('queued', 'running')
RETURNING attempts
"""


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def _args(model: Any, columns: tuple[str, ...], json_cols: set[str]) -> list[Any]:
    data = model.model_dump(mode="python")
    out: list[Any] = []
    for c in columns:
        v = data.get(c)
        out.append(_json(v) if c in json_cols and v is not None else v)
    return out


@dataclass
class _Op:
    entity: str
    tenant_id: UUID
    run_id: UUID
    sql: str
    args: list[Any]
    nbytes: int = 0


@dataclass
class TelemetryStore:
    """Writes to Postgres through ``db.tenant_connection`` (RLS)."""

    pool: Any
    flush_interval_seconds: float = 1.0
    write_timeout_seconds: float = 5.0
    # Telemetry switched off (TELEMETRY_ENABLED=false): only the processing_run row is
    # written; spans, run context, LLM calls and client events are dropped.
    row_only: bool = False
    _queue: deque[_Op] = field(default_factory=deque)
    _task: asyncio.Task[None] | None = None
    _last_log: dict[str, float] = field(default_factory=dict)

    # ── fail-open plumbing ──
    def _failed(self, entity: str, exc: BaseException) -> None:
        metrics.write_errors_total.add(1, {"entity": entity})
        now = time.monotonic()
        if now - self._last_log.get(entity, -1e9) >= 60:
            self._last_log[entity] = now
            logger.warning(
                "telemetry.write_failed",
                extra={"entity": entity, "error_class": type(exc).__name__},
            )

    async def _guarded(
        self, entity: str, run_id: UUID | None, fn: Callable[[], Awaitable[Any]]
    ) -> Any:
        start = time.monotonic_ns()
        try:
            return await asyncio.wait_for(fn(), self.write_timeout_seconds)
        except Exception as exc:  # noqa: BLE001 — telemetry never fails the pipeline
            self._failed(entity, exc)
            return None
        finally:
            if run_id is not None:
                overhead.add(run_id, (time.monotonic_ns() - start) / 1e9)

    # ── buffered span writes ──
    def span(self, record: SpanRecord) -> None:
        if self.row_only:
            return
        try:
            attributes_json = _json(record.attributes)
            args = [
                record.span_id, record.processing_run_id, record.tenant_id, record.parent_span_id,
                record.stage, record.name, record.attempt, record.status, record.error_category,
                record.error_class, record.start_monotonic_ns, record.end_monotonic_ns,
                record.start_wall_utc, record.end_wall_utc, record.clock_source, record.process_id,
                record.host, attributes_json, record.is_parallel_with,
            ]  # fmt: skip
            nbytes = len(attributes_json)
            self._queue.append(
                _Op("span", record.tenant_id, record.processing_run_id, _SPAN_SQL, args, nbytes)
            )
            overhead.buffered(record.processing_run_id, nbytes)
            self._ensure_task()
        except Exception as exc:  # noqa: BLE001
            self._failed("span", exc)

    def llm_call(self, call: LlmCall) -> None:
        """Buffered like spans (the attempt sink is synchronous)."""
        if self.row_only:
            return
        try:
            cols = tuple(LlmCall.model_fields)
            sql = _insert("telemetry_llm_calls", cols, {"null_reasons"}, "ON CONFLICT DO NOTHING")
            self._queue.append(
                _Op(
                    "llm_call",
                    call.tenant_id,
                    call.processing_run_id,
                    sql,
                    _args(call, cols, {"null_reasons"}),
                )
            )
            self._ensure_task()
        except Exception as exc:  # noqa: BLE001
            self._failed("llm_call", exc)

    def _ensure_task(self) -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # called from a worker thread: the next flush on the loop picks it up
        # A fresh context: the flusher must not inherit the caller's tenant scope.
        self._task = loop.create_task(self._loop(), context=contextvars.Context())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval_seconds)
            await self.flush()

    async def flush(self) -> None:
        ops: list[_Op] = []
        while self._queue:
            ops.append(self._queue.popleft())
        by_tenant: dict[UUID, list[_Op]] = {}
        for op in ops:
            by_tenant.setdefault(op.tenant_id, []).append(op)
        for tenant_id, batch in by_tenant.items():

            async def write(tid: UUID = tenant_id, rows: list[_Op] = batch) -> None:
                async with tenant_connection(self.pool, tid) as conn:
                    for op in rows:
                        await conn.execute(op.sql, *op.args)

            await self._guarded("span", batch[0].run_id, write)
            for op in batch:
                overhead.buffered(op.run_id, -op.nbytes)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
        await self.flush()

    # ── runs ──
    async def insert_run(self, run: ProcessingRun) -> None:
        async def write() -> None:
            async with tenant_connection(self.pool, run.tenant_id) as conn:
                await conn.execute(_RUN_SQL, *_args(run, _RUN_COLUMNS, _JSON_RUN))

        await self._guarded("run", run.processing_run_id, write)

    async def open_runs(self, tenant_id: UUID) -> int | None:
        async def read() -> int:
            async with tenant_connection(self.pool, tenant_id) as conn:
                return int(await conn.fetchval("SELECT telemetry_open_runs()"))

        result: int | None = await self._guarded("run", None, read)
        return result

    async def mark_running(
        self, tenant_id: UUID, run_id: UUID, other_model_activity: list[dict[str, Any]]
    ) -> None:
        async def write() -> None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                await conn.execute(_MARK_RUNNING_SQL, run_id, _json(other_model_activity))

        await self._guarded("run", run_id, write)

    async def insert_context(self, ctx: RunContext) -> None:
        if self.row_only:
            return

        async def write() -> None:
            async with tenant_connection(self.pool, ctx.tenant_id) as conn:
                await conn.execute(_CONTEXT_SQL, *_args(ctx, _CONTEXT_COLUMNS, _JSON_CONTEXT))

        await self._guarded("run_context", ctx.processing_run_id, write)

    async def begin(
        self,
        tenant_id: UUID,
        run_id: UUID,
        other_model_activity: list[dict[str, Any]],
        ctx: RunContext | None,
    ) -> int | None:
        """``running`` + the run context, in one transaction; the run's attempt number."""

        async def write() -> int | None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                attempts = await conn.fetchval(
                    _MARK_RUNNING_SQL, run_id, _json(other_model_activity)
                )
                if ctx is not None:
                    await conn.execute(_CONTEXT_SQL, *_args(ctx, _CONTEXT_COLUMNS, _JSON_CONTEXT))
                # No row updated: the run is already closed (a redelivery after it finished).
                return int(attempts) if attempts is not None else 0

        result: int | None = await self._guarded("run", run_id, write)
        return result

    async def finish_context(
        self, tenant_id: UUID, run_id: UUID, end: Mapping[str, tuple[Any, str]]
    ) -> None:
        if self.row_only:
            return
        values = {k: v for k, (v, _r) in end.items()}
        reasons = {k: r for k, (v, r) in end.items() if v is None}

        async def write() -> None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                await conn.execute(
                    """
                    UPDATE telemetry_run_contexts
                       SET memory_pressure_end = $2, process_rss_end = $3, swap_used_end = $4,
                           null_reasons = (null_reasons
                               - 'memory_pressure_end' - 'process_rss_end' - 'swap_used_end')
                               || $5::jsonb
                     WHERE processing_run_id = $1
                    """,
                    run_id,
                    values.get("memory_pressure_end"),
                    values.get("process_rss_end"),
                    values.get("swap_used_end"),
                    _json(reasons),
                )

        await self._guarded("run_context", run_id, write)

    async def run_facts(
        self, tenant_id: UUID, run_id: UUID
    ) -> tuple[datetime | None, float | None, list[datetime]]:
        """``(submitted_at, audio_duration_seconds, end_wall_utc of every finished backend span)``."""

        async def read() -> tuple[datetime | None, float | None, list[datetime]]:
            async with tenant_connection(self.pool, tenant_id) as conn:
                run = await conn.fetchrow(
                    "SELECT submitted_at, audio_duration_seconds FROM telemetry_runs"
                    " WHERE processing_run_id = $1",
                    run_id,
                )
                rows = await conn.fetch(
                    """
                    SELECT end_wall_utc FROM telemetry_spans
                     WHERE processing_run_id = $1 AND end_wall_utc IS NOT NULL
                       AND clock_source <> 'client_wall' AND stage <> 'ui_delivery'
                    """,
                    run_id,
                )
            if run is None:
                return None, None, []
            return (
                run["submitted_at"],
                run["audio_duration_seconds"],
                [r["end_wall_utc"] for r in rows],
            )

        result = await self._guarded("run", run_id, read)
        return result if result is not None else (None, None, [])

    async def update_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        fields: dict[str, Any],
        reasons: dict[str, str],
        cleared: list[str],
        *,
        only_open: bool = True,
    ) -> None:
        """Set ``fields``; ``reasons`` replace the null-reasons of ``cleared`` + their own keys."""
        names = list(fields)
        sets = [f"{n} = ${i}" for i, n in enumerate(names, 2)]
        drop = "".join(f" - '{k}'" for k in sorted(set(cleared) | set(reasons)))
        sql = (
            f"UPDATE telemetry_runs SET {', '.join(sets + [f'null_reasons = (null_reasons{drop}) || ${len(names) + 2}::jsonb'])}"
            # A run is closed once; a redelivered, already-finished job leaves it as it is.
            " WHERE processing_run_id = $1"
            + (" AND status IN ('queued', 'running')" if only_open else "")
        )

        async def write() -> None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                await conn.execute(sql, run_id, *fields.values(), _json(reasons))

        await self._guarded("run", run_id, write)

    async def run_status(self, tenant_id: UUID, run_id: UUID) -> str | None:
        async def read() -> str | None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                value = await conn.fetchval(
                    "SELECT status FROM telemetry_runs WHERE processing_run_id = $1", run_id
                )
                return str(value) if value is not None else None

        result: str | None = await self._guarded("run", run_id, read)
        return result

    async def latest_run(self, conn: Any, recording_id: UUID) -> UUID | None:
        """The newest run of a recording, on the caller's tenant connection (inside a
        savepoint, so a failure cannot abort the caller's transaction)."""
        try:
            async with conn.transaction():
                value = await conn.fetchval(
                    "SELECT processing_run_id FROM telemetry_runs WHERE recording_id = $1"
                    " ORDER BY submitted_at DESC LIMIT 1",
                    recording_id,
                )
            return value if isinstance(value, UUID) else None
        except Exception as exc:  # noqa: BLE001
            self._failed("run", exc)
            return None

    # ── LLM calls and client events (Sprint 3 writers) ──
    async def insert_llm_call(self, call: LlmCall) -> None:
        if self.row_only:
            return
        cols = tuple(LlmCall.model_fields)
        sql = _insert("telemetry_llm_calls", cols, {"null_reasons"}, "ON CONFLICT DO NOTHING")

        async def write() -> None:
            async with tenant_connection(self.pool, call.tenant_id) as conn:
                await conn.execute(sql, *_args(call, cols, {"null_reasons"}))

        await self._guarded("llm_call", call.processing_run_id, write)

    async def insert_client_event(self, event: ClientEvent) -> None:
        if self.row_only:
            return
        cols = tuple(ClientEvent.model_fields)
        sql = _insert("telemetry_client_events", cols, {"attributes"}, "ON CONFLICT DO NOTHING")

        async def write() -> None:
            async with tenant_connection(self.pool, event.tenant_id) as conn:
                await conn.execute(sql, *_args(event, cols, {"attributes"}))

        await self._guarded("client_event", event.processing_run_id, write)

    async def resolve_run(self, tenant_id: UUID, recording_id: UUID, event: str) -> UUID | None:
        """The run a client event belongs to when the client sent none: the recording's newest
        run whose scope covers the event (a notes display after a regeneration → that run)."""
        scopes = ("notes",) if event.startswith("notes") else ("diarization",)

        async def read() -> UUID | None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                value = await conn.fetchval(
                    """
                    SELECT processing_run_id FROM telemetry_runs
                     WHERE recording_id = $1
                       AND (kind = 'initial' OR reprocess_scope = ANY($2::text[]))
                     ORDER BY submitted_at DESC LIMIT 1
                    """,
                    recording_id,
                    list(scopes),
                )
            return value if isinstance(value, UUID) else None

        result: UUID | None = await self._guarded("client_event", None, read)
        return result

    async def run_recording(self, tenant_id: UUID, run_id: UUID) -> UUID | None:
        async def read() -> UUID | None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                value = await conn.fetchval(
                    "SELECT recording_id FROM telemetry_runs WHERE processing_run_id = $1", run_id
                )
            return value if isinstance(value, UUID) else None

        result: UUID | None = await self._guarded("client_event", None, read)
        return result

    async def add_client_event(self, event: ClientEvent) -> bool:
        """Insert one event; ``False`` when it was a duplicate (first report wins)."""
        if self.row_only:
            return False

        cols = tuple(ClientEvent.model_fields)
        sql = _insert("telemetry_client_events", cols, {"attributes"}, "ON CONFLICT DO NOTHING")

        async def write() -> bool:
            async with tenant_connection(self.pool, event.tenant_id) as conn:
                status = await conn.execute(sql, *_args(event, cols, {"attributes"}))
            return str(status).endswith(" 1")

        result: bool | None = await self._guarded("client_event", event.processing_run_id, write)
        return bool(result)

    async def apply_client_timings(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
        """Recompute the run's user-visible timings from all its client events."""
        from .client_timings import Event, derive

        async def read() -> tuple[Any, list[Any]]:
            async with tenant_connection(self.pool, tenant_id) as conn:
                submitted = await conn.fetchval(
                    "SELECT submitted_at FROM telemetry_runs WHERE processing_run_id = $1", run_id
                )
                rows = await conn.fetch(
                    "SELECT event, client, client_wall_utc, estimated_clock_offset_ms"
                    " FROM telemetry_client_events WHERE processing_run_id = $1",
                    run_id,
                )
            return submitted, list(rows)

        got = await self._guarded("client_event", run_id, read)
        if got is None:
            return {}
        submitted, rows = got
        fields, reasons = derive(
            [
                Event(r["event"], r["client"], r["client_wall_utc"], r["estimated_clock_offset_ms"])
                for r in rows
            ],
            submitted,
        )
        if fields:
            await self.update_run(tenant_id, run_id, fields, reasons, list(fields), only_open=False)
        return fields

    # ── read back (smoke dump, read API) ──
    async def export(self, tenant_id: UUID, run_id: UUID) -> RunExport | None:
        async def read() -> RunExport | None:
            async with tenant_connection(self.pool, tenant_id) as conn:
                return await fetch_export(conn, run_id)

        result: RunExport | None = await self._guarded("export", None, read)
        return result


class NullStore(TelemetryStore):
    """No database configured (tests, scripts): every write is a no-op."""

    def __init__(self) -> None:
        super().__init__(pool=None)

    def span(self, record: SpanRecord) -> None:
        return None

    def llm_call(self, call: LlmCall) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def insert_run(self, run: ProcessingRun) -> None:
        return None

    async def open_runs(self, tenant_id: UUID) -> int | None:
        return None

    async def mark_running(
        self, tenant_id: UUID, run_id: UUID, other_model_activity: list[dict[str, Any]]
    ) -> None:
        return None

    async def insert_context(self, ctx: RunContext) -> None:
        return None

    async def begin(
        self,
        tenant_id: UUID,
        run_id: UUID,
        other_model_activity: list[dict[str, Any]],
        ctx: RunContext | None,
    ) -> int | None:
        return None

    async def finish_context(
        self, tenant_id: UUID, run_id: UUID, end: Mapping[str, tuple[Any, str]]
    ) -> None:
        return None

    async def run_facts(
        self, tenant_id: UUID, run_id: UUID
    ) -> tuple[datetime | None, float | None, list[datetime]]:
        return None, None, []

    async def update_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        fields: dict[str, Any],
        reasons: dict[str, str],
        cleared: list[str],
        *,
        only_open: bool = True,
    ) -> None:
        return None

    async def run_status(self, tenant_id: UUID, run_id: UUID) -> str | None:
        return None

    async def resolve_run(self, tenant_id: UUID, recording_id: UUID, event: str) -> UUID | None:
        return None

    async def run_recording(self, tenant_id: UUID, run_id: UUID) -> UUID | None:
        return None

    async def add_client_event(self, event: ClientEvent) -> bool:
        return False

    async def apply_client_timings(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
        return {}

    async def latest_run(self, conn: Any, recording_id: UUID) -> UUID | None:
        return None

    async def insert_llm_call(self, call: LlmCall) -> None:
        return None

    async def insert_client_event(self, event: ClientEvent) -> None:
        return None

    async def export(self, tenant_id: UUID, run_id: UUID) -> RunExport | None:
        return None


_store: TelemetryStore = NullStore()


def configure(store: TelemetryStore | None) -> None:
    global _store
    _store = store or NullStore()


def get() -> TelemetryStore:
    return _store


def utcnow() -> datetime:
    return datetime.now(UTC)
