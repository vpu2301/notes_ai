"""Pure retry / warming policy — no I/O, table-tested.

* ``warming`` is a job *state*, not an error: reschedule ``+WARMING_RESCHEDULE_S``
  without consuming an attempt, up to ``cold_start_seconds × WARMING_BUDGET_FACTOR``
  measured from when the job first started waiting. Beyond that the job
  falls back to the normal retry path (attempt consumed, backoff).
* Normal retries: exponential backoff with a cap; ``max_attempts`` → ``dead``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

WARMING_RESCHEDULE_S = 30.0
WARMING_BUDGET_FACTOR = 2
BACKOFF_BASE_S = 15.0
BACKOFF_CAP_S = 15 * 60.0


@dataclass(frozen=True, slots=True)
class WarmingDecision:
    wait: bool  # True → park as waiting_on_model; False → budget exhausted, treat as retryable failure
    run_at: datetime
    waited_seconds: float
    budget_seconds: float


def warming_decision(
    *,
    now: datetime,
    waiting_since: datetime | None,
    cold_start_seconds: int,
    retry_after_s: float | None = None,
) -> WarmingDecision:
    budget = float(cold_start_seconds * WARMING_BUDGET_FACTOR)
    since = waiting_since or now
    waited = max(0.0, (now - since).total_seconds())
    if cold_start_seconds <= 0 or waited >= budget:
        return WarmingDecision(wait=False, run_at=now, waited_seconds=waited, budget_seconds=budget)
    delay = min(max(retry_after_s or WARMING_RESCHEDULE_S, 1.0), WARMING_RESCHEDULE_S * 2)
    return WarmingDecision(
        wait=True,
        run_at=now + timedelta(seconds=delay),
        waited_seconds=waited,
        budget_seconds=budget,
    )


def retry_backoff_seconds(attempts: int) -> float:
    """Delay before the next attempt after ``attempts`` consumed attempts."""
    return float(min(BACKOFF_BASE_S * (2 ** max(0, attempts - 1)), BACKOFF_CAP_S))


def next_run_at(now: datetime, attempts: int) -> datetime:
    return now + timedelta(seconds=retry_backoff_seconds(attempts))


def utcnow() -> datetime:
    return datetime.now(UTC)
