"""Redis Streams producer/consumer with at-least-once + DLQ semantics (ADR-0010).

XAUTOCLAIM-reclaimed entries are re-delivered through the iterator (``XREADGROUP '>'`` never returns them); the
retry counter lives in Redis, not in headers (a re-delivered entry carries its ORIGINAL fields). Idempotency is
the caller's responsibility.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable
from typing import Any, Final, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .protocols import Message

logger = logging.getLogger(__name__)

DEFAULT_DLQ_SUFFIX: Final = ":dlq"
DEFAULT_BLOCK_MS: Final = 5_000
DEFAULT_RECLAIM_IDLE_MS: Final = 60_000
DEFAULT_RECLAIM_INTERVAL_S: Final = 60.0
DEFAULT_MAX_RETRIES: Final = 3
HEADER_ATTEMPTS_KEY: Final = "x-attempts"
# Lifetime of the per-(stream, group) delivery-attempt counter hash.
_ATTEMPTS_TTL_S: Final = 7 * 24 * 3600


class RedisStreamsProducer:
    """``XADD`` producer for a default stream; ``send(topic=…)`` also serves the DLQ path."""

    def __init__(
        self,
        *,
        client: Redis,
        default_stream: str,
        maxlen: int | None = 100_000,
    ) -> None:
        self._client = client
        self._default_stream = default_stream
        self._maxlen = maxlen

    async def send(
        self,
        topic: str | None = None,
        key: bytes | None = None,
        value: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> str:
        stream = topic or self._default_stream
        fields: dict[bytes, bytes] = {b"value": value}
        if key is not None:
            fields[b"key"] = key
        for h_name, h_value in (headers or {}).items():
            fields[f"h-{h_name}".encode()] = h_value.encode("utf-8")

        kwargs: dict[str, Any] = {}
        if self._maxlen is not None:
            kwargs["maxlen"] = self._maxlen
            kwargs["approximate"] = True

        msg_id_raw: Any = await self._client.xadd(stream, fields, **kwargs)  # type: ignore[arg-type]
        msg_id = msg_id_raw.decode("utf-8") if isinstance(msg_id_raw, bytes) else str(msg_id_raw)
        logger.debug(
            "redis_streams.xadd",
            extra={"stream": stream, "message_id": msg_id, "key_set": key is not None},
        )
        return msg_id

    async def flush(self) -> None:
        return None

    async def aclose(self) -> None:
        # The Redis connection is shared; never closed here.
        return None


class RedisStreamsConsumer:
    """``XREADGROUP`` consumer with reclaim + DLQ: ``ack`` on success, ``fail`` to bump attempts (DLQ at the cap),
    no ack to leave the entry pending for XAUTOCLAIM. The reclaim task runs in the background."""

    def __init__(
        self,
        *,
        client: Redis,
        producer: RedisStreamsProducer,
        stream: str,
        group: str,
        consumer: str,
        dlq_stream: str | None = None,
        block_ms: int = DEFAULT_BLOCK_MS,
        reclaim_idle_ms: int = DEFAULT_RECLAIM_IDLE_MS,
        reclaim_interval_s: float = DEFAULT_RECLAIM_INTERVAL_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._client = client
        self._producer = producer
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._dlq_stream = dlq_stream or f"{stream}{DEFAULT_DLQ_SUFFIX}"
        self._block_ms = block_ms
        self._reclaim_idle_ms = reclaim_idle_ms
        self._reclaim_interval_s = reclaim_interval_s
        self._max_retries = max_retries
        self._stop = asyncio.Event()
        self._reclaim_task: asyncio.Task[None] | None = None
        # Keyed by stream+group so a reclaim by another consumer sees the same count.
        self._attempts_key = f"mdx:streams:{stream}:{group}:attempts"
        # Reclaimed entries reach __aiter__ through this queue (XREADGROUP '>' would never return them).
        self._reclaimed: asyncio.Queue[Message] = asyncio.Queue()

    async def __aenter__(self) -> RedisStreamsConsumer:
        await self._ensure_group()
        self._reclaim_task = asyncio.create_task(self._reclaim_loop())
        return self

    async def __aexit__(self, *_: Any) -> None:
        self._stop.set()
        if self._reclaim_task is not None:
            self._reclaim_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reclaim_task

    async def _ensure_group(self) -> None:
        try:
            await self._client.xgroup_create(self._stream, self._group, id="$", mkstream=True)
            logger.info(
                "redis_streams.group_created",
                extra={"stream": self._stream, "group": self._group},
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def subscribe(self, topics: list[str]) -> None:
        # Single-stream consumer bound at construction; satisfies ConsumerProtocol.
        if list(topics) != [self._stream]:
            raise ValueError(
                f"RedisStreamsConsumer is bound to {self._stream!r}; "
                f"subscribe({topics!r}) does not match."
            )

    async def _bump_attempts(self, msg_id: str) -> int:
        """Increment and return the durable delivery-attempt count."""
        # redis-py types hash commands `Awaitable[int] | int` (shared sync/async signature); the client is async.
        attempts = int(
            await cast("Awaitable[int]", self._client.hincrby(self._attempts_key, msg_id, 1))
        )
        # Bounds the counter hash so poisoned messages do not leak fields forever.
        await self._client.expire(self._attempts_key, _ATTEMPTS_TTL_S)
        return attempts

    async def __aiter__(self) -> AsyncIterator[Message]:
        while not self._stop.is_set():
            # Reclaimed entries first: strictly older than anything XREADGROUP returns.
            while not self._reclaimed.empty():
                yield self._reclaimed.get_nowait()
                if self._stop.is_set():
                    return
            try:
                resp = await self._client.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer,
                    streams={self._stream: ">"},
                    count=1,
                    block=self._block_ms,
                )
            except RedisTimeoutError:
                # redis-py >=8 raises on the BLOCK deadline instead of returning None: the idle path.
                continue
            except ResponseError as exc:
                logger.warning(
                    "redis_streams.xreadgroup_error",
                    extra={"error": str(exc), "stream": self._stream},
                )
                await asyncio.sleep(1)
                continue

            if not resp:
                continue
            for _stream_name, entries in resp:
                for msg_id_raw, fields in entries:
                    yield _to_message(self._stream, msg_id_raw, fields)

    async def commit(self) -> None:
        # No-op: acks happen per message via ``ack``.
        return None

    async def ack(self, message: Message) -> None:
        # The stream id lives in ``headers["_id"]``; ``offset`` is always None here.
        msg_id = message.headers.get("_id")
        if msg_id is None:
            return
        await self._client.xack(self._stream, self._group, msg_id)
        await cast("Awaitable[int]", self._client.hdel(self._attempts_key, msg_id))

    async def fail(self, message: Message, *, error_kind: str) -> bool:
        """Increment the retry counter; at the cap push to DLQ + ack. Returns whether the message was dead-lettered
        (a caller with its own job record needs that to close it out)."""
        msg_id = message.headers.get("_id")
        if msg_id is None:
            return False
        attempts = await self._bump_attempts(msg_id)
        if attempts >= self._max_retries:
            await self._producer.send(
                topic=self._dlq_stream,
                key=message.key,
                value=message.value,
                headers={
                    **{k: v for k, v in message.headers.items() if not k.startswith("_")},
                    HEADER_ATTEMPTS_KEY: str(attempts),
                    "x-final-error-kind": error_kind,
                    "x-original-stream": self._stream,
                    "x-original-message-id": msg_id,
                },
            )
            await self._client.xack(self._stream, self._group, msg_id)
            await cast("Awaitable[int]", self._client.hdel(self._attempts_key, msg_id))
            logger.warning(
                "redis_streams.dlq",
                extra={
                    "stream": self._stream,
                    "dlq": self._dlq_stream,
                    "message_id": msg_id,
                    "error_kind": error_kind,
                    "attempts": attempts,
                },
            )
            return True
        # Below the cap: the message stays pending for reclaim.
        logger.info(
            "redis_streams.retry",
            extra={
                "stream": self._stream,
                "message_id": msg_id,
                "attempts": attempts,
                "max_retries": self._max_retries,
            },
        )
        return False

    async def _reclaim_loop(self) -> None:
        """Background XAUTOCLAIM of messages pending longer than ``reclaim_idle_ms`` (a crashed consumer)."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._reclaim_interval_s)
                return  # stop set
            except TimeoutError:
                pass
            try:
                await self.reclaim_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "redis_streams.autoclaim_error",
                    extra={
                        "error": str(exc),
                        "error_class": type(exc).__name__,
                        "stream": self._stream,
                    },
                )

    async def reclaim_once(self) -> int:
        """Run one XAUTOCLAIM cycle and queue what it claims; returns the count (test-drivable)."""
        _cursor, claimed, _deleted = await self._client.xautoclaim(
            name=self._stream,
            groupname=self._group,
            consumername=self._consumer,
            min_idle_time=self._reclaim_idle_ms,
            count=10,
        )
        if not claimed:
            return 0
        for msg_id_raw, fields in claimed:
            self._reclaimed.put_nowait(_to_message(self._stream, msg_id_raw, fields))
        logger.info(
            "redis_streams.reclaimed",
            extra={
                "stream": self._stream,
                "count": len(claimed),
                "as_consumer": self._consumer,
            },
        )
        return len(claimed)


def _to_message(
    stream: str,
    msg_id_raw: bytes,
    fields: dict[bytes, bytes],
) -> Message:
    msg_id = msg_id_raw.decode("utf-8") if isinstance(msg_id_raw, bytes) else str(msg_id_raw)
    value = fields.get(b"value", b"")
    key = fields.get(b"key")
    headers: dict[str, str] = {"_id": msg_id}
    for k, v in fields.items():
        if k in (b"value", b"key"):
            continue
        k_str = k.decode("utf-8")
        if k_str.startswith("h-"):
            headers[k_str[2:]] = v.decode("utf-8")
        else:
            headers[k_str] = v.decode("utf-8")
    try:
        ts_ms = int(msg_id.split("-", 1)[0])
    except ValueError:
        ts_ms = int(time.time() * 1000)
    return Message(
        topic=stream,
        key=key,
        value=value,
        headers=headers,
        timestamp_ms=ts_ms,
        partition=None,
        offset=None,
    )
