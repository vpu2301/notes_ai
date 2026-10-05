"""Step 2 — declared MIME is in the allow-list."""

from __future__ import annotations

from typing import Final

from .result import ValidationCode, ValidationResult, ok, reject

ALLOWED_MIME_TYPES: Final[frozenset[str]] = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/mpeg",
        "audio/mp3",
        "audio/ogg",
        "audio/webm",
        "audio/flac",
    }
)


def normalize_mime(mime_type: str) -> str:
    """Reduce a Content-Type to its bare type/subtype (``audio/webm;codecs=opus`` →
    ``audio/webm``); the codec is verified in step 6 from ffprobe, not the header."""
    return mime_type.split(";", 1)[0].strip().lower()


def validate_mime(mime_type: str) -> ValidationResult:
    """Return :func:`ok` if ``mime_type`` is supported."""
    if normalize_mime(mime_type) in ALLOWED_MIME_TYPES:
        return ok()
    return reject(
        ValidationCode.MIME_NOT_ALLOWED,
        f"declared MIME {mime_type!r} is not in the allow-list",
    )
