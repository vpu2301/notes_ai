"""One HTTP contract for every OpenAI-compatible chat server.

Ollama, LM Studio, MLX-serve, llama-server, TGI, vLLM and Hugging Face
Inference Endpoints all speak ``POST /v1/chat/completions``. What differs —
how structured output is requested, auth, cold start, context — is
configuration on the backend, not a class per vendor.

Retry policy (spec §D): retries only for ``warming`` / ``unavailable`` /
``timeout``; ``warming`` retries are bounded by the backend's
``cold_start_seconds``; everything else surfaces immediately.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .errors import PROVIDER_RETRY_KINDS, ErrorKind, ProviderError, register_secret
from .protocols import JsonSchema, JsonValue, ProviderResult
from .usage import UsageRecord, emit

logger = logging.getLogger("models.openai_compat")

CONNECT_TIMEOUT_S = 5.0
MAX_ATTEMPTS = 3
WARMING_POLL_S = 10.0
_ERROR_TEXT_MAX = 200
_CONTEXT_HINTS = re.compile(
    r"context|too many tokens|maximum.*length|max_tokens|token limit|prompt is too long", re.I
)
_SCHEMA_UNSUPPORTED_HINTS = re.compile(
    r"response_format|json_schema|guided|unsupported|not supported|invalid.*format", re.I
)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)

SleepFn = Callable[[float], Awaitable[None]]


class OpenAICompatibleChatProvider:
    def __init__(
        self,
        *,
        backend: str,
        base_url: str,
        model_id: str,
        auth_token: str | None = None,
        structured_output: str = "json_schema",
        timeout_s: float = 120.0,
        cold_start_seconds: int = 0,
        context_window: int = 32768,
        max_concurrency: int = 1,
        client: httpx.AsyncClient | None = None,
        sleep: SleepFn | None = None,
        request_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.backend = backend
        self.request_overrides: dict[str, Any] = dict(request_overrides or {})
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.context_window = context_window
        self._requested_mode = structured_output
        self._mode = "json_schema" if structured_output == "probe" else structured_output
        self._cold_start_seconds = cold_start_seconds
        self._timeout_s = timeout_s
        self._sleep: SleepFn = sleep or asyncio.sleep
        self._sem = asyncio.Semaphore(max_concurrency)
        register_secret(auth_token)
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S),
        )
        self._owns_client = client is None

    @property
    def structured_mode(self) -> str:
        return self._mode

    # ── public API ──────────────────────────────────────────────────────
    async def probe(self) -> None:
        """Liveness + (for ``probe`` mode) which structured-output flavour works."""
        if self._requested_mode == "probe":
            schema: JsonSchema = {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            }
            try:
                await self.complete('Reply with JSON: {"ok": true}', schema, max_tokens=16)
            except ProviderError as exc:
                if exc.kind is ErrorKind.SCHEMA_INVALID or (exc.status in (400, 422)):
                    self._mode = "json_object"
                    logger.info(
                        "models.structured_probe",
                        extra={"backend": self.backend, "fallback": self._mode},
                    )
                    await self.complete('Reply with JSON: {"ok": true}', schema, max_tokens=16)
                else:
                    raise
        else:
            # 64, not 8: a reasoning model spends tokens before answering.
            await self.complete("Reply with the single word: pong", None, max_tokens=64)

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
        workspace_id: str | None = None,
    ) -> ProviderResult:
        body = self._build_body(
            prompt, schema, max_tokens=max_tokens, temperature=temperature, system=system
        )
        started = time.monotonic()
        attempts = 0
        waited_s = 0.0  # time slept on `warming`; bounded by cold_start_seconds
        async with self._sem:
            while True:
                attempts += 1
                try:
                    data = await self._post(body)
                    result = self._parse(
                        data, schema, latency_ms=int((time.monotonic() - started) * 1000)
                    )
                except ProviderError as exc:
                    if self._should_retry(exc, attempts, waited_s):
                        delay = self._retry_delay(exc, attempts, waited_s)
                        waited_s += delay
                        logger.info(
                            "models.retry",
                            extra={
                                "backend": self.backend,
                                "kind": str(exc.kind),
                                "attempt": attempts,
                                "delay_s": delay,
                            },
                        )
                        await self._sleep(delay)
                        continue
                    emit(
                        UsageRecord(
                            backend=self.backend,
                            model_id=self.model_id,
                            operation="chat.complete",
                            ok=False,
                            latency_ms=int((time.monotonic() - started) * 1000),
                            structured_mode=self._mode,
                            error_kind=str(exc.kind),
                            workspace_id=workspace_id,
                            attempts=attempts,
                        )
                    )
                    raise
                emit(
                    UsageRecord(
                        backend=self.backend,
                        model_id=self.model_id,
                        operation="chat.complete",
                        ok=True,
                        latency_ms=result.latency_ms,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        structured_mode=self._mode,
                        workspace_id=workspace_id,
                        attempts=attempts,
                    )
                )
                return result

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ── request ─────────────────────────────────────────────────────────
    def _build_body(
        self,
        prompt: str,
        schema: JsonSchema | None,
        *,
        max_tokens: int,
        temperature: float,
        system: str | None,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        user = prompt
        if schema is not None and self._mode in ("json_object", "none"):
            # Servers without schema enforcement get the schema in-band.
            user = f"{prompt}\n\nRespond with a single JSON document matching this JSON Schema, and nothing else:\n{json.dumps(schema)}"
        messages.append({"role": "user", "content": user})
        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if schema is not None:
            if self._mode == "json_schema":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": schema, "strict": True},
                }
            elif self._mode == "json_object":
                body["response_format"] = {"type": "json_object"}
            elif self._mode == "guided_json":  # vLLM
                body["response_format"] = {"type": "json_object"}
                body["guided_json"] = schema
        body.update(self.request_overrides)
        return body

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._client.post("/chat/completions", json=body)
        except httpx.ConnectTimeout as exc:
            raise ProviderError(ErrorKind.TIMEOUT, "connect timeout", backend=self.backend) from exc
        except httpx.ConnectError as exc:
            raise ProviderError(
                ErrorKind.UNAVAILABLE, "connection refused", backend=self.backend
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ErrorKind.TIMEOUT,
                f"read timeout after {self._timeout_s:.0f}s",
                backend=self.backend,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ErrorKind.UNAVAILABLE, type(exc).__name__, backend=self.backend
            ) from exc
        if resp.status_code >= 400:
            raise self._map_status(resp)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(
                ErrorKind.UNAVAILABLE,
                "non-JSON response body",
                backend=self.backend,
                status=resp.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                ErrorKind.UNAVAILABLE,
                "unexpected response shape",
                backend=self.backend,
                status=resp.status_code,
            )
        return data

    def _map_status(self, resp: httpx.Response) -> ProviderError:
        status = resp.status_code
        text = _error_text(resp)
        retry_after = _retry_after(resp)
        if status in (401, 403):
            return ProviderError(
                ErrorKind.AUTH, f"HTTP {status}", backend=self.backend, status=status
            )
        if status == 429:
            return ProviderError(
                ErrorKind.RATE_LIMITED,
                f"HTTP 429 {text}",
                backend=self.backend,
                status=status,
                retry_after_s=retry_after,
            )
        if status in (408, 504):
            return ProviderError(
                ErrorKind.TIMEOUT, f"HTTP {status}", backend=self.backend, status=status
            )
        if status == 413:
            return ProviderError(
                ErrorKind.CONTEXT_EXCEEDED,
                "HTTP 413 payload too large",
                backend=self.backend,
                status=status,
            )
        if status == 503:
            kind = ErrorKind.WARMING if self._cold_start_seconds > 0 else ErrorKind.UNAVAILABLE
            return ProviderError(
                kind,
                f"HTTP 503 {text}",
                backend=self.backend,
                status=status,
                retry_after_s=retry_after,
            )
        if status in (400, 422):
            if _CONTEXT_HINTS.search(text):
                return ProviderError(
                    ErrorKind.CONTEXT_EXCEEDED,
                    f"HTTP {status} {text}",
                    backend=self.backend,
                    status=status,
                )
            if _SCHEMA_UNSUPPORTED_HINTS.search(text):
                return ProviderError(
                    ErrorKind.SCHEMA_INVALID,
                    f"HTTP {status} structured output rejected: {text}",
                    backend=self.backend,
                    status=status,
                )
            return ProviderError(
                ErrorKind.UNKNOWN, f"HTTP {status} {text}", backend=self.backend, status=status
            )
        if status == 404:
            return ProviderError(
                ErrorKind.UNAVAILABLE,
                f"HTTP 404 (model or route not served) {text}",
                backend=self.backend,
                status=status,
            )
        if status >= 500:
            return ProviderError(
                ErrorKind.UNAVAILABLE, f"HTTP {status} {text}", backend=self.backend, status=status
            )
        return ProviderError(
            ErrorKind.UNKNOWN, f"HTTP {status} {text}", backend=self.backend, status=status
        )

    # ── response ────────────────────────────────────────────────────────
    def _parse(
        self, data: dict[str, Any], schema: JsonSchema | None, *, latency_ms: int
    ) -> ProviderResult:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                ErrorKind.UNAVAILABLE, "response has no choices", backend=self.backend
            )
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError(
                ErrorKind.SCHEMA_INVALID,
                "assistant content missing or not text",
                backend=self.backend,
            )
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        if finish == "length":
            # Output was cut — with a schema that is a truncated JSON document;
            # the caller re-chunks (S2). Runbook step 2 (num_ctx) for local servers.
            raise ProviderError(
                ErrorKind.CONTEXT_EXCEEDED,
                f"output truncated (finish_reason=length, {input_tokens} in / {output_tokens} out)",
                backend=self.backend,
            )
        parsed: JsonValue | None = None
        if schema is not None:
            parsed = _parse_json(content)
            if parsed is None:
                raise ProviderError(
                    ErrorKind.SCHEMA_INVALID, "content is not valid JSON", backend=self.backend
                )
            problem = _shape_problem(parsed, schema)
            if problem:
                raise ProviderError(ErrorKind.SCHEMA_INVALID, problem, backend=self.backend)
        return ProviderResult(
            text=content,
            json=parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            backend=self.backend,
            model_id=str(data.get("model") or self.model_id),
            structured_mode=self._mode if schema is not None else "none",
            finish_reason=finish if isinstance(finish, str) else None,
        )

    # ── retry policy ────────────────────────────────────────────────────
    def _should_retry(self, exc: ProviderError, attempts: int, waited_s: float) -> bool:
        if exc.kind not in PROVIDER_RETRY_KINDS:
            return False
        if exc.kind is ErrorKind.WARMING:
            # Budget is the backend's declared cold start, counted in time we
            # actually waited (deterministic under an injected sleep).
            return waited_s < self._cold_start_seconds
        return attempts < MAX_ATTEMPTS

    def _retry_delay(self, exc: ProviderError, attempts: int, waited_s: float) -> float:
        if exc.kind is ErrorKind.WARMING:
            poll = exc.retry_after_s or WARMING_POLL_S
            return max(0.1, min(poll, self._cold_start_seconds - waited_s))
        return float(2 ** (attempts - 1))


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error", data)
            msg = err.get("message") if isinstance(err, dict) else err
            return str(msg)[:_ERROR_TEXT_MAX]
    except ValueError:
        pass
    return resp.text[:_ERROR_TEXT_MAX]


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_json(content: str) -> JsonValue | None:
    text = content.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except ValueError:
        # Some servers prepend prose; take the outermost {...}.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except ValueError:
            return None
    if isinstance(value, dict | list):
        return value
    return None


def _shape_problem(value: JsonValue, schema: JsonSchema) -> str | None:
    """Cheap top-level check (type + required keys). Full validation is the caller's (S2)."""
    expected = schema.get("type")
    if expected == "object" and not isinstance(value, dict):
        return "expected a JSON object"
    if expected == "array" and not isinstance(value, list):
        return "expected a JSON array"
    if isinstance(value, dict):
        missing = [k for k in schema.get("required", []) if k not in value]
        if missing:
            return f"missing required key(s) {missing}"
    return None
