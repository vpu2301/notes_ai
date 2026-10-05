"""RFC 8785 JCS via the ``rfc8785`` library, so writer and verifier hash the same logical event identically.

Callers pre-convert UUID/datetime/bytes; JCS rejects NaN and Infinity.
"""

from __future__ import annotations

from typing import Any

import rfc8785

from .exceptions import CanonicalizationError


def canonicalize(value: Any) -> bytes:
    """RFC 8785 canonical bytes of ``value``; CanonicalizationError on a non-serialisable type or NaN/Infinity."""
    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(f"JCS canonicalization failed: {exc}") from exc


def canonicalize_str(value: Any) -> str:
    """Convenience: the canonical bytes as a UTF-8 string."""
    return canonicalize(value).decode("utf-8")
