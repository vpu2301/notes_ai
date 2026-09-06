"""``model_usage`` hook — every provider call emits one record.

DEP-S0 ships the hook and a log sink; DEP-S1 persists records (cost meter,
per-tier fairness in DEP-S4). A record carries counts and identifiers only,
never prompt, transcript or output text — a unit test scans a captured log
to keep that true.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass

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
