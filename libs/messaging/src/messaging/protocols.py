"""Producer / consumer Protocols and the wire ``Message`` type (shape, not transport)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Message:
    """Wire message common to every transport."""

    topic: str
    key: bytes | None
    value: bytes
    headers: dict[str, str]
    timestamp_ms: int
    partition: int | None = None
    offset: int | None = None


class ProducerProtocol(Protocol):
    async def send(
        self,
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: dict[str, str] | None = None,
    ) -> None: ...

    async def flush(self) -> None: ...


class ConsumerProtocol(Protocol):
    def subscribe(self, topics: list[str]) -> None: ...

    def __aiter__(self) -> AsyncIterator[Message]: ...

    async def commit(self) -> None: ...
