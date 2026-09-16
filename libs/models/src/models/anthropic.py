"""The only vendor-specific provider — opt-in, lands in BE-S3.

Kept as a named backend now so the registry, the Data page (decision 12)
and the ``no-vendor-import`` lint all know where the SDK will live. Until
BE-S3 the constructor raises ``ConfigError(provider_not_configured)``; the
``anthropic`` package is not imported anywhere in this repo.
"""

from __future__ import annotations

from .errors import ConfigError
from .protocols import JsonSchema, ProviderResult

_NOT_CONFIGURED = ConfigError(
    "provider_not_configured", "AnthropicProvider is NotConfigured until BE-S3"
)


class AnthropicProvider:
    """Satisfies ``ChatProvider`` structurally; every entry point raises."""

    backend = "anthropic"

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
