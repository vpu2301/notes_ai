"""Step 7 — SHA-256 of the upload; the persisted digest matches the stored bytes."""

from __future__ import annotations

import hashlib


def compute_hash(data: bytes) -> bytes:
    """Return the SHA-256 digest of ``data`` (32 raw bytes)."""
    return hashlib.sha256(data).digest()
