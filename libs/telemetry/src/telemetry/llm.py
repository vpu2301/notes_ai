"""LLM call telemetry (sprint 3): every HTTP attempt of a model call becomes one ``llm_call``
row plus one ``llm_call`` span (a child of whatever stage span is open), with tokens exactly as
the provider reported them, an accounting note, and nulls-with-reasons for what was not said.

Wiring, once per process::

    telemetry.llm.install(models.set_attempt_sink)

and around each call site::

    result = await telemetry.llm.instrumented_call(
        "note_write", provider="openai_compat", model=..., backend=..., fn=lambda: p.complete(...))

The provider emits ``models.AttemptRecord``s (duck-typed here; this lib does not import
``models``). Mapping per backend: telemetry-sprints/design/LLM_PROVIDERS.md."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from . import context, metrics, overhead, store
from .schema import Device, ExecutionMode, LlmCall, Reason, SpanStatus
from .spans import record_span

logger = logging.getLogger("telemetry.llm")


PURPOSES = frozenset(
    {"note_write", "note_merge", "note_check", "note_ask", "provider_probe", "inline_completion"}
)
# error_kind (models.ErrorKind values) → the subtype that tells retries apart.
_SUBTYPES = {
    "rate_limited": "rate_limit", "timeout": "timeout", "schema_invalid": "parse",
    "context_exceeded": "context_length", "warming": "warming", "unavailable": "unavailable",
    "auth": "auth", "provider_not_configured": "config",
}  # fmt: skip
_NOTES = {
    "openai_compat": (
        "OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and "
        "completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as "
        "reported, subsets never added again"
    ),
}


@dataclass(frozen=True)
class _CallSite:
    purpose: str
    provider: str
    backend: str
    model: str | None
    execution_mode: ExecutionMode
    device: Device | None
    device_reason: Reason | None


_site: ContextVar[_CallSite | None] = ContextVar("telemetry_llm_site", default=None)


def execution_mode_for(base_url: str | None) -> ExecutionMode:
    """Where the model runs, from the address the caller uses: a server on this machine's host
    (Ollama, whisper.cpp on the Mac) is ``native``; a compose/k8s service name is
    ``container``; anything else is ``remote``."""
    host = (urlparse(base_url or "").hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
        return "native"
    if host and "." not in host:
        return "container"
    return "remote"


async def instrumented_call[T](
    purpose: str,
    *,
    provider: str,
    model: str | None,
    backend: str,
    fn: Callable[[], Awaitable[T]],
    streaming: bool = False,
    base_url: str | None = None,
    device: Device | None = None,
) -> T:
    """Run ``fn`` (one model call, retries included) as ``purpose``; each attempt the provider
    reports is recorded. Fail-open: the call's result or exception passes through unchanged."""
    del streaming  # the attempt record says whether it streamed
    mode = execution_mode_for(base_url)
    reason: Reason | None = None
    if device is None:
        reason = "not_applicable" if mode == "remote" else "unavailable"
    token = _site.set(_CallSite(purpose, provider, backend, model, mode, device, reason))
    try:
        return await fn()
    finally:
        _site.reset(token)


_call_device: ContextVar[Device | None] = ContextVar("telemetry_llm_device", default=None)


def set_call_device(device: Device | None) -> object:
    """The device the caller observed for this context's model (e.g. Ollama ``/api/ps``)."""
    return _call_device.set(device)


async def call[T](purpose: str, provider: Any, fn: Callable[[], Awaitable[T]]) -> T:
    """:func:`instrumented_call` with the backend, model and address read off a
    ``models`` chat provider."""
    return await instrumented_call(
        purpose,
        provider=getattr(provider, "kind", None) or "openai_compat",
        model=getattr(provider, "model_id", None),
        backend=str(
            getattr(provider, "backend_name", None)
            or getattr(provider, "backend", None)
            or "unknown"
        ),
        fn=fn,
        base_url=getattr(provider, "base_url", None),
        device=_call_device.get(),
    )


def instrumented_call_sync[T](purpose: str, *, provider: str, model: str | None, backend: str,
                           fn: Callable[[], T], base_url: str | None = None) -> T:  # fmt: skip
    mode = execution_mode_for(base_url)
    token = _site.set(
        _CallSite(
            purpose,
            provider,
            backend,
            model,
            mode,
            None,
            "not_applicable" if mode == "remote" else "unavailable",
        )  # fmt: skip
    )
    try:
        return fn()
    finally:
        _site.reset(token)


def install(set_attempt_sink: Callable[[Callable[[Any], None] | None], None]) -> None:
    """Register :func:`on_attempt` as the process's attempt sink (``models.set_attempt_sink``)."""
    set_attempt_sink(on_attempt)


def _tokens(record: Any) -> tuple[dict[str, int | None], str, str, dict[str, Reason]]:
    """``(counts, token_source, accounting note, reasons)``."""
    counts: dict[str, int | None] = {
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "cached_input_tokens": record.cached_input_tokens,
        "reasoning_tokens": record.reasoning_tokens,
    }
    reasons: dict[str, Reason] = {}
    note = _NOTES.get("openai_compat", "")
    if record.input_tokens is not None or record.output_tokens is not None:
        source = "provider"
        for key in ("cached_input_tokens", "reasoning_tokens"):
            if counts[key] is None:
                reasons[key] = "unavailable"  # this provider's usage object has no such field
        for key in ("input_tokens", "output_tokens"):
            if counts[key] is None:
                reasons[key] = "unavailable"
        return counts, source, note, reasons
    # No usage object: estimate from character lengths (no tokenizer in the repo).
    source = "estimated"
    counts["input_tokens"] = round(record.prompt_chars / 4) if record.prompt_chars else None
    counts["output_tokens"] = (
        round(record.completion_chars / 4) if record.completion_chars else None
    )
    for key in ("input_tokens", "output_tokens"):
        if counts[key] is None:
            reasons[key] = "unavailable"
    reasons["cached_input_tokens"] = reasons["reasoning_tokens"] = "unavailable"
    return counts, source, "estimated: characters / 4 (the provider sent no usage object)", reasons


