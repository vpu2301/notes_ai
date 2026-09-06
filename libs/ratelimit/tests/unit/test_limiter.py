from __future__ import annotations

import pytest

from ratelimit import Decision, FixedWindowLimiter, RateLimiterUnavailableError


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.down = False

    async def incrby(self, key: str, amount: int) -> int:
        if self.down:
            raise ConnectionError("redis down")
        self.store[key] = self.store.get(key, 0) + amount
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> None:
        if self.down:
            raise ConnectionError("redis down")
        self.ttls[key] = seconds


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


def _limiter(redis: FakeRedis, now: float = 1_000_000.0) -> FixedWindowLimiter:
    return FixedWindowLimiter(redis, prefix="mdx:auth:rl", clock=lambda: now)


async def test_allows_up_to_limit_then_refuses_with_retry_after(redis: FakeRedis) -> None:
    now = 1_000_000.0  # window of 900 s starts at 999_900 → 800 s left
    limiter = _limiter(redis, now)
    for i in range(1, 6):
        d = await limiter.allow("otp_start_email", "h", limit=5, window_seconds=900)
        assert d == Decision(allowed=True, count=i, limit=5, retry_after=0)
    d = await limiter.allow("otp_start_email", "h", limit=5, window_seconds=900)
    assert not d.allowed and d.count == 6 and d.retry_after == 800


async def test_key_shape_and_ttl_outlives_window(redis: FakeRedis) -> None:
    limiter = _limiter(redis, 1_000_000.0)
    await limiter.allow("otp_start_ip", "203.0.113.9", limit=20, window_seconds=3600)
    (key,) = redis.store
    assert key == "mdx:auth:rl:otp_start_ip:203.0.113.9:997200"
    assert redis.ttls[key] == 3660


async def test_new_window_starts_fresh(redis: FakeRedis) -> None:
    limiter = _limiter(redis, 1_000_000.0)
    for _ in range(3):
        await limiter.allow("s", "x", limit=2, window_seconds=60)
    later = _limiter(redis, 1_000_060.0)
    assert (await later.allow("s", "x", limit=2, window_seconds=60)).count == 1


async def test_refused_calls_still_count(redis: FakeRedis) -> None:
    limiter = _limiter(redis)
    for _ in range(4):
        await limiter.allow("s", "x", limit=2, window_seconds=60)
    assert next(iter(redis.store.values())) == 4


async def test_fail_open_allows_and_flags_degraded(redis: FakeRedis) -> None:
    redis.down = True
    d = await _limiter(redis).allow(
        "otp_verify_ip", "x", limit=60, window_seconds=900, fail_open=True
    )
    assert d.allowed and d.degraded and d.count == 0


async def test_fail_closed_raises(redis: FakeRedis) -> None:
    redis.down = True
    with pytest.raises(RateLimiterUnavailableError):
        await _limiter(redis).allow(
            "otp_start_email", "x", limit=5, window_seconds=900, fail_open=False
        )


async def test_rejects_nonsense_limits(redis: FakeRedis) -> None:
    with pytest.raises(ValueError):
        await _limiter(redis).allow("s", "x", limit=0, window_seconds=60)
    with pytest.raises(ValueError):
        FixedWindowLimiter(redis, prefix="")
