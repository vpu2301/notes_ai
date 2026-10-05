"""The one way to cut a section into lines (action items, scratchpad, corrections
all share it, or a line's `item_key` changes under it).

A line is a non-blank line; its marker is kept separately; its key is
``item_key(normalise_text(body))`` with marker, owner prefix and due phrase
removed, the same hash the recipient loop has always used. Pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

# The line GRAMMAR stays in `action_items`; this module owns splitting, marker and
# key. The dependency runs one way only: `action_items` must not import this module.
from .action_items import item_key, normalise_text, parse_action_lines

MAX_OWNER: Final = 60
MAX_BODY: Final = 500

# A fixed anchor: the KEY comes from the body alone, never the resolved date.
_KEY_ANCHOR: Final = date(2000, 1, 1)

# A leading bullet or number/letter marker, captured so a rewrite keeps it.
_MARKER = re.compile(r"^(?P<marker>[\s>]*(?:[-–—•*·▪◦●○]+|\(?(?:\d{1,2}|[a-zA-Z])[.)])\s*)")


# "(internal)" at the start of a line keeps it out of every external surface;
# localised, and stripped from every surface so it never appears as literal text.
_INTERNAL_WORDS: Final = ("internal", "intern", "внутрішнє", "внутрішній")
_INTERNAL = re.compile(
    r"^\s*[\(\[]\s*(?:" + "|".join(_INTERNAL_WORDS) + r")\s*[\)\]]\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Line:
    """One line of a section."""

    index: int
    """Position among the non-blank lines, 0-based."""
    raw: str
    """Exactly as stored, marker and all. What goes back if nothing changes."""
    marker: str
    """The leading bullet/number, or "" — presentation only."""
    content: str
    """The line without its marker OR its internal mark: what the grammar
    is parsed from, and what a reader sees."""
    key: str
    """Identity. Stable across reordering, a section move, an owner or
    due-date edit, and marking the line internal; it changes when the body
    changes, which is the point."""
    internal: bool = False
    """The author marked this line as not for the client."""


def strip_marker(text: str) -> tuple[str, str]:
    """``("- ", "Anna: send the deck")`` — the marker and the rest."""
    match = _MARKER.match(text)
    if match is None:
        return "", text.strip()
    return match.group("marker"), text[match.end() :].strip()


def split_section(text: str) -> list[Line]:
    """The section's lines, in order. Blank lines are structure, not lines."""
    out: list[Line] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        marker, content = strip_marker(raw)
        if not content:
            # A bare "-" or "2." is a leftover, not a statement.
            continue
        content, internal = strip_internal(content)
        if not content:
            continue
        out.append(
            Line(
                index=len(out),
                raw=raw.rstrip(),
                marker=marker,
                content=content,
                key=key_of(content),
                internal=internal,
            )
        )
    return out


def strip_internal(content: str) -> tuple[str, bool]:
    """``("the price is our floor", True)`` for ``"(internal) the price…"``. The mark
    comes off before the key is computed, so toggling it does NOT change identity."""
    match = _INTERNAL.match(content)
    return (content[match.end() :].strip(), True) if match else (content, False)


def mark_internal(raw: str, *, internal: bool) -> str:
    """Add or remove the ``(internal)`` mark, keeping marker and words exactly."""
    marker, content = strip_marker(raw)
    bare, _ = strip_internal(content)
    body = f"(internal) {bare}" if internal else bare
    return f"{marker}{body}" if marker else body


def key_of(content: str) -> str:
    """The key of a line (marker already off). Owner and due are stripped first, so
    a correction to either keeps the key."""
    parsed = parse_action_lines(content, anchor=_KEY_ANCHOR)
    return parsed[0].item_key if parsed else item_key(normalise_text(content))


@dataclass(frozen=True, slots=True)
class Parts:
    """A line's content, taken apart by the action-item grammar."""

    owner: str | None
    body: str
    due_text: str | None


def parts(content: str) -> Parts:
    """Split a line into owner, body and due; putting THIS body back keeps the key."""
    parsed = parse_action_lines(content, anchor=_KEY_ANCHOR)
    if not parsed:
        return Parts(owner=None, body=content.strip(), due_text=None)
    first = parsed[0]
    return Parts(owner=first.owner_label, body=first.text, due_text=first.due_text)


def find(text: str, key: str) -> Line | None:
    """The line with this key, or ``None``; first match wins."""
    return next((line for line in split_section(text) if line.key == key), None)


def render_item(*, marker: str, owner: str | None, body: str, due_text: str | None) -> str:
    """``"- Anna: send the deck — Friday"``, the grammar ``parse_action_lines`` reads back; the body is untouched."""
    line = body.strip()
    if owner and owner.strip():
        line = f"{owner.strip()[:MAX_OWNER]}: {line}"
    if due_text and due_text.strip():
        line = f"{line} — {due_text.strip()}"
    return f"{marker}{line}" if marker else line


def replace_line(text: str, key: str, replacement: str | None) -> str | None:
    """Rewrite (or, with ``replacement=None``, remove) one line. ``None`` when the key
    is not there; every other line is preserved byte for byte."""
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        if not raw.strip():
            continue
        marker, content = strip_marker(raw)
        if not content or key_of(content) != key:
            continue
        if replacement is not None:
            lines[i] = replacement
            return "\n".join(lines)
        del lines[i]
        # Removing a line must not leave a hole (a leading or doubled blank line).
        return _tidy(lines)
    return None


def _tidy(lines: list[str]) -> str:
    out: list[str] = []
    for raw in lines:
        blank = not raw.strip()
        if blank and (not out or not out[-1].strip()):
            continue  # leading blank, or a second one in a row
        out.append(raw)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def append_line(text: str, line: str) -> str:
    """Add a line at the end of the section, keeping one trailing newline at most."""
    body = text.rstrip("\n")
    return f"{body}\n{line}" if body else line
