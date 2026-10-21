"""Task 4 step 2 — a throttled call waits (Retry-After, else backoff with jitter) within
its budgets, every attempt is a usage record, a call that runs out of budget is
`rate_limited`, and one semaphore per backend holds N in flight."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from models import ErrorKind, ProviderError, UsageRecord, set_usage_sink, throttle
from models.openai_compat import OpenAICompatibleChatProvider

from .conftest_helpers import cassette, json_response, mock_client


def _provider(handler: Any, **kw: Any) -> OpenAICompatibleChatProvider:
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    defaults: dict[str, Any] = {
        "backend": "test_backend",
        "base_url": "http://test/v1",
        "model_id": "m",
        "client": mock_client(handler),
        "sleep": sleep,
    }
    defaults.update(kw)
    provider = OpenAICompatibleChatProvider(**defaults)
    provider.slept = slept  # type: ignore[attr-defined]
    return provider


def _records() -> list[UsageRecord]:
    out: list[UsageRecord] = []
    set_usage_sink(out.append)
    return out


async def test_three_429s_then_200_is_one_call_three_waits_and_a_success() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 3:
            return json_response(429, {"error": "slow down"}, {"retry-after": "7"})
        return json_response(200, cassette("ollama_chat.json"))

    records = _records()
    try:
        tally = throttle.begin()
        p = _provider(handler)
        result = await p.complete("x", None, max_tokens=5)
    finally:
        set_usage_sink(None)
    assert result.text and calls == 4
    assert p.slept == [7.0, 7.0, 7.0]  # Retry-After honoured  # type: ignore[attr-defined]
    assert tally.snapshot() == {"calls_throttled": 3, "waited_ms": 21000, "gave_up": 0}
    assert throttle.end() == tally.snapshot()
    # Every attempt is in the ledger: three throttled, one ok, zero tokens on the failures.
    assert [(r.ok, r.error_kind, r.attempts) for r in records] == [
        (False, "rate_limited", 1),
        (False, "rate_limited", 2),
        (False, "rate_limited", 3),
        (True, None, 4),
    ]
    assert all(r.input_tokens == 0 for r in records if not r.ok)


async def test_backoff_without_retry_after_is_jittered_and_capped() -> None:
    rng = iter([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    delays = [throttle.backoff_s(n, rng=lambda: next(rng)) for n in range(1, 7)]
    assert delays == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert throttle.backoff_s(1, rng=lambda: 0.0) == 0.1  # never a zero sleep


async def test_a_call_beyond_its_budget_is_rate_limited_and_the_fallback_sees_it() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(429, {"error": "slow down"}, {"retry-after": "50"})

    records = _records()
    try:
        tally = throttle.begin()
        with pytest.raises(ProviderError) as exc:
            await _provider(handler).complete("x", None, max_tokens=5)
    finally:
        set_usage_sink(None)
    assert exc.value.kind is ErrorKind.RATE_LIMITED and str(exc.value.kind) == "rate_limited"
    # 50 + 50 fits the 120 s call budget; the third wait would not.
    assert calls == 3 and tally.snapshot() == {
        "calls_throttled": 3,
        "waited_ms": 100000,
        "gave_up": 1,
    }
    assert [(r.ok, r.error_kind, r.attempts) for r in records] == [
        (False, "rate_limited", 1),
        (False, "rate_limited", 2),
        (False, "rate_limited", 3),
    ]


async def test_the_generation_budget_caps_waiting_across_calls() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return json_response(429, {"error": "slow down"}, {"retry-after": "100"})

    tally = throttle.begin(budget_s=150)
    p = _provider(handler)
    with pytest.raises(ProviderError):
        await p.complete("x", None, max_tokens=5)  # waits 100 s, then 100 more would exceed 150
    assert tally.snapshot() == {"calls_throttled": 2, "waited_ms": 100000, "gave_up": 1}
    throttle.end()


async def test_one_semaphore_per_backend_holds_n_in_flight_under_a_burst() -> None:
    in_flight = 0
    peak = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return json_response(200, cassette("ollama_chat.json"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test/v1")
    p = _provider(lambda _r: None, client=client, max_concurrency=3)
    await asyncio.gather(*(p.complete("x", None, max_tokens=5) for _ in range(20)))
    assert peak == 3
