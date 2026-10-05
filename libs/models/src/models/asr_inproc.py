"""``ASRProvider`` adapting asr-worker's in-process ``WhisperEngine`` to the provider contract (CI / self-host default)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Protocol

import numpy as np

from asr_models import TranscriptionOutput

from .protocols import ShouldCancel, SpeechRun
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
        second_pass: bool = False,
    ) -> TranscriptionOutput: ...

    async def transcribe_runs(
        self,
        audio_pcm: np.ndarray,
        runs: Sequence[SpeechRun],
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
        group_seconds: float = 300.0,
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
        await asyncio.to_thread(self._engine.load)

    async def transcribe(
        self,
        audio_pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
        second_pass: bool = False,
    ) -> TranscriptionOutput:
        started = time.monotonic()
        audio_seconds = float(len(audio_pcm)) / 16_000
        try:
            if second_pass:
                output = await self._engine.transcribe(
                    audio_pcm,
                    language=language,
                    prompt=prompt,
                    should_cancel=should_cancel,
                    second_pass=True,
                )
            else:
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

    async def transcribe_runs(
        self,
        audio_pcm: np.ndarray,
        runs: Sequence[SpeechRun],
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
        group_seconds: float = 300.0,
    ) -> TranscriptionOutput:
        """The worker's planned runs, one engine call."""
        started = time.monotonic()
        audio_seconds = sum(r.end_ms - r.start_ms for r in runs) / 1000
        try:
            output = await self._engine.transcribe_runs(
                audio_pcm,
                runs,
                language=language,
                prompt=prompt,
                should_cancel=should_cancel,
                group_seconds=group_seconds,
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
