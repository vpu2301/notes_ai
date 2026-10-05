"""Messaging Protocol contracts + the Redis Streams implementation (importable without ``redis`` installed)."""

from .protocols import ConsumerProtocol, Message, ProducerProtocol

try:
    from .redis_streams import (
        DEFAULT_DLQ_SUFFIX,
        RedisStreamsConsumer,
        RedisStreamsProducer,
    )

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover  — `redis` not installed
    _REDIS_AVAILABLE = False
    DEFAULT_DLQ_SUFFIX = ":dlq"  # type: ignore[misc]

    class _MissingRedis:
        def __init__(self, *_a: object, **_kw: object) -> None:
            raise ImportError(
                "redis is not installed; pip install redis>=5.0 to use "
                "RedisStreamsProducer / RedisStreamsConsumer."
            )

    RedisStreamsProducer = _MissingRedis  # type: ignore[assignment,misc]
    RedisStreamsConsumer = _MissingRedis  # type: ignore[assignment,misc]


__all__ = [
    "ConsumerProtocol",
    "DEFAULT_DLQ_SUFFIX",
    "Message",
    "ProducerProtocol",
    "RedisStreamsConsumer",
    "RedisStreamsProducer",
]
