"""Telemetry's own cost per run: monotonic time spent in span bookkeeping, redaction,
serialisation and store writes, plus the peak serialised size of the run's buffered records
(the RSS proxy). Sprint 5 reports both."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

_lock = threading.Lock()
_seconds: dict[UUID, float] = {}
_buffer_bytes: dict[UUID, int] = {}
_peak_bytes: dict[UUID, int] = {}


@contextmanager
def measure(run_id: UUID | None) -> Iterator[None]:
    """Attribute the time spent inside the block to ``run_id`` (no-op for ``None``)."""
    start = time.monotonic_ns()
    try:
        yield
    finally:
        if run_id is not None:
            add(run_id, (time.monotonic_ns() - start) / 1e9)


def add(run_id: UUID, seconds: float) -> None:
    with _lock:
        _seconds[run_id] = _seconds.get(run_id, 0.0) + seconds


def buffered(run_id: UUID, nbytes: int) -> None:
    """``nbytes`` of this run's records entered (> 0) or left (< 0) the write buffer."""
    with _lock:
        now = _buffer_bytes.get(run_id, 0) + nbytes
        _buffer_bytes[run_id] = now
        _peak_bytes[run_id] = max(_peak_bytes.get(run_id, 0), now)


def seconds(run_id: UUID) -> float:
    with _lock:
        return _seconds.get(run_id, 0.0)


def peak_bytes(run_id: UUID) -> int:
    with _lock:
        return _peak_bytes.get(run_id, 0)


def forget(run_id: UUID) -> None:
    with _lock:
        _seconds.pop(run_id, None)
        _buffer_bytes.pop(run_id, None)
        _peak_bytes.pop(run_id, None)
