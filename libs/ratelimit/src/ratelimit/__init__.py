"""Fixed-window limiter. Fail-open/closed is a per-call decision: an unauthenticated mail-sending cap fails
closed (no open relay on a down Redis), a cap already bounded elsewhere fails open.
"""

from __future__ import annotations

from .ip import client_ip, parse_cidrs
from .limiter import Decision, FixedWindowLimiter, RateLimiterUnavailableError

__all__ = [
    "Decision",
    "FixedWindowLimiter",
    "RateLimiterUnavailableError",
    "client_ip",
    "parse_cidrs",
]
