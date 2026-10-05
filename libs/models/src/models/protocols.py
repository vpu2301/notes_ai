"""The three vendor-neutral provider contracts; ``backend``/``model_id`` on each result record provenance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

from asr_models import TranscriptionOutput

JsonValue = dict[str, Any] | list[Any]
JsonSchema = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """One completed chat call; ``json`` only when a schema was requested and parsed; token counts 0 if unreported."""

    text: str
    json: JsonValue | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    backend: str
    model_id: str
    structured_mode: str
    finish_reason: str | None = None


@runtime_checkable
class ChatProvider(Protocol):
    """Single-turn completion with optional JSON-schema constrained output."""

    backend: str
    model_id: str
    # A small local model the document engine gives simpler work to.
    small_model: bool

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> ProviderResult: ...

    async def probe(self) -> None:
        """Cheap liveness + capability check; raises ``ProviderError``."""
        ...

    async def aclose(self) -> None: ...


ShouldCancel = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class SpeechRun:
    """One planned VAD speech run: where it is in the recording and the language it is decoded in."""

    start_ms: int
    end_ms: int
    language: str
    other_language: bool = False


@runtime_checkable
class ASRProvider(Protocol):
    """Batch transcription of 16 kHz mono float32 PCM; word timings are a contract (ADR-0037), ``warm_up`` rejects without."""

    backend: str

    @property
    def model_name(self) -> str: ...

    @property
    def is_loaded(self) -> bool: ...

    @property
    def warmup_seconds(self) -> float: ...

    async def warm_up(self) -> None:
        """Load weights / probe the endpoint. Raises ``ProviderError``."""
        ...

    async def transcribe(
        self,
        audio_pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
        second_pass: bool = False,
    ) -> TranscriptionOutput:
        """``second_pass``: a lost speech run, decoded without prompt or conditioning and beam ≥ 5 where the backend allows."""
        ...

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
        """Decode the planned runs, each in its own language, onto the recording's clock; other-language runs
        set ``Segment.language``. HTTP backends group runs of one language by ``group_seconds``."""
        ...

    async def aclose(self) -> None: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Declared so the registry's kind table is total; not implemented yet."""

    backend: str
    model_id: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def aclose(self) -> None: ...
