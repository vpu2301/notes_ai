"""Candidate ASR engine in the shadow: a sample of jobs, within a shared daily budget.

Only counts and rates are kept; the shadow transcript is never stored, logged or returned.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from opentelemetry import metrics

from asr_models import ShadowDiagnostics, TranscriptionOutput

from .config import settings

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.asr.worker.shadow")
_shadow_total = _meter.create_counter(
    "mdx_asr_shadow_runs_total",
    description="Candidate-engine shadow decodes by outcome (ran | skipped reason)",
    unit="1",
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
BUDGET_KEY = "mdx:asr:shadow:audio_s:{day}"


def _tokens(output: TranscriptionOutput) -> list[str]:
    return [t.casefold() for seg in output.segments for t in _WORD.findall(seg.text)]


def _name_forms(output: TranscriptionOutput) -> int:
    forms: set[str] = set()
    for seg in output.segments:
        words = _WORD.findall(seg.text)
        forms.update(w for k, w in enumerate(words) if k > 0 and w[:1].isupper())
    return len(forms)


def _edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def compare(
    primary: TranscriptionOutput, shadow: TranscriptionOutput, *, backend: str, rtf: float
) -> ShadowDiagnostics:
    """Numbers only; the distance is computed on the first 4 000 words (quadratic)."""
    a, b = _tokens(primary), _tokens(shadow)
    distance = _edit_distance(a[:4000], b[:4000])
    return ShadowDiagnostics(
        backend=backend[:32],
        words_primary=len(a),
        words_shadow=len(b),
        word_disagreement=round(distance / max(1, min(len(a), 4000)), 4),
        name_forms_primary=_name_forms(primary),
        name_forms_shadow=_name_forms(shadow),
        dropped_primary=len(primary.diagnostics.dropped_segments),
        dropped_shadow=len(shadow.diagnostics.dropped_segments),
        rtf=round(rtf, 4),
    )


async def _within_budget(redis: Any, audio_seconds: float) -> bool:
    """Reserve this job's audio against today's budget; fail closed."""
    if settings.asr_shadow_budget_hours <= 0:
        return False
    key = BUDGET_KEY.format(day=datetime.now(UTC).strftime("%Y-%m-%d"))
    try:
        used = float(await redis.incrbyfloat(key, audio_seconds))
        await redis.expire(key, 2 * 86_400)
    except Exception:  # noqa: BLE001 — no budget bookkeeping, no shadow
        return False
    return used <= settings.asr_shadow_budget_hours * 3600


def sampled(rng: Callable[[], float] = random.random) -> bool:
    return bool(settings.asr_shadow_backend) and rng() < settings.asr_shadow_rate


async def run(
    shadow_engine: Any,
    *,
    redis: Any,
    decode: Callable[..., Awaitable[TranscriptionOutput]],
    primary: TranscriptionOutput,
    audio_seconds: float,
    decode_kwargs: dict[str, Any],
) -> ShadowDiagnostics | None:
    """The shadow comparison for one job, or None when it was not sampled."""
    backend = settings.asr_shadow_backend
    if not await _within_budget(redis, audio_seconds):
        _shadow_total.add(1, {"outcome": "budget"})
        return ShadowDiagnostics(backend=backend[:32], skipped="budget")
    started = time.monotonic()
    try:
        if not shadow_engine.is_loaded:
            await shadow_engine.warm_up()
        state = type("ShadowState", (), {"engine": shadow_engine})()
        out = await decode(state, **decode_kwargs)
    except TimeoutError:
        _shadow_total.add(1, {"outcome": "timeout"})
        return ShadowDiagnostics(backend=backend[:32], skipped="timeout")
    except Exception as exc:  # noqa: BLE001 — the shadow never costs the primary
        logger.warning(
            "asr.shadow_failed", extra={"backend": backend, "error_class": type(exc).__name__}
        )
        _shadow_total.add(1, {"outcome": "error"})
        return ShadowDiagnostics(backend=backend[:32], skipped="error")
    seconds = time.monotonic() - started
    _shadow_total.add(1, {"outcome": "ran"})
    return compare(primary, out, backend=backend, rtf=seconds / max(audio_seconds, 1e-6))


async def bounded(task: Awaitable[ShadowDiagnostics | None]) -> ShadowDiagnostics | None:
    """Wait for the shadow at most the configured time beyond the primary."""
    try:
        return await asyncio.wait_for(task, timeout=settings.asr_shadow_max_wait_seconds)
    except TimeoutError:
        _shadow_total.add(1, {"outcome": "timeout"})
        return ShadowDiagnostics(backend=settings.asr_shadow_backend[:32], skipped="timeout")
