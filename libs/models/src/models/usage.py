"""``model_usage`` hook: every provider call emits one record of counts and identifiers only, never text."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger("models.usage")


@dataclass(frozen=True, slots=True)
class UsageRecord:
    backend: str
    model_id: str
    operation: str  # chat.complete | asr.transcribe | embed
    ok: bool
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0.0
    structured_mode: str | None = None
    error_kind: str | None = None
    workspace_id: str | None = None
    attempts: int = 1


UsageSink = Callable[[UsageRecord], None]


def _log_sink(record: UsageRecord) -> None:
    logger.info("model_usage", extra={"model_usage": asdict(record)})


_sink: UsageSink = _log_sink


def set_usage_sink(sink: UsageSink | None) -> None:
    """Replace the process-wide sink (``None`` restores the log sink)."""
    global _sink
    _sink = sink or _log_sink


def emit(record: UsageRecord) -> None:
    try:
        _sink(record)
    except Exception:  # a broken sink must never fail a job
        logger.exception("model_usage sink raised")


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One HTTP attempt of a model call, for pipeline telemetry (never the billing ledger:
    ``UsageRecord`` stays one record per call). Counts, durations and ids only, never text.
    A count the provider did not report is ``None``, never 0."""

    backend: str
    model_id: str  # configured
    operation: str  # chat.complete | asr.transcribe | embed
    attempt: int
    ok: bool
    started_at: datetime
    ended_at: datetime
    latency_ms: int  # this attempt: request sent → last byte (or failure)
    response_model: str | None = None
    error_kind: str | None = None
    http_status: int | None = None
    streaming: bool = False
    structured_mode: str | None = None
    finish_reason: str | None = None
    # Waits before this attempt: the concurrency slot and 429 back-off; a warming 503's sleep.
    queue_wait_ms: int | None = None
    model_load_ms: int | None = None
    # Exactly what the provider's usage object said (None = absent).
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    prompt_chars: int | None = None
    completion_chars: int | None = None
    # Server-side timing fields when the backend sends them (llama.cpp ``timings``).
    provider_timings: dict[str, Any] = field(default_factory=dict)


AttemptSink = Callable[[AttemptRecord], None]
_attempt_sink: AttemptSink | None = None


def set_attempt_sink(sink: AttemptSink | None) -> None:
    """Install the process-wide attempt sink (telemetry); ``None`` = attempts are not recorded."""
    global _attempt_sink
    _attempt_sink = sink


def emit_attempt(record: AttemptRecord) -> None:
    if _attempt_sink is None:
        return
    try:
        _attempt_sink(record)
    except Exception:  # telemetry must never fail a call
        logger.debug("attempt sink raised", exc_info=True)
