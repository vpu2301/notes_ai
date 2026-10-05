"""Semaphore pool bounding concurrent inline completions; slot wait is inside the
caller's ``asyncio.timeout``, so a slow generation times out into a silent 204.
"""

from __future__ import annotations

import asyncio
from types import TracebackType


class SlotPool:
    def __init__(self, slots: int) -> None:
        self._sem = asyncio.Semaphore(slots)

    async def __aenter__(self) -> SlotPool:
        await self._sem.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._sem.release()
