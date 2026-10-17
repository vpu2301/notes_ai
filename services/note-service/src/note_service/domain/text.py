"""Plain-text hygiene for short user-typed text: recipient responses and note comments."""

from __future__ import annotations

import re
from typing import Final

_URL_RE: Final = re.compile(r"https?://|www\.", re.IGNORECASE)
_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_comment(
    value: str | None, *, max_len: int = 280, allow_links: bool = False
) -> str | None:
    """Strip control characters and surrounding blanks; ``None`` when nothing is left.

    Raises ``ValueError`` when the text is longer than ``max_len`` or, unless
    ``allow_links``, contains a link. The text is stored and shown as plain text.
    """
    if value is None:
        return None
    cleaned = _CONTROL_RE.sub("", value).strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ValueError(f"comment is longer than {max_len} characters")
    if not allow_links and _URL_RE.search(cleaned):
        raise ValueError("no_links_in_comment")
    return cleaned
