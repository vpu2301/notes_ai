"""Fixed-window counter on Redis: ``INCR`` + ``EXPIRE`` per window bucket.

Key shape ``<prefix>:<scope>:<subject>:<window_start>`` — the same shape
``nlp_service.deps.rate_limited`` and ``auth_service.rate_limit`` have used
by hand. The TTL outlives the window by a margin so a bucket cannot be
reset by racing its own expiry. Subjects that are personal data (an email
address) must be hashed by the caller before they become a key.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("ratelimit")

_TTL_MARGIN_SECONDS = 60


class RateLimiterUnavailableError(RuntimeError):
    """The backend could not be reached and the caller asked to fail closed."""


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    count: int
    limit: int
    retry_after: int
    """Seconds until the current window ends (0 when allowed)."""
    degraded: bool = False
    """True when the backend was down and the call failed open."""


class FixedWindowLimiter:
    def __init__(
        self,
        redis: Any,
        *,
        prefix: str,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not prefix:
            raise ValueError("prefix is required")
        self._redis = redis
        self._prefix = prefix.rstrip(":")
        self._clock = clock or time.time

    def key(self, scope: str, subject: str, window_start: int) -> str:
        return f"{self._prefix}:{scope}:{subject}:{window_start}"

    async def allow(
        self,
        scope: str,
        subject: str,
        *,
        limit: int,
        window_seconds: int,
        fail_open: bool = True,
        cost: int = 1,
    ) -> Decision:
        """Count one hit in the current window and say whether it fits.

        Every call counts, including refused ones — an attacker who is
        already over the cap keeps feeding the counter, which is what keeps
        the cap a cap.
        """
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        now = int(self._clock())
        window_start = now - (now % window_seconds)
        retry_after = max(1, window_start + window_seconds - now)
        key = self.key(scope, subject, window_start)
        try:
            count = int(await self._redis.incrby(key, cost))
            if count <= cost:
                await self._redis.expire(key, window_seconds + _TTL_MARGIN_SECONDS)
        except Exception as exc:  # noqa: BLE001 — posture decided by the caller
            logger.warning(
                "ratelimit.backend_error",
                extra={
                    "scope": scope,
                    "fail_open": fail_open,
                    "error_class": type(exc).__name__,
                },
            )
            if not fail_open:
                raise RateLimiterUnavailableError(
                    f"rate limiter backend unavailable for {scope}"
                ) from exc
            return Decision(allowed=True, count=0, limit=limit, retry_after=0, degraded=True)
        if count > limit:
            return Decision(allowed=False, count=count, limit=limit, retry_after=retry_after)
        return Decision(allowed=True, count=count, limit=limit, retry_after=0)
