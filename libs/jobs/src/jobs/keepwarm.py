"""Scheduled keep-warm probes for scale-to-zero endpoints, off by default."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from observability import run_periodic

from . import metrics

logger = logging.getLogger("jobs.keepwarm")


@dataclass(frozen=True, slots=True)
class KeepWarmSchedule:
    enabled: bool = False
    timezone: str = "Europe/Berlin"
    weekdays: frozenset[int] = field(default_factory=lambda: frozenset({0, 1, 2, 3, 4}))  # Mon–Fri
    start_hour: int = 8
    end_hour: int = 19
    interval_seconds: float = 600.0

    def is_active(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        local = now.astimezone(ZoneInfo(self.timezone))
        return local.weekday() in self.weekdays and self.start_hour <= local.hour < self.end_hour


ProbeFn = Callable[[], Awaitable[None]]


async def keep_warm_task(
    schedule: KeepWarmSchedule,
    probes: dict[str, ProbeFn],
    *,
    now: Callable[[], datetime],
) -> None:
    """Run forever: every ``interval_seconds`` inside the window, probe each backend."""

    async def tick() -> None:
        if not schedule.is_active(now()):
            return
        for backend, probe in probes.items():
            try:
                await probe()
                metrics.model_keepwarm_probes_total.add(1, {"backend": backend, "outcome": "ok"})
            except Exception as exc:
                kind = getattr(exc, "kind", type(exc).__name__)
                metrics.model_keepwarm_probes_total.add(
                    1, {"backend": backend, "outcome": str(kind)}
                )
                logger.warning(
                    "jobs.keepwarm_probe_failed",
                    extra={"backend": backend, "error_kind": str(kind)},
                )

    await run_periodic(
        job_name="model_keep_warm", interval_seconds=schedule.interval_seconds, fn=tick
    )
