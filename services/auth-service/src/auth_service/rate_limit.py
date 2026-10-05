"""Fail-open fixed-window caps for the password-recovery endpoints: per IP and per email (key hashed, never raw)."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from redis.asyncio import Redis

_WINDOW_SECONDS = 3600
# Outlives the window so a bucket cannot be reset by racing its own expiry.
_KEY_TTL = _WINDOW_SECONDS + 60


class PasswordResetRateLimiter:
    def __init__(
        self,
        redis: Redis,
        *,
        ip_per_hour: int = 20,
        email_per_hour: int = 5,
        email_salt: str = "",
    ) -> None:
        self._redis = redis
        self._ip_per_hour = ip_per_hour
        self._email_per_hour = email_per_hour
        self._email_salt = email_salt

    def _email_key(self, email: str, bucket: int) -> str:
        digest = hashlib.sha256(f"{self._email_salt}:{email.strip().lower()}".encode()).hexdigest()[
            :32
        ]
        return f"auth:pwreset-rl:email:{digest}:{bucket}"

    async def _bump(self, key: str, limit: int) -> bool:
        """Increment one window. True = still within the cap."""
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, _KEY_TTL)
        except Exception as exc:  # noqa: BLE001 — fail-OPEN, by decision
            logger.warning(
                "auth.password_reset.rate_limit_redis_error",
                extra={"error": str(exc), "error_class": type(exc).__name__},
            )
            return True
        return int(count) <= limit

    async def check(self, *, ip: str, email: str) -> bool:
        """True when the request may proceed; both windows are bumped even when the first refused."""
        bucket = int(time.time() // _WINDOW_SECONDS)
        ip_ok = True
        if ip:
            ip_ok = await self._bump(f"auth:pwreset-rl:ip:{ip}:{bucket}", self._ip_per_hour)
        email_ok = await self._bump(self._email_key(email, bucket), self._email_per_hour)
        return ip_ok and email_ok
