"""Previews of note instructions: a per-workspace hourly cap (each is a model call).
Fixed window in Redis; fails open, like ``ClipRateLimiter``."""

from __future__ import annotations

import logging
import time
from typing import Final
from uuid import UUID

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

WINDOW_S: Final = 3600


class NoteInstructionsRateLimiter:
    def __init__(self, redis: Redis, *, per_hour: int = 30) -> None:
        self._redis = redis
        self._per_hour = per_hour

    async def check(self, *, tenant_id: UUID) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        bucket = int(time.time() // WINDOW_S)
        key = f"note:instr-rl:{tenant_id}:{bucket}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, WINDOW_S + 60)
        except Exception as exc:  # noqa: BLE001 — fail open
            logger.warning("note.instructions_rate_limit_redis_error: %s", exc)
            return True, 0
        if count > self._per_hour:
            return False, WINDOW_S - int(time.time() % WINDOW_S)
        return True, 0
