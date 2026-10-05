"""In-memory telemetry batch buffer: flushes on interval or batch size.

Bounded (``10 × flush_batch``), drop-oldest on overflow; a failed flush retries once then drops.
Telemetry must never slow a keystroke or grow memory.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

import asyncpg

from . import repository as repo

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    pass

MAX_BUFFER_FACTOR = 10  # max_buffer = factor × flush_batch


class TelemetryBuffer:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        flush_interval_s: float,
        flush_batch: int,
        dropped_metric: Any = None,
    ) -> None:
        self._pool = pool
        self._interval = flush_interval_s
        self._batch = flush_batch
        self._max_buffer = MAX_BUFFER_FACTOR * flush_batch
        self._rows: list[tuple] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._dropped_metric = dropped_metric

    def _drop(self, n: int, reason: str) -> None:
        if n <= 0:
            return
        if self._dropped_metric is not None:
            self._dropped_metric.add(n, {"reason": reason})
        logger.warning("telemetry.rows_dropped", extra={"count": n, "reason": reason})

    def append(self, row: tuple) -> None:
        self._rows.append(row)
        overflow = len(self._rows) - self._max_buffer
        if overflow > 0:
            del self._rows[:overflow]
            self._drop(overflow, "buffer_overflow")
        if len(self._rows) >= self._batch:
            asyncio.create_task(self._flush_locked(), name="telemetry-batch-flush")

    async def _flush_locked(self) -> None:
        async with self._lock:
            if not self._rows:
                return
            batch = self._rows
            self._rows = []
            try:
                async with self._pool.acquire() as conn:
                    await repo.insert_telemetry_batch(conn, batch)
            except Exception as first_exc:  # noqa: BLE001
                # One retry on a fresh connection, then drop.
                try:
                    async with self._pool.acquire() as conn:
                        await repo.insert_telemetry_batch(conn, batch)
                except Exception:  # noqa: BLE001
                    logger.warning("telemetry.batch_insert_failed: %s", first_exc)
                    self._drop(len(batch), "flush_failed")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="telemetry-buffer")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):  # noqa: BLE001
                await self._task
            self._task = None
        await self._flush_locked()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self._flush_locked()
