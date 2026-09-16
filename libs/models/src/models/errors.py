"""Error types shared by every provider and by the registry.

Two families, deliberately distinct:

* ``ConfigError`` — raised at *startup* (registry load / validate / build).
  A misconfigured environment refuses to start; it never fails a job at
  3 a.m. Carries a stable ``code`` so runbooks can name it.
* ``ProviderError`` — raised at *call time* by a provider. Carries a
  ``kind`` from a closed taxonomy so callers (job policies, circuit
  breakers in DEP-S4) branch on the kind, never on vendor status codes.
"""

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


# Kinds a caller may retry without changing the request. `rate_limited` is
# retryable by the *job policy* (DEP-S1), not by the provider itself — the
# provider retries only warming/unavailable/timeout (spec §D).
RETRYABLE_KINDS: frozenset[ErrorKind] = frozenset(
    {ErrorKind.WARMING, ErrorKind.RATE_LIMITED, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT}
)
PROVIDER_RETRY_KINDS: frozenset[ErrorKind] = frozenset(
    {ErrorKind.WARMING, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT}
)


_REDACT: list[str] = []


def register_secret(value: str | None) -> None:
    """Register a token so no ``ProviderError`` text can ever carry it.

    Providers call this with their bearer token at construction; vendor
    error bodies occasionally echo the ``Authorization`` header back.
    """
    if value and len(value) >= 8 and value not in _REDACT:
        _REDACT.append(value)


def redact(text: str) -> str:
    for secret in _REDACT:
        text = text.replace(secret, "***")
    return text


class ProviderError(RuntimeError):
    """Call-time provider failure.

    ``message`` must never contain prompt or transcript content — only
    status codes, backend names and the vendor's *error* text (which is
    truncated to keep accidental echoes short and redacted of every
    registered token).
    """

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
    """Raised by an ``ASRProvider`` when ``should_cancel`` answered True.

    Service-local cancellation errors subclass this so the worker can catch
    one type regardless of which backend served the job.
    """
