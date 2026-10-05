"""Placeholder for the opt-in vendor provider: the constructor raises ``provider_not_configured``; no SDK is imported."""

from __future__ import annotations

from .errors import ConfigError
from .protocols import JsonSchema, ProviderResult

_NOT_CONFIGURED = ConfigError(
    "provider_not_configured", "AnthropicProvider is NotConfigured until BE-S3"
)


class AnthropicProvider:
    """Satisfies ``ChatProvider`` structurally; every entry point raises."""

    backend = "anthropic"
    small_model = False

    def __init__(self, *, model_id: str) -> None:
        self.model_id = model_id
        raise _NOT_CONFIGURED

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> ProviderResult:
        raise _NOT_CONFIGURED

    async def probe(self) -> None:
        raise _NOT_CONFIGURED

    async def aclose(self) -> None:
        return None
