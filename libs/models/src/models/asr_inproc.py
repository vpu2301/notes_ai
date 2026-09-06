"""``ASRProvider`` over the existing in-process faster-whisper engine.

Default for CI and self-host. The engine (asr-worker's ``WhisperEngine``)
stays where it is — this wrapper adapts it to the provider contract without
moving 500 lines, so behaviour on ``inproc_cpu_asr`` is identical to the
pre-seam worker (parity test in ``tests/unit/test_asr_inproc.py``).
Hoisting the engine itself into a lib is the recorded coupling debt
(pyproject import-linter note), not this sprint.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

import numpy as np

from asr_models import TranscriptionOutput

from .protocols import ShouldCancel
from .usage import UsageRecord, emit


class InProcEngine(Protocol):
    """Duck-typed shape of asr-worker's ``WhisperEngine``."""

    @property
    def model_name(self) -> str: ...

    @property
    def is_loaded(self) -> bool: ...

    @property
    def warmup_seconds(self) -> float: ...

    def load(self) -> None: ...

    async def transcribe(
        self,
        audio_pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
    ) -> TranscriptionOutput: ...


class InProcASRProvider:
    def __init__(self, engine: InProcEngine, *, backend: str = "inproc_cpu_asr") -> None:
        self.backend = backend
        self._engine = engine

    @property
    def engine(self) -> InProcEngine:
        return self._engine

    @property
    def model_name(self) -> str:
        return self._engine.model_name

    @property
    def is_loaded(self) -> bool:
        return self._engine.is_loaded

    @property
    def warmup_seconds(self) -> float:
        return self._engine.warmup_seconds

    async def warm_up(self) -> None:
        # Weight loading is CPU-bound and synchronous; keep the loop free.
        await asyncio.to_thread(self._engine.load)

    async def transcribe(
        self,
        audio_pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
    ) -> TranscriptionOutput:
        started = time.monotonic()
        audio_seconds = float(len(audio_pcm)) / 16_000
        try:
            output = await self._engine.transcribe(
                audio_pcm, language=language, prompt=prompt, should_cancel=should_cancel
            )
        except Exception as exc:
            emit(
                UsageRecord(
                    backend=self.backend,
                    model_id=self._engine.model_name,
                    operation="asr.transcribe",
                    ok=False,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    audio_seconds=audio_seconds,
                    error_kind=type(exc).__name__,
                )
            )
            raise
        emit(
            UsageRecord(
                backend=self.backend,
                model_id=self._engine.model_name,
                operation="asr.transcribe",
                ok=True,
                latency_ms=int((time.monotonic() - started) * 1000),
                audio_seconds=audio_seconds,
            )
        )
        return output

    async def aclose(self) -> None:
        return None
