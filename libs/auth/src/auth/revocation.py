"""Session-revocation denylist (ADR-0040): Redis keys by ``sid``/``sub`` with TTL = remaining token lifetime.

auth-service pushes revocations as it performs them. Fail-OPEN by decision: Redis down → not revoked + WARNING.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_SID_PREFIX = "mdx:revoked:sid:"
_SUB_PREFIX = "mdx:revoked:sub:"

# TTL floor so a token at the edge of its lifetime stays denylisted through clock skew.
_MIN_TTL_SECONDS = 30


class SessionDenylist(Protocol):
    """What ``build_current_user`` needs from a denylist."""

    async def is_revoked(self, *, sid: str, sub: str) -> bool: ...


class RedisSessionDenylist:
    """Redis-backed denylist; safe for concurrent use, lazy connections."""

    def __init__(self, *, redis: Any) -> None:
        self._redis = redis
        self._owns_client = False

    @classmethod
    def from_url(cls, url: str) -> RedisSessionDenylist:
        import redis.asyncio as aioredis

        inst = cls(redis=aioredis.from_url(url, decode_responses=False))
        inst._owns_client = True
        return inst

    async def aclose(self) -> None:
        if self._owns_client:
            await self._redis.aclose()

    async def is_revoked(self, *, sid: str, sub: str) -> bool:
        try:
            pipe = self._redis.pipeline(transaction=False)
            pipe.exists(_SID_PREFIX + sid)
            pipe.exists(_SUB_PREFIX + sub)
            sid_hit, sub_hit = await pipe.execute()
            return bool(sid_hit) or bool(sub_hit)
        except Exception as exc:  # noqa: BLE001 — fail-OPEN, by decision
            logger.warning(
                "session_denylist.check_failed_fail_open",
                extra={"error": str(exc), "error_class": type(exc).__name__},
            )
            return False

    async def revoke_sid(self, sid: str, *, ttl_seconds: int) -> None:
        """Deny one session. TTL = remaining access-token lifetime."""
        await self._redis.set(_SID_PREFIX + sid, b"1", ex=max(int(ttl_seconds), _MIN_TTL_SECONDS))

    async def revoke_sub(self, sub: str, *, ttl_seconds: int) -> None:
        """Deny every live session of a user (deactivation, replay)."""
        await self._redis.set(_SUB_PREFIX + sub, b"1", ex=max(int(ttl_seconds), _MIN_TTL_SECONDS))

    async def clear_sub(self, sub: str) -> None:
        """Lift a user-level deny (reactivation before the TTL lapsed)."""
        await self._redis.delete(_SUB_PREFIX + sub)


def build_session_denylist(*, enabled: bool, redis_url: str) -> RedisSessionDenylist | None:
    """Settings-gated helper; ``None`` when the feature is off (= no check)."""
    if not enabled:
        return None
    return RedisSessionDenylist.from_url(redis_url)