def on_attempt(record: Any) -> None:
    """Attempt sink: metrics always; a row + span when a run is current. Never raises."""
    site = _site.get()
    purpose = site.purpose if site else "unknown"
    run = context.current_run()
    run_id = run.processing_run_id if run else None
    try:
        with overhead.measure(run_id):
            status: SpanStatus = "ok" if record.ok else "error"
            model = record.response_model or (site.model if site else None) or record.model_id
            family = metrics.model_family(model)
            provider = site.provider if site else "openai_compat"
            metrics.llm_calls_total.add(
                1,
                {
                    "provider": provider,
                    "model_family": family,
                    "purpose": purpose,
                    "status": status,
                },
            )
            counts, source, note, reasons = _tokens(record)
            for direction, key in (("input", "input_tokens"), ("output", "output_tokens"),
                                   ("cached", "cached_input_tokens"), ("reasoning", "reasoning_tokens")):  # fmt: skip
                if counts[key]:
                    metrics.llm_tokens_total.add(
                        counts[key] or 0,
                        {
                            "provider": provider,
                            "model_family": family,
                            "direction": direction,
                            "source": source,
                        },
                    )
            if run is None or purpose not in PURPOSES:
                return
            total = record.latency_ms / 1000
            tps = record.provider_timings.get("predicted_per_second")
            if record.queue_wait_ms is None:
                reasons["queue_wait_seconds"] = "unavailable"
            if record.model_load_ms is None:
                reasons["model_load_seconds"] = (
                    "not_applicable" if record.attempt == 1 else "unavailable"
                )
            reasons["time_to_first_token_seconds"] = "not_applicable"  # non-streaming call
            if tps is None:
                reasons["generation_tokens_per_second"] = "not_supported"
            for key in ("prompt_chars", "completion_chars"):
                if getattr(record, key) is None:
                    reasons[key] = "unavailable"
            if model is None:
                reasons["model"] = "unavailable"
            subtype = _SUBTYPES.get(record.error_kind or "", "other") if not record.ok else None
            span_id = record_span(
                "llm_call",
                f"llm.{purpose}",
                start_wall=record.started_at,
                end_wall=record.ended_at,
                status=status,
                attributes={
                    "purpose": purpose,
                    "backend": record.backend,
                    "provider": provider,
                    "llm_attempt": record.attempt,
                    "http_status": record.http_status,
                    "error_subtype": subtype,
                    "finish_reason": record.finish_reason,
                    "structured_mode": record.structured_mode,
                },  # fmt: skip
                clock_source="monotonic",
                run=run,
            )
            if span_id is None:
                return
            call = LlmCall(
                llm_call_id=uuid4(),
                span_id=span_id,
                processing_run_id=run.processing_run_id,
                tenant_id=run.tenant_id,
                purpose=purpose,  # type: ignore[arg-type]
                provider=provider,
                model=model,
                backend=record.backend,
                execution_mode=site.execution_mode if site else "remote",
                streaming=bool(record.streaming),
                attempt=max(1, int(record.attempt)),
                status=status,
                queue_wait_seconds=record.queue_wait_ms / 1000
                if record.queue_wait_ms is not None
                else None,
                model_load_seconds=record.model_load_ms / 1000
                if record.model_load_ms is not None
                else None,
                total_latency_seconds=round(total, 4),
                input_tokens=counts["input_tokens"],
                output_tokens=counts["output_tokens"],
                cached_input_tokens=counts["cached_input_tokens"],
                reasoning_tokens=counts["reasoning_tokens"],
                token_source=source,  # type: ignore[arg-type]
                token_accounting_note=note,
                generation_tokens_per_second=float(tps) if tps is not None else None,
                prompt_chars=record.prompt_chars,
                completion_chars=record.completion_chars,
                error_category="llm" if not record.ok else None,
                null_reasons=reasons,
            )
            store.get().llm_call(call)
    except Exception:  # noqa: BLE001 — telemetry never fails a model call
        metrics.write_errors_total.add(1, {"entity": "llm_call"})
        logger.debug("telemetry.llm_attempt_failed", exc_info=True)


async def ollama_device(base_url: str, client: Any, *, ttl_seconds: float = 300.0) -> Device | None:
    """Ollama's ``/api/ps``: a loaded model with ``size_vram > 0`` is (partly) on the GPU —
    observed from the server at runtime; cached per address for ``ttl_seconds``."""
    now = time.monotonic()
    hit = _device_cache.get(base_url)
    if hit and now - hit[0] < ttl_seconds:
        return hit[1]
    root = base_url.rstrip("/").removesuffix("/v1")
    device: Device | None = None
    try:
        resp = await client.get(f"{root}/api/ps", timeout=1.0)
        models = resp.json().get("models") or []
        if models:
            vram = sum(int(m.get("size_vram") or 0) for m in models)
            size = sum(int(m.get("size") or 0) for m in models) or 1
            value = (
                "gpu"
                if vram >= size
                else ("cpu" if vram == 0 else f"gpu_partial:{vram / size:.2f}")
            )
            device = Device(value=value, observation="observed")
    except Exception:  # noqa: BLE001 — no device is better than a guessed one
        device = None
    _device_cache[base_url] = (now, device)
    return device


_device_cache: dict[str, tuple[float, Device | None]] = {}
