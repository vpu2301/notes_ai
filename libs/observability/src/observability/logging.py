"""JSON logging to stdout with service, trace/span ids and the PII filter applied last."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

from pythonjsonlogger import json as jsonlogger

from .correlation import CorrelationIdFilter
from .pii_filter import PIISafeFilter


class _UtcJsonFormatter(jsonlogger.JsonFormatter):
    """ISO-8601 UTC with milliseconds; ``time.strftime`` has no ``%f``, so ``datefmt`` cannot do it."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        return (
            datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{int(record.msecs):03d}Z"
        )


def setup_logging(service_name: str, log_level: str = "INFO") -> None:
    """Configure the root logger (JSON, correlation ids, PII filter); idempotent."""
    root = logging.getLogger()
    root.setLevel(log_level.upper())
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = _UtcJsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(trace_id)s %(span_id)s",
        rename_fields={"levelname": "level", "asctime": "timestamp", "name": "logger"},
        static_fields={"service": service_name},
    )
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())
    handler.addFilter(PIISafeFilter())
    root.addHandler(handler)
