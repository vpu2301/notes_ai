"""The author's own ``user_notes`` lines: split and keyed.
The text is an INPUT, never polished. Pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .action_items import item_key, normalise_text

# The clients' cap on one PUT of line times, and the most lines the engine will anchor.
MAX_USER_LINES: Final = 500


@dataclass(frozen=True, slots=True)
class UserLine:
    """One line the author typed."""

    text: str
    """Verbatim, as typed — this is what goes back in the note."""
    line_key: str
    position: int
    offset_ms: int | None = None
    """First keystroke, relative to the recording's t=0; None when the
    client never reported one (an old client, or text pasted in later)."""


def line_key(text: str) -> str:
    """The stable identity of a typed line; one hashing rule with action items."""
    return item_key(normalise_text(text))


def split_lines(section_text: str, *, limit: int = MAX_USER_LINES) -> list[UserLine]:
    """The ``user_notes`` section as lines, in order: marker stripped for KEYING only,
    ``text`` exactly as typed; lines with one key collapse to the first."""
    out: list[UserLine] = []
    seen: set[str] = set()
    for raw in section_text.splitlines():
        text = raw.rstrip()
        if not text.strip():
            continue
        key = line_key(_strip_bullet(text))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(UserLine(text=text, line_key=key, position=len(out)))
        if len(out) == limit:
            break
    return out


_BULLET = re.compile(r"^[\s\-•*·▪◦]*(?:\d{1,2}[.)]\s*)?[\s\-•*·]*")


def _strip_bullet(text: str) -> str:
    return _BULLET.sub("", text, count=1)
