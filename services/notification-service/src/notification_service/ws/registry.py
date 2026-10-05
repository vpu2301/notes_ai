"""Per-worker registry of locally-connected sockets. Process-local by design (cross-worker
is pub/sub in fanout.py); one user may hold several sockets.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


class SendableSocket(Protocol):
    """The slice of starlette's WebSocket this module needs."""

    async def send_text(self, data: str) -> None: ...


class SocketRegistry:
    def __init__(self) -> None:
        self._by_user: dict[UUID, set[SendableSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def add(self, user_id: UUID, socket: SendableSocket) -> None:
        async with self._lock:
            self._by_user[user_id].add(socket)

    async def remove(self, user_id: UUID, socket: SendableSocket) -> None:
        async with self._lock:
            sockets = self._by_user.get(user_id)
            if sockets is None:
                return
            sockets.discard(socket)
            if not sockets:
                # Keep the map from growing without bound.
                del self._by_user[user_id]

    async def sockets_for(self, user_id: UUID) -> list[SendableSocket]:
        async with self._lock:
            return list(self._by_user.get(user_id, ()))

    async def send_to_user(self, user_id: UUID, payload: str) -> int:
        """Best-effort push; returns how many sockets accepted. A failed socket is dropped (disconnect race)."""
        sent = 0
        for socket in await self.sockets_for(user_id):
            try:
                await socket.send_text(payload)
                sent += 1
            except Exception:  # noqa: BLE001
                await self.remove(user_id, socket)
        return sent

    def connected_user_count(self) -> int:
        """Feeds the fan-out gauge."""
        return len(self._by_user)

    def connected_socket_count(self) -> int:
        return sum(len(s) for s in self._by_user.values())
