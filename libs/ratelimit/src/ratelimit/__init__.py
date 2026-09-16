"""libs/ratelimit — the house fixed-window limiter, extracted (IDX-A3, F4).

    limiter = FixedWindowLimiter(redis, prefix="mdx:auth:rl")
    decision = await limiter.allow("otp_start_ip", ip, limit=20, window_seconds=3600)
    if not decision.allowed:
        raise ... 429 with Retry-After = decision.retry_after

Posture is a per-call decision, not a global one: an abuse cap on an
unauthenticated mail-sending endpoint fails **closed** (a down Redis must
not turn the service into an open relay), while a cap on a verify step that
is already bounded by the DB's attempt counter fails **open**.
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
