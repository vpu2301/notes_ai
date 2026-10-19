"""A chat provider with one stage's settings (S3 profiles): its temperature on every
call, its output-token limit as a ceiling, and a timeout around each call. Only
settings the profile validated against the backend's capabilities ever get here;
an unset one leaves the pipeline's own value. Everything else is the inner provider.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any


class StageProvider:
    def __init__(
        self,
        inner: Any,
        *,
        stage: str,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._inner = inner
        self.stage = stage
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._timeout_s = timeout_s

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> Any:
        if self._max_output_tokens is not None:
            max_tokens = min(max_tokens, self._max_output_tokens)
        call = self._inner.complete(
            prompt,
            schema,
            max_tokens=max_tokens,
            temperature=temperature if self._temperature is None else self._temperature,
            system=system,
        )
        if self._timeout_s is None:
            return await call
        return await asyncio.wait_for(call, timeout=self._timeout_s)

    def __getattr__(self, name: str) -> Any:
        # backend, model_id, context_window, small_model, probe, aclose …
        return getattr(self._inner, name)


class Metered:
    """Counts what one run spent, per call: the backend and model that actually
    answered, tokens, latency, failures by kind, and the sha256 of the system text it
    sent (P1-01: compared with the resolver's). Numbers, names and hashes only."""

    def __init__(self, inner: Any, *, stage: str) -> None:
        self._inner = inner
        self.stage = stage
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        system = kwargs.get("system")
        sent = hashlib.sha256(system.encode("utf-8")).hexdigest() if system else None
        try:
            result = await self._inner.complete(*args, **kwargs)
        except Exception as exc:
            self.calls.append(
                {
                    "stage": self.stage,
                    "backend": getattr(self._inner, "backend", None),
                    "model_id": getattr(self._inner, "model_id", None),
                    "ok": False,
                    "error_kind": str(getattr(exc, "kind", type(exc).__name__)),
                    "system_sha": sent,
                }
            )
            raise
        self.calls.append(
            {
                "stage": self.stage,
                "backend": getattr(self._inner, "backend", None),
                "model_id": getattr(self._inner, "model_id", None),
                "ok": True,
                "system_sha": sent,
                "input_tokens": int(getattr(result, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(result, "output_tokens", 0) or 0),
                "latency_ms": int(getattr(result, "latency_ms", 0) or 0),
            }
        )
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
