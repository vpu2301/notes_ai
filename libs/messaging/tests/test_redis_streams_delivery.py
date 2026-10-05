"""Delivery-semantics regressions for RedisStreamsConsumer on fakeredis (deliberately not env-gated):
ack must XACK, the retry counter must survive re-delivery, reclaimed entries must reach the iterator.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fakeredis.aioredis import FakeRedis

from messaging import Message, RedisStreamsConsumer, RedisStreamsProducer


@pytest.fixture
async def redis_client() -> FakeRedis:
    client = FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


def _names() -> tuple[str, str, str]:
    stream = f"test:notif:{uuid.uuid4().hex[:8]}"
    return stream, f"{stream}:dlq", "test-group"


async def _pending_count(client: FakeRedis, stream: str, group: str) -> int:
    summary = await client.xpending(stream, group)
    # redis-py returns a dict for the summary form.
    return int(summary["pending"] if isinstance(summary, dict) else summary[0])


async def test_ack_removes_entry_from_pending(redis_client: FakeRedis) -> None:
    """The regression: ack() used to no-op because offset is always None."""
    stream, dlq, group = _names()
    producer = RedisStreamsProducer(client=redis_client, default_stream=stream)

    async with RedisStreamsConsumer(
        client=redis_client,
        producer=producer,
        stream=stream,
        group=group,
        consumer="c1",
        dlq_stream=dlq,
        block_ms=50,
    ) as consumer:
        await producer.send(value=b"payload")

        async for msg in consumer:
            assert msg.value == b"payload"
            await consumer.ack(msg)
            break

        assert await _pending_count(redis_client, stream, group) == 0


async def test_dlq_after_max_retries_without_header_help(
    redis_client: FakeRedis,
) -> None:
    """fail() must reach the cap on its own — no hand-injected x-attempts."""
    stream, dlq, group = _names()
    producer = RedisStreamsProducer(client=redis_client, default_stream=stream)

    async with RedisStreamsConsumer(
        client=redis_client,
        producer=producer,
        stream=stream,
        group=group,
        consumer="c1",
        dlq_stream=dlq,
        block_ms=50,
        max_retries=3,
    ) as consumer:
        await producer.send(value=b"poison")

        first: Message | None = None
        async for msg in consumer:
            first = msg
            break
        assert first is not None

        # Re-delivery rebuilds the Message from the SAME fields, so failing one object three times is the retry
        # sequence; the return value tells a caller with its own job record that the queue gave up.
        assert await consumer.fail(first, error_kind="boom-1") is False
        assert await redis_client.xlen(dlq) == 0

        assert await consumer.fail(first, error_kind="boom-2") is False
        assert await redis_client.xlen(dlq) == 0

        assert await consumer.fail(first, error_kind="boom-3") is True
        assert await redis_client.xlen(dlq) == 1
        assert await _pending_count(redis_client, stream, group) == 0


async def test_reclaimed_entries_are_redelivered(redis_client: FakeRedis) -> None:
    """A crashed consumer's in-flight message must reach a live consumer."""
    stream, dlq, group = _names()
    producer = RedisStreamsProducer(client=redis_client, default_stream=stream)

    # Consumer A reads and "crashes" without acking.
    async with RedisStreamsConsumer(
        client=redis_client,
        producer=producer,
        stream=stream,
        group=group,
        consumer="crashed",
        dlq_stream=dlq,
        block_ms=50,
        reclaim_interval_s=60.0,
        reclaim_idle_ms=0,
    ) as a:
        await producer.send(value=b"orphan")
        async for msg in a:
            assert msg.value == b"orphan"
            break  # no ack — entry stays in the PEL

    assert await _pending_count(redis_client, stream, group) == 1

    # Consumer B must pick it up via XAUTOCLAIM and see it in the iterator.
    async with RedisStreamsConsumer(
        client=redis_client,
        producer=producer,
        stream=stream,
        group=group,
        consumer="rescuer",
        dlq_stream=dlq,
        block_ms=50,
        reclaim_interval_s=60.0,  # driven explicitly below, not by the timer
        reclaim_idle_ms=0,
    ) as b:
        assert await b.reclaim_once() == 1

        # One generator step rather than `async for` + `break`, which would leave it suspended for the GC.
        it = b.__aiter__()
        try:
            rescued = await asyncio.wait_for(anext(it), timeout=5.0)
        finally:
            await it.aclose()

        assert rescued.value == b"orphan", "reclaimed entry never reached the iterator"
        await b.ack(rescued)
        assert await _pending_count(redis_client, stream, group) == 0
