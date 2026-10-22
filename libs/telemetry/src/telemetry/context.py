"""Run/span context: ContextVars plus propagation across the queue (CORRELATION.md §3).

A queue payload carries ``processing_run_id`` and a W3C ``traceparent``; the consumer calls
``extract`` first thing. ``asyncio.to_thread`` and new tasks copy the context, so spans opened
in offloaded code attach to the right run and parent."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from opentelemetry import propagate, trace


@dataclass(frozen=True, slots=True)
class RunRef:
    processing_run_id: UUID
    tenant_id: UUID
    recording_id: UUID
    kind: str = "initial"


_current_run: ContextVar[RunRef | None] = ContextVar("telemetry_run", default=None)
_current_span: ContextVar[UUID | None] = ContextVar("telemetry_span", default=None)
# The run's current worker attempt; spans opened without an explicit attempt take it.
_current_attempt: ContextVar[int] = ContextVar("telemetry_attempt", default=1)


def current_attempt() -> int:
    return _current_attempt.get()


def set_attempt(attempt: int) -> object:
    return _current_attempt.set(max(1, attempt))


def current_run() -> RunRef | None:
    return _current_run.get()


def current_span_id() -> UUID | None:
    return _current_span.get()


def set_run(run: RunRef | None) -> object:
    return _current_run.set(run)


def reset_run(token: object) -> None:
    _current_run.reset(token)  # type: ignore[arg-type]


def set_span(span_id: UUID | None) -> object:
    return _current_span.set(span_id)


def reset_span(token: object) -> None:
    _current_span.reset(token)  # type: ignore[arg-type]


def inject(run: RunRef | None = None) -> dict[str, Any]:
    """Fields to add to a queue payload: the run id and the current trace context."""
    run = run or current_run()
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {
        "processing_run_id": run.processing_run_id if run else None,
        "traceparent": carrier.get("traceparent"),
    }


def extract(
    processing_run_id: UUID | str | None, *, tenant_id: UUID, recording_id: UUID
) -> RunRef | None:
    """The run a consumed message belongs to, or ``None`` for messages from before telemetry."""
    if processing_run_id is None:
        return None
    run_id = (
        processing_run_id if isinstance(processing_run_id, UUID) else UUID(str(processing_run_id))
    )
    return RunRef(processing_run_id=run_id, tenant_id=tenant_id, recording_id=recording_id)


def trace_context(traceparent: str | None) -> Any:
    """An OTel context for ``traceparent`` (or the current one), to start consumer spans under."""
    if not traceparent:
        return None
    return propagate.extract({"traceparent": traceparent})


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
