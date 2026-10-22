"""The span API: ``with span(stage, name) as s:`` (or ``async with``).

Durations come from ``time.monotonic_ns()``; span boundaries also carry wall UTC so spans from
different processes can be ordered. An exception inside the block marks the span ``error``
(``cancelled`` for cancellation), records the exception class name only, and is re-raised
unchanged. Outside a run the span still times itself but writes nothing. Telemetry failures
never reach the caller."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Literal
from uuid import UUID, uuid4

from . import accum, context, metrics, overhead
from .redact import redact
from .runtime import host_label
from .schema import STAGE_ERROR_CATEGORY, STAGE_KEYS, ErrorCategory, Reason, SpanRecord, SpanStatus

logger = logging.getLogger("telemetry.spans")

# Stages that can run longer than 10 s write a `started` row at begin, so a crash leaves evidence.
LONG_STAGES: frozenset[str] = frozenset(
    {"queue", "model_init", "asr_primary", "asr_recovery", "diarization_load",
     "diarization_infer", "llm_call", "other"}
)  # fmt: skip
# Spans open right now in this process, for `other_model_activity` (stage, backend, run, start).
_open_lock = threading.Lock()
_open: dict[UUID, tuple[str, str, UUID, int]] = {}
_MODEL_STAGES = {
    "model_init": "asr", "asr_primary": "asr", "asr_recovery": "asr",
    "diarization_load": "diarization", "diarization_infer": "diarization", "llm_call": "llm",
}  # fmt: skip


def _is_cancellation(exc: BaseException) -> bool:
    return isinstance(exc, asyncio.CancelledError) or "cancel" in type(exc).__name__.lower()


def open_model_activity(exclude_run: UUID | None) -> list[dict[str, Any]]:
    """Model work other runs have open in this process right now."""
    now = time.monotonic_ns()
    with _open_lock:
        items = list(_open.values())
    return [
        {
            "kind": _MODEL_STAGES[stage],
            "backend": backend,
            "run_id": str(run_id),
            "overlap_seconds": round((now - start) / 1e9, 3),
        }
        for stage, backend, run_id, start in items
        if stage in _MODEL_STAGES and run_id != exclude_run
    ]


class Span:
    """One measured unit. Use through ``span(...)``."""

    def __init__(
        self,
        stage: str,
        name: str,
        *,
        attempt: int | None = None,
        parent: UUID | None = None,
        attributes: dict[str, Any] | None = None,
        run: context.RunRef | None = None,
    ) -> None:
        self.stage = stage
        self.name = name
        # None = the run's current worker attempt (context), taken at begin.
        self.attempt = attempt or 0
        self.span_id: UUID = uuid4()
        self._parent = parent
        self._run = run
        self.attributes: dict[str, Any] = dict(attributes or {})
        self._reasons: dict[str, Reason] = {}
        self.status: SpanStatus = "ok"
        self.error_category: ErrorCategory | None = None
        self.parallel_with: list[UUID] = []
        self._start_ns = 0
        self._start_wall: datetime | None = None
        self._tokens: list[object] = []
        self.duration_seconds: float | None = None
        self._exc_class: str | None = None

    # ── attributes ──
    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value
        self._reasons.pop(key, None)

    def update(self, **values: Any) -> None:
        for key, value in values.items():
            self.set(key, value)

    def missing(self, key: str, reason: Reason) -> None:
        """``key`` was not measured, for ``reason`` (missing is not zero)."""
        self.attributes[key] = None
        self._reasons[key] = reason

    # ── lifecycle ──
    def _begin(self) -> None:
        self._run = self._run or context.current_run()
        self._parent = self._parent or context.current_span_id()
        self.attempt = self.attempt or context.current_attempt()
        self._start_ns = time.monotonic_ns()
        self._start_wall = datetime.now(UTC)
        self._tokens = [context.set_span(self.span_id)]
        if self._run is None:
            return
        run_id = self._run.processing_run_id
        with overhead.measure(run_id):
            try:
                backend = str(self.attributes.get("backend") or "")
                with _open_lock:
                    _open[self.span_id] = (self.stage, backend, run_id, self._start_ns)
                if self.stage in LONG_STAGES:
                    from . import store

                    store.get().span(self._record("started", end=False))
            except Exception:  # noqa: BLE001 — fail-open
                logger.debug("telemetry.span_begin_failed", exc_info=True)

    def _end(self, exc: BaseException | None) -> None:
        end_ns = time.monotonic_ns()
        self.duration_seconds = (end_ns - self._start_ns) / 1e9
        for token in reversed(self._tokens):
            context.reset_span(token)
        if exc is not None:
            if _is_cancellation(exc):
                self.status = "cancelled"
            else:
                self.status = "error"
                self.error_category = self.error_category or STAGE_ERROR_CATEGORY.get(
                    self.stage, "unknown"
                )
        if self.status == "error" and self._run is not None and self.stage != "other":
            accum.error(self._run.processing_run_id, self.error_category or "unknown")
        if self._run is None:
            return
        run_id = self._run.processing_run_id
        with overhead.measure(run_id):
            try:
                with _open_lock:
                    _open.pop(self.span_id, None)
                self._exc_class = type(exc).__name__ if exc is not None else None
                record = self._record(self.status, end=True, end_ns=end_ns)
                from . import store

                store.get().span(record)
                metrics.stage_seconds.record(
                    self.duration_seconds,
                    {
                        "stage": self.stage,
                        "backend": str(record.attributes.get("backend") or "none")[:40],
                        "status": self.status,
                    },
                )
            except Exception:  # noqa: BLE001 — fail-open
                metrics.write_errors_total.add(1, {"entity": "span"})
                logger.debug("telemetry.span_end_failed", exc_info=True)

    def _record(self, status: SpanStatus, *, end: bool, end_ns: int | None = None) -> SpanRecord:
        assert self._run is not None
        attrs = redact({k: v for k, v in self.attributes.items() if not k.startswith("_")})
        reasons: dict[str, Reason] = dict(self._reasons)
        if end:
            for key in STAGE_KEYS.get(self.stage, ()):
                attrs.setdefault(key, None)
            for key, value in attrs.items():
                if value is None and key not in reasons:
                    # Not set, or dropped by redaction: unmeasured, never zero.
                    reasons[key] = "not_measured" if key not in self.attributes else "unavailable"
        if reasons:
            attrs["_reasons"] = reasons
        return SpanRecord(
            span_id=self.span_id,
            processing_run_id=self._run.processing_run_id,
            tenant_id=self._run.tenant_id,
            parent_span_id=self._parent,
            stage=self.stage,  # type: ignore[arg-type]
            name=self.name,
            attempt=self.attempt,
            status=status,
            error_category=self.error_category if end else None,
            error_class=self._exc_class if end else None,
            start_monotonic_ns=self._start_ns,
            end_monotonic_ns=end_ns if end else None,
            start_wall_utc=self._start_wall,
            end_wall_utc=datetime.now(UTC) if end else None,
            clock_source="monotonic",
            process_id=os.getpid(),
            host=host_label(),
            attributes=attrs,
            is_parallel_with=list(self.parallel_with) or None,
        )

    def __enter__(self) -> Span:
        self._begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self._end(exc)
        return False

    async def __aenter__(self) -> Span:
        self._begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self._end(exc)
        return False


def record_span(
    stage: str,
    name: str,
    *,
    start_wall: datetime | None,
    end_wall: datetime | None,
    status: SpanStatus = "ok",
    attributes: dict[str, Any] | None = None,
    reasons: dict[str, Reason] | None = None,
    clock_source: str = "wall",
    parent: UUID | None = None,
    attempt: int | None = None,
    run: context.RunRef | None = None,
) -> UUID | None:
    """A span measured from wall timestamps after the fact — a queue wait (enqueue → pickup,
    two processes), an upload timed from the request's arrival. Fail-open; ``None`` outside a run."""
    run = run or context.current_run()
    if run is None:
        return None
    s = Span(stage, name, attempt=attempt, parent=parent, attributes=attributes, run=run)
    s._parent = parent or context.current_span_id()
    s.attempt = attempt or context.current_attempt()
    s.status = status
    for key, reason in (reasons or {}).items():
        s.missing(key, reason)
    with overhead.measure(run.processing_run_id):
        try:
            s._start_wall = start_wall
            record = s._record(status, end=True).model_copy(
                update={
                    "start_monotonic_ns": None,
                    "end_monotonic_ns": None,
                    "end_wall_utc": end_wall,
                    "clock_source": clock_source,
                }
            )
            from . import store

            store.get().span(record)
            if start_wall is not None and end_wall is not None:
                metrics.stage_seconds.record(
                    max(0.0, (end_wall - start_wall).total_seconds()),
                    {
                        "stage": stage,
                        "backend": str(record.attributes.get("backend") or "none")[:40],
                        "status": status,
                    },
                )
        except Exception:  # noqa: BLE001 — fail-open
            metrics.write_errors_total.add(1, {"entity": "span"})
            logger.debug("telemetry.record_span_failed", exc_info=True)
            return None
    return s.span_id


def span(
    stage: str,
    name: str,
    attempt: int | None = None,
    parent: UUID | None = None,
    attributes: dict[str, Any] | None = None,
    *,
    run: context.RunRef | None = None,
) -> Span:
    """A span for ``stage``; works with ``with`` and ``async with``."""
    return Span(stage, name, attempt=attempt, parent=parent, attributes=attributes, run=run)
