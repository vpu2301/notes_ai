"""Rate limits, waited out and counted (Task 4 step 2).

A provider that gets HTTP 429 waits — ``Retry-After`` when the server says, else
exponential backoff with full jitter from ``BASE_S`` up to ``CAP_S`` — and tries again,
within ``CALL_BUDGET_S`` of waiting per call and ``GENERATION_BUDGET_S`` per generation.
A call that exhausts either budget fails as ``rate_limited``: a throttled provider,
never a failed model.

The per-generation tally is a ``ContextVar``: the task that owns a generation calls
:func:`begin`; every provider call under it (gather'd windows and blocks included)
records into the same tally; :func:`end` hands the numbers back for ``stats.throttle``.
"""

from __future__ import annotations

import random
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

BASE_S = 2.0
CAP_S = 30.0
CALL_BUDGET_S = 120.0
GENERATION_BUDGET_S = 600.0


@dataclass
class Tally:
    budget_s: float = GENERATION_BUDGET_S
    calls_throttled: int = 0
    """HTTP 429 responses seen (each one is a wait, or the give-up)."""
    waited_ms: int = 0
    gave_up: int = 0
    """Calls that ran out of waiting budget and failed as ``rate_limited``."""

    def remaining_s(self) -> float:
        return self.budget_s - self.waited_ms / 1000.0

    def snapshot(self) -> dict[str, int]:
        return {
            "calls_throttled": self.calls_throttled,
            "waited_ms": self.waited_ms,
            "gave_up": self.gave_up,
        }


_current: ContextVar[Tally | None] = ContextVar("models_throttle_tally", default=None)


def begin(budget_s: float = GENERATION_BUDGET_S) -> Tally:
    """Start counting for the generation that owns the current task."""
    tally = Tally(budget_s=budget_s)
    _current.set(tally)
    return tally


def current() -> Tally | None:
    return _current.get()


def end() -> dict[str, int]:
    """The tally's numbers; the task stops counting."""
    tally = _current.get()
    _current.set(None)
    return (tally or Tally()).snapshot()


def backoff_s(attempt: int, *, rng: Any = random.random) -> float:
    """Full jitter: uniform on ``(0, min(CAP_S, BASE_S · 2^(attempt-1)))``, never below 0.1 s."""
    ceiling = min(CAP_S, BASE_S * (2 ** max(0, attempt - 1)))
    return max(0.1, float(rng()) * ceiling)


def wait_for(
    retry_after_s: float | None, attempt: int, call_waited_s: float, *, rng: Any = random.random
) -> float | None:
    """How long this throttled attempt waits before trying again, or ``None`` when the
    call's or the generation's budget cannot cover the wait (the caller gives up).
    Records the 429 and the wait on the current tally either way."""
    delay = (
        float(retry_after_s)
        if retry_after_s is not None and retry_after_s > 0
        else backoff_s(attempt, rng=rng)
    )
    tally = _current.get()
    if tally is not None:
        tally.calls_throttled += 1
    if call_waited_s + delay > CALL_BUDGET_S or (tally is not None and tally.remaining_s() < delay):
        if tally is not None:
            tally.gave_up += 1
        return None
    if tally is not None:
        tally.waited_ms += round(delay * 1000)
    return delay
