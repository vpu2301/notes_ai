"""In-process periodic job runner (ADR-0041). The metric label is ``job_name``, not ``job``: the collector's
Prometheus exporter stamps a constant ``job`` and refuses a colliding label. The audit row is the job's own
concern via ``on_complete`` (this leaf must not import libs/audit). Jobs MUST be idempotent.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import metrics

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.scheduler")
_runs_total = _meter.create_counter(
    "mdx_scheduler_job_runs_total",
    description="Scheduled job runs by job name and outcome",
    unit="1",
)
_duration = _meter.create_histogram(
    "mdx_scheduler_job_duration_seconds",
    description="Scheduled job run duration",
    unit="s",
)


async def run_job_once(
    *,
    job_name: str,
    fn: Callable[[], Awaitable[Any]],
    on_complete: Callable[[str, Any, float], Awaitable[None]] | None = None,
) -> Any:
    """Run one iteration; job errors are logged and swallowed. ``on_complete(outcome, detail, duration)`` is best-effort."""
    started = time.monotonic()
    try:
        result = await fn()
        outcome = "ok"
        detail: Any = result
    except Exception as exc:  # noqa: BLE001 — the loop must survive
        outcome = "error"
        detail = f"{type(exc).__name__}: {exc}"
        logger.exception("scheduler.job_failed", extra={"job": job_name})
        result = None
    duration = time.monotonic() - started
    _runs_total.add(1, {"job_name": job_name, "outcome": outcome})
    _duration.record(duration, {"job_name": job_name})
    logger.info(
        "scheduler.job_finished",
        extra={"job": job_name, "outcome": outcome, "duration_s": round(duration, 3)},
    )
    if on_complete is not None:
        try:
            await on_complete(outcome, detail, duration)
        except Exception:  # noqa: BLE001 — audit is best-effort here
            logger.exception("scheduler.on_complete_failed", extra={"job": job_name})
    return result


async def run_periodic(
    *,
    job_name: str,
    interval_seconds: float,
    fn: Callable[[], Awaitable[Any]],
    on_complete: Callable[[str, Any, float], Awaitable[None]] | None = None,
) -> None:
    """Loop ``run_job_once`` forever; first iteration fires immediately."""
    while True:
        await run_job_once(job_name=job_name, fn=fn, on_complete=on_complete)
        await asyncio.sleep(interval_seconds)
