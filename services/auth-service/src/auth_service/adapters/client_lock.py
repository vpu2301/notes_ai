"""The fail-closed lock on client-credential guessing (IDX-B1b F2/H).

Two keys, because the pack's rule has two different clocks in it — "ten
wrong secrets within ten minutes, then locked for fifteen":

    mdx:auth:fail:client:<id>   counter, 10-minute TTL
    mdx:auth:lock:client:<id>   the lock itself, 15-minute TTL

A fixed-window limiter cannot express that on its own: its window is both
the counting period and the penalty, so a 10-minute window gives a
10-minute lock. Separating them means the penalty outlives the evidence,
which is the point of a lockout.

``is_locked`` **raises** rather than guessing when Redis is unreachable.
That is the deliberate exception to the house fail-open posture: the
alternative is unlimited secret guessing against a principal that never
notices and never gets tired, and the client on the other end is a
machine that already retries with backoff.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

FAIL_KEY = "mdx:auth:fail:client:{subject}"
LOCK_KEY = "mdx:auth:lock:client:{subject}"


class LockUnavailableError(RuntimeError):
    """The backend could not be reached. The caller must refuse, not allow."""


class RedisClientLock:
    def __init__(
        self,
        redis: Any,
        *,
        threshold: int,
        window_seconds: int,
        lock_seconds: int,
    ) -> None:
        self._redis = redis
        self._threshold = threshold
        self._window = window_seconds
        self._lock_seconds = lock_seconds

    async def is_locked(self, subject: str) -> bool:
        try:
            return bool(await self._redis.exists(LOCK_KEY.format(subject=subject)))
        except Exception as exc:  # noqa: BLE001 — posture is the caller's, and it is closed
            logger.error("auth.client_lock.unavailable", extra={"error_class": type(exc).__name__})
            raise LockUnavailableError("client lock backend unavailable") from exc

    async def record_failure(self, subject: str) -> bool:
        """Count one wrong secret. True when this failure tripped the lock.

        Best-effort: a failure we could not count is a failure the client
        was still refused for. Losing the count degrades the lock, it does
        not open the door — unlike losing ``is_locked``, which would.
        """
        key = FAIL_KEY.format(subject=subject)
        try:
            count = int(await self._redis.incr(key))
            if count == 1:
                await self._redis.expire(key, self._window)
            if count >= self._threshold:
                await self._redis.set(LOCK_KEY.format(subject=subject), b"1", ex=self._lock_seconds)
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "auth.client_lock.counter_unavailable",
                extra={"error_class": type(exc).__name__},
            )
            return False

    async def clear(self, subject: str) -> None:
        """Drop both keys. Used by the operator runbook after a re-provision."""
        try:
            await self._redis.delete(
                FAIL_KEY.format(subject=subject), LOCK_KEY.format(subject=subject)
            )
        except Exception:  # noqa: BLE001
            logger.warning("auth.client_lock.clear_failed")
