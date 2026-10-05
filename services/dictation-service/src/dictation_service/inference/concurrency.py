"""Per-worker inference queue: one asyncio queue serialises window inference so windows never contend on the GPU."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


class WorkerCapacityError(Exception):
    """Raised when the per-worker session cap is reached."""


@dataclass(slots=True)
class _Job:
    pcm: np.ndarray
    language: str
    prompt: str | None
    prev_text: str | None
    future: asyncio.Future[object]
    deadline_at: float
    submitted_at: float


class InferenceQueue:
    """Serialise window-inference across sessions; one background consumer per process."""

    def __init__(
        self,
        *,
        transcribe_window_fn: Callable[..., Awaitable[object]],
        deadline_multiplier: float,
        worker_id: str,
    ) -> None:
        self._fn = transcribe_window_fn
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._stop = asyncio.Event()
        self._consumer_task: asyncio.Task[None] | None = None
        self._deadline_multiplier = deadline_multiplier
        self._worker_id = worker_id
        self._consecutive_deadline_misses = 0

    async def __aenter__(self) -> InferenceQueue:
        self._consumer_task = asyncio.create_task(self._consume())
        return self

    async def __aexit__(self, *_: object) -> None:
        self._stop.set()
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._consumer_task

    async def submit(
        self,
        pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        prev_text: str | None,
    ) -> object:
        """Enqueue a window for inference; return the WindowResult."""
        audio_seconds = pcm.shape[0] / 16_000.0
        submitted_at = time.monotonic()
        deadline = submitted_at + max(2.0, audio_seconds * self._deadline_multiplier)
        fut: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        await self._queue.put(
            _Job(
                pcm=pcm,
                language=language,
                prompt=prompt,
                prev_text=prev_text,
                future=fut,
                deadline_at=deadline,
                submitted_at=submitted_at,
            )
        )
        return await fut

    async def _consume(self) -> None:
        while not self._stop.is_set():
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            t0 = time.monotonic()
            try:
                result = await self._fn(
                    job.pcm,
                    language=job.language,
                    prompt=job.prompt,
                    prev_text=job.prev_text,
                )
                # Compare completion time, not start time, or a slow run never registers a miss.
                done_at = time.monotonic()
                if done_at > job.deadline_at:
                    self._consecutive_deadline_misses += 1
                    logger.warning(
                        "inference.deadline_missed",
                        extra={
                            "worker_id": self._worker_id,
                            "consecutive": self._consecutive_deadline_misses,
                            # queue wait = oversubscription, run time = model/device
                            "overrun_ms": round((done_at - job.deadline_at) * 1000, 1),
                            "queue_wait_ms": round((t0 - job.submitted_at) * 1000, 1),
                            "run_ms": round((done_at - t0) * 1000, 1),
                        },
                    )
                else:
                    self._consecutive_deadline_misses = 0
                if not job.future.done():
                    job.future.set_result(result)
            except Exception as exc:  # noqa: BLE001
                if not job.future.done():
                    job.future.set_exception(exc)
