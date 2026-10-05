"""Step 4 — file size ≤ MD_ASR_MAX_UPLOAD_MB (the API layer caps the body early)."""

from __future__ import annotations

from .result import ValidationCode, ValidationResult, ok, reject


def validate_size(size_bytes: int, *, max_mb: int) -> ValidationResult:
    # A zero-byte payload is a lost recording, not a format mismatch.
    if size_bytes == 0:
        return reject(
            ValidationCode.EMPTY_UPLOAD,
            "the uploaded file is empty (0 bytes)",
        )
    cap = max_mb * 1024 * 1024
    if size_bytes <= cap:
        return ok()
    return reject(
        ValidationCode.SIZE_EXCEEDED,
        f"upload is {size_bytes} bytes; cap is {cap} bytes ({max_mb} MB)",
    )
