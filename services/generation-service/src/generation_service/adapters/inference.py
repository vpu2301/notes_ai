"""Inference backend seam: llama-server ``/completion`` (default, raw prompt so the
Gemma turn wrapper is applied here) or Ollama ``/api/generate`` (applies its own template).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from .. import config

# Gemma 3 turn format; without it greedy gemma3 loops (llama.cpp path only).
_GEMMA_TURN = "<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"
# `\n\n` keeps a completion inside the current paragraph.
_STOP = ["<end_of_turn>", "\n\n"]


@dataclass(slots=True, frozen=True)
class CompletionResult:
    text: str
    model: str


@runtime_checkable
class InferenceClient(Protocol):
    async def complete(self, *, prompt: str, max_tokens: int) -> CompletionResult: ...

    async def ready(self) -> bool: ...

    async def aclose(self) -> None: ...


class LlamaCppClient:
    def __init__(self, *, base_url: str, model: str) -> None:
        self._model = model
        self._http = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def complete(self, *, prompt: str, max_tokens: int) -> CompletionResult:
        resp = await self._http.post(
            "/completion",
            json={
                "prompt": _GEMMA_TURN.format(prompt=prompt),
                "n_predict": max_tokens,
                "temperature": 0,
                "stop": _STOP,
                "cache_prompt": True,
            },
        )
        resp.raise_for_status()
        return CompletionResult(text=resp.json().get("content", ""), model=self._model)

    async def ready(self) -> bool:
        try:
            resp = await self._http.get("/health", timeout=2.0)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    async def aclose(self) -> None:
        await self._http.aclose()


class OllamaClient:
    def __init__(self, *, base_url: str, model: str) -> None:
        self._model = model
        self._http = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def complete(self, *, prompt: str, max_tokens: int) -> CompletionResult:
        resp = await self._http.post(
            "/api/generate",
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0,
                    "stop": _STOP,
                },
            },
        )
        resp.raise_for_status()
        return CompletionResult(text=resp.json().get("response", ""), model=self._model)

    async def ready(self) -> bool:
        try:
            resp = await self._http.get("/api/tags", timeout=2.0)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    async def aclose(self) -> None:
        await self._http.aclose()


def build_inference_client(settings: config.Settings) -> InferenceClient:
    if settings.gen_backend == "ollama":
        return OllamaClient(base_url=settings.gen_base_url, model=settings.gen_model)
    return LlamaCppClient(base_url=settings.gen_base_url, model=settings.gen_model)
