"""Per-run, per-process accumulators that ``finish_run`` reads: the audio actually fed to ASR
(primary + recovery — a labelled sum) and the first failing stage's error category."""

from __future__ import annotations

import threading
from uuid import UUID

from .schema import ErrorCategory

_lock = threading.Lock()
_audio: dict[UUID, float] = {}
_first_error: dict[UUID, ErrorCategory] = {}


def add_audio_processed(run_id: UUID, seconds: float) -> None:
    with _lock:
        _audio[run_id] = _audio.get(run_id, 0.0) + max(0.0, seconds)


def audio_processed(run_id: UUID) -> float | None:
    with _lock:
        return _audio.get(run_id)


def error(run_id: UUID, category: ErrorCategory) -> None:
    with _lock:
        _first_error.setdefault(run_id, category)


def first_error(run_id: UUID) -> ErrorCategory | None:
    with _lock:
        return _first_error.get(run_id)


def forget(run_id: UUID) -> None:
    with _lock:
        _audio.pop(run_id, None)
        _first_error.pop(run_id, None)
