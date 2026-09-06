"""``ChatProvider`` that replays recorded results — the ``test`` env backend.

A cassette is one JSON file per (model, prompt, schema) key. Missing keys
fail loudly (``ProviderError(unavailable)``) rather than inventing text, so
a test that reaches the network by accident cannot pass by luck.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .errors import ErrorKind, ProviderError
from .protocols import JsonSchema, ProviderResult


def cassette_key(model_id: str, prompt: str, schema: JsonSchema | None, system: str | None) -> str:
    payload = json.dumps(
        {"model": model_id, "prompt": prompt, "schema": schema, "system": system}, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


class RecordedChatProvider:
    def __init__(
        self, *, backend: str, cassette_dir: str | Path, model_id: str = "recorded"
    ) -> None:
        self.backend = backend
        self.model_id = model_id
        self._dir = Path(cassette_dir)

    async def probe(self) -> None:
        if not self._dir.is_dir():
            raise ProviderError(
                ErrorKind.UNAVAILABLE, f"cassette dir missing: {self._dir}", backend=self.backend
            )

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> ProviderResult:
        started = time.monotonic()
        key = cassette_key(self.model_id, prompt, schema, system)
        path = self._dir / f"{key}.json"
        if not path.is_file():
            raise ProviderError(
                ErrorKind.UNAVAILABLE,
                f"no cassette {key} (record it with scripts/eval/record_cassette.py)",
                backend=self.backend,
            )
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        text = str(data["text"])
        parsed = json.loads(text) if schema is not None else None
        return ProviderResult(
            text=text,
            json=parsed,
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            latency_ms=int((time.monotonic() - started) * 1000),
            backend=self.backend,
            model_id=self.model_id,
            structured_mode="recorded",
            finish_reason="stop",
        )

    def record(
        self, prompt: str, schema: JsonSchema | None, system: str | None, result: ProviderResult
    ) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{cassette_key(self.model_id, prompt, schema, system)}.json"
        path.write_text(
            json.dumps(
                {
                    "text": result.text,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "recorded_from": {"backend": result.backend, "model_id": result.model_id},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    async def aclose(self) -> None:
        return None
