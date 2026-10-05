"""``ConfigError`` (startup, stable ``code``) and ``ProviderError`` (call time, closed ``kind`` taxonomy)."""

from __future__ import annotations

from enum import StrEnum


class ConfigError(RuntimeError):
    """Startup-time configuration failure. ``code`` is stable and log-safe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ErrorKind(StrEnum):
    WARMING = "warming"  # backend is scaling from zero; retry within cold_start_seconds
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"  # connection refused / 5xx / model not served
    TIMEOUT = "timeout"
    CONTEXT_EXCEEDED = "context_exceeded"  # prompt too long OR output truncated (finish=length)
    SCHEMA_INVALID = "schema_invalid"  # model returned something that is not the requested JSON
    AUTH = "auth"
    UNKNOWN = "unknown"


# `rate_limited` is retryable by the job policy, not by the provider (which retries only warming/unavailable/timeout).
RETRYABLE_KINDS: frozenset[ErrorKind] = frozenset(
    {ErrorKind.WARMING, ErrorKind.RATE_LIMITED, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT}
)
PROVIDER_RETRY_KINDS: frozenset[ErrorKind] = frozenset(
    {ErrorKind.WARMING, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT}
)


_REDACT: list[str] = []


def register_secret(value: str | None) -> None:
    """Register a token so no ``ProviderError`` text can carry it (vendor error bodies echo the header)."""
    if value and len(value) >= 8 and value not in _REDACT:
        _REDACT.append(value)


def redact(text: str) -> str:
    for secret in _REDACT:
        text = text.replace(secret, "***")
    return text


class ProviderError(RuntimeError):
    """Call-time provider failure; ``message`` never carries prompt/transcript content and is redacted of tokens."""

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        backend: str,
        status: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        message = redact(message)
        super().__init__(f"{backend}: {kind}: {message}")
        self.kind = kind
        self.message = message
        self.backend = backend
        self.status = status
        self.retry_after_s = retry_after_s

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS


class TranscriptionCancelledError(Exception):
    """Raised by an ``ASRProvider`` when ``should_cancel`` answered True; service-local variants subclass it."""
