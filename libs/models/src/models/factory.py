"""Build a provider instance from a ``ResolvedBackend``.

The only place that maps ``kind`` → class. Workers call
``build_chat_provider(registry.resolve(ws, "understand"))`` and never see
a class name.
"""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .asr_http import HTTPASRProvider
from .asr_inproc import InProcASRProvider, InProcEngine
from .errors import ConfigError
from .openai_compat import OpenAICompatibleChatProvider
from .protocols import ASRProvider, ChatProvider
from .recorded import RecordedChatProvider
from .registry import ResolvedBackend


def build_chat_provider(resolved: ResolvedBackend) -> ChatProvider:
    cfg = resolved.config
    if resolved.kind == "openai_compat":
        return OpenAICompatibleChatProvider(
            backend=resolved.name,
            base_url=cfg.base_url or "",
            model_id=resolved.model_id,
            auth_token=cfg.bearer_token(),
            structured_output=cfg.structured_output,
            timeout_s=cfg.timeout_seconds,
            cold_start_seconds=cfg.cold_start_seconds,
            context_window=cfg.context_window,
            max_concurrency=cfg.max_concurrency,
            request_overrides=cfg.request_overrides,
        )
    if resolved.kind == "recorded":
        return RecordedChatProvider(
            backend=resolved.name, cassette_dir=cfg.cassette_dir or "", model_id=resolved.model_id
        )
    if resolved.kind == "anthropic":
        return AnthropicProvider(model_id=resolved.model_id)
    raise ConfigError(
        "kind_mismatch", f"backend {resolved.name!r} ({resolved.kind}) is not a chat backend"
    )


def build_asr_provider(
    resolved: ResolvedBackend, *, inproc_engine: InProcEngine | None = None
) -> ASRProvider:
    cfg = resolved.config
    if resolved.kind == "asr_http":
        return HTTPASRProvider(
            backend=resolved.name,
            base_url=cfg.base_url or "",
            model_id=resolved.model_id,
            auth_token=cfg.bearer_token(),
            timeout_s=cfg.timeout_seconds,
            cold_start_seconds=cfg.cold_start_seconds,
        )
    if resolved.kind == "asr_inproc":
        if inproc_engine is None:
            raise ConfigError(
                "invalid_config",
                f"backend {resolved.name!r} (asr_inproc) needs the service to pass its engine",
            )
        return InProcASRProvider(inproc_engine, backend=resolved.name)
    raise ConfigError(
        "kind_mismatch", f"backend {resolved.name!r} ({resolved.kind}) is not an ASR backend"
    )
