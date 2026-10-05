"""Shared types for the validation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ValidationCode(StrEnum):
    """Stable rejection codes, also the RFC 9457 ``type`` URI suffix (see docs/api/error-codes.md)."""

    # ── Identity / authorization ─────────────────────────────────────
    SCOPE_MISSING = "scope_missing"

    # ── File shape: is this an audio file at all? ────────────────────
    EMPTY_UPLOAD = "empty_upload"
    MIME_NOT_ALLOWED = "mime_not_allowed"
    MIME_MISMATCH = "mime_mismatch"
    SIZE_EXCEEDED = "size_exceeded"
    UNPROBEABLE = "unprobeable"

    # ── Audio shape: is it audio we can transcribe? ──────────────────
    DURATION_EXCEEDED = "duration_exceeded"
    DURATION_TOO_SHORT = "duration_too_short"
    CODEC_NOT_ALLOWED = "codec_not_allowed"
    SAMPLE_RATE_TOO_LOW = "sample_rate_too_low"
    CHANNELS_EXCEEDED = "channels_exceeded"

    # ── Budget: may this tenant spend more transcription now? ────────
    QUOTA_EXCEEDED = "quota_exceeded"
    CONCURRENCY_EXCEEDED = "concurrency_exceeded"


@dataclass(slots=True)
class ValidationResult:
    """One step's outcome."""

    ok: bool
    code: str = ""
    detail: str = ""


@dataclass(slots=True)
class UploadFacts:
    """Facts about the upload, accumulated by the pipeline."""

    mime_type: str = ""
    size_bytes: int = 0
    duration_ms: int = 0
    sample_rate_hz: int = 0
    channels: int = 0
    codec: str = ""
    sha256: bytes = b""
    bytes_buffer: bytes = field(default=b"", repr=False)


def ok() -> ValidationResult:
    return ValidationResult(ok=True)


def reject(code: ValidationCode | str, detail: str = "") -> ValidationResult:
    """Build a failing result with a stable code."""
    return ValidationResult(ok=False, code=str(code), detail=detail)
