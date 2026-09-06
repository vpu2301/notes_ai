"""The three provider contracts every worker codes against.

Nothing in here names a vendor. A worker receives a provider from
``models.registry`` and calls ``complete`` / ``transcribe`` / ``embed``;
which HTTP server, which weights and which region answered is recorded on
the result (``backend``, ``model_id``) for provenance and never chosen here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

from asr_models import TranscriptionOutput

JsonValue = dict[str, Any] | list[Any]
JsonSchema = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """One completed chat call.

    ``text`` is the raw assistant content; ``json`` is populated only when a
    schema was requested and the content parsed. Token counts come from the
    backend's ``usage`` block (0 when the server does not report them).
    """

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


@runtime_checkable
class ASRProvider(Protocol):
    """Batch transcription of 16 kHz mono float32 PCM with per-word timings.

    Word timings are a contract (ADR-0037 clip replay depends on them); a
    backend that cannot produce them is rejected by ``probe``/``warm_up``.
    """

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
    ) -> TranscriptionOutput: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Completed in DEP-S5. Declared now so the registry's kind table is total."""

    backend: str
    model_id: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def aclose(self) -> None: ...
