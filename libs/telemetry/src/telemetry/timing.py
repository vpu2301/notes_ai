"""Pure timing and status rules (CORRELATION.md §6–7). Σ span durations is never wall time:
spans nest and overlap, so wall time is ``max(end) − submitted_at`` over the run's backend spans."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .schema import RunStatus

# Stages whose failure does not lose the result (the result is still stored → `partial`).
_OPTIONAL_STAGES = frozenset({"other", "ui_delivery"})


def critical_path_seconds(
    submitted_at: datetime | None, end_walls: Iterable[datetime]
) -> float | None:
    """``max(end_wall) − submitted_at``; ``None`` when either side is unknown."""
    ends = list(end_walls)
    if submitted_at is None or not ends:
        return None
    return max(0.0, (max(ends) - submitted_at).total_seconds())


def sum_seconds(durations: Iterable[float]) -> float:
    """A labelled sum (``asr_audio_processed_seconds``); never used for wall time."""
    return float(sum(durations))


def derive_status(
    stage_statuses: Iterable[tuple[str, str]], *, result_stored: bool, cancelled: bool = False
) -> RunStatus:
    """Run status from per-stage span statuses: the spans carry the truth, this is a summary."""
    statuses = list(stage_statuses)
    if cancelled or any(status == "cancelled" for _stage, status in statuses):
        return "cancelled"
    if not result_stored:
        return "failed"
    if any(
        status in ("error", "partial") and stage not in _OPTIONAL_STAGES
        for stage, status in statuses
    ):
        return "partial"
    return "succeeded"


def ratios(wall: float | None, audio: float | None) -> tuple[float | None, float | None]:
    """``(rtf, speedup)`` = ``(wall / audio, audio / wall)``."""
    if wall is None or audio is None or wall <= 0 or audio <= 0:
        return None, None
    return wall / audio, audio / wall
