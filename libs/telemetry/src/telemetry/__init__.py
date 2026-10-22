"""Pipeline telemetry, schema v1 (telemetry-sprints/design/).

Public API::

    telemetry.configure(pool, enabled=..., retention_days=..., app_commit=...)
    run = await telemetry.start_run(tenant_id=..., recording_id=..., kind="initial", trigger="user")
    payload_fields = telemetry.inject(run)                # onto the queue message
    run = telemetry.extract(payload.processing_run_id, tenant_id=..., recording_id=...)
    await telemetry.begin_run(run, effective_config=..., device_asr=...)
    with telemetry.span("vad", "vad.speech_runs") as s: s.set("speech_seconds", 12.5)
    await telemetry.finish_run(run, result_stored=True, stage_statuses=[...])

Missing is not zero; observed is never inferred; nothing leaves without ``redact``; every
call is fail-open."""

from __future__ import annotations

from . import llm
from .accum import add_audio_processed as _add_audio
from .context import (
    RunRef,
    current_attempt,
    current_run,
    current_span_id,
    extract,
    inject,
    reset_run,
    set_run,
)
from .redact import redact
from .runs import begin_run, configure, extend_run, finish_run, settings, start_run
from .runtime import collect_run_context, execution_mode, observe_device
from .schema import SCHEMA_VERSION, ClientEvent, Device, LlmCall
from .spans import Span, record_span, span
from .store import get as get_store


def add_audio_processed(seconds: float) -> None:
    """Add to the run's ``asr_audio_processed_seconds`` (a labelled sum: primary + recovery)."""
    run = current_run()
    if run is not None:
        _add_audio(run.processing_run_id, seconds)


async def record_llm_call(call: LlmCall) -> None:
    await get_store().insert_llm_call(call)


async def record_client_event(event: ClientEvent) -> None:
    event = event.model_copy(update={"attributes": redact(event.attributes)})
    await get_store().insert_client_event(event)


__all__ = [
    "SCHEMA_VERSION", "ClientEvent", "Device", "LlmCall", "RunRef", "Span", "add_audio_processed",
    "begin_run", "current_attempt", "extend_run", "llm", "record_span",
    "collect_run_context", "configure", "current_run", "current_span_id", "execution_mode",
    "extract", "finish_run", "get_store", "inject", "observe_device", "record_client_event",
    "record_llm_call", "redact", "reset_run", "set_run", "settings", "span", "start_run",
]  # fmt: skip
