"""One way to cut a section into lines, shared by everything that does it.

Three places used to split section text independently: the action-item
projection (`action_items.parse_action_lines`), the author's scratchpad
(`meeting_doc.user_notes.split_lines`) and — from Sprint 35 — the
corrections routes that rewrite one line in place. When they disagree, a
line's `item_key` changes under it and the recipient's confirmation, the
evidence chip and the correction history all detach from the line they
belong to.

So the rules live here:

* a **line** is a non-blank line of the section, in order;
* its **marker** (bullet, ``1.``, ``a)``) is presentation and is kept
  separately, so a rewrite puts the same marker back;
* its **key** is ``item_key(normalise_text(body))`` over the body with the
  marker, the owner prefix and the trailing due phrase removed — the same
  hash the recipient loop has used since Sprint 20, so keys minted then
  still resolve now.

Everything here is pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

# The line GRAMMAR (owner prefix, due phrase, dates) stays in
# `action_items`, which the recipient loop has depended on since Sprint 20;
# this module owns the splitting, the marker and the key, and delegates the
# grammar. The dependency runs one way only — `action_items` must not
# import this module back.
from .action_items import item_key, normalise_text, parse_action_lines

MAX_OWNER: Final = 60
MAX_BODY: Final = 500

# `parse_action_lines` needs an anchor to resolve "Friday", but the KEY is
# taken from the body alone and never from the resolved date. A fixed
# anchor therefore keeps a line's key identical from one day to the next.
_KEY_ANCHOR: Final = date(2000, 1, 1)

# A leading bullet or number/letter marker. Captured rather than discarded:
# a line rewritten by a correction keeps the look the author chose.
_MARKER = re.compile(r"^(?P<marker>[\s>]*(?:[-–—•*·▪◦●○]+|\(?(?:\d{1,2}|[a-zA-Z])[.)])\s*)")


# Sprint 36 — "(internal)" at the start of a line keeps it inside the
# workspace: it is dropped from the client version, the shared page and
# the client PDF. Localised, because a German or Ukrainian author types
# the word they think in; the marker is stripped from every surface,
# external AND internal, so it never appears as literal text.
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
    """``("the price is our floor", True)`` for ``"(internal) the price…"``.

    The mark is taken off before the key is computed, so marking a line
    internal — or unmarking it — does NOT change its identity. Its
    evidence, its recipient responses and its correction history all
    survive the toggle, which is the only behaviour that makes the toggle
    safe to use.
    """
    match = _INTERNAL.match(content)
    return (content[match.end() :].strip(), True) if match else (content, False)


def mark_internal(raw: str, *, internal: bool) -> str:
    """Add or remove the ``(internal)`` mark on a line, keeping its marker
    and its words exactly as they were."""
    marker, content = strip_marker(raw)
    bare, _ = strip_internal(content)
    body = f"(internal) {bare}" if internal else bare
    return f"{marker}{body}" if marker else body


def key_of(content: str) -> str:
    """The key of a line, from its content with the marker already off.

    Owner and due are stripped first, so ``"Anna: send the deck — Friday"``
    and ``"Tom: send the deck — Monday"`` are the SAME line with a
    different owner and date. That is what lets a correction change either
    without detaching the line's evidence or its recipient responses.
    """
    parsed = parse_action_lines(content, anchor=_KEY_ANCHOR)
    return parsed[0].item_key if parsed else item_key(normalise_text(content))


@dataclass(frozen=True, slots=True)
class Parts:
    """A line's content, taken apart by the action-item grammar."""

    owner: str | None
    body: str
    due_text: str | None


def parts(content: str) -> Parts:
    """Split a line into who owns it, what it says, and when it is due.

    The body is what the key is taken from, so a caller that rewrites the
    owner or the due date and puts THIS body back is guaranteed to keep
    the key.
    """
    parsed = parse_action_lines(content, anchor=_KEY_ANCHOR)
    if not parsed:
        return Parts(owner=None, body=content.strip(), due_text=None)
    first = parsed[0]
    return Parts(owner=first.owner_label, body=first.text, due_text=first.due_text)


def find(text: str, key: str) -> Line | None:
    """The line with this key, or ``None``. First match wins: two lines
    with one key are the same statement written twice."""
    return next((line for line in split_section(text) if line.key == key), None)


def render_item(*, marker: str, owner: str | None, body: str, due_text: str | None) -> str:
    """``"- Anna: send the deck — Friday"`` — the render grammar the
    templates' synthesis prompt asks for, and the one
    ``parse_action_lines`` reads back.

    The body is passed through untouched: a correction changes who owns a
    line and when it is due, never what it says.
    """
    line = body.strip()
    if owner and owner.strip():
        line = f"{owner.strip()[:MAX_OWNER]}: {line}"
    if due_text and due_text.strip():
        line = f"{line} — {due_text.strip()}"
    return f"{marker}{line}" if marker else line


def replace_line(text: str, key: str, replacement: str | None) -> str | None:
    """Rewrite (or, with ``replacement=None``, remove) one line.

    Returns the new section text, or ``None`` when the key is not there —
    the caller turns that into a 404 rather than writing a version that
    changes nothing. Every other line, and the blank lines between them,
    are preserved byte for byte.
    """
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
        # Removing a line must not leave the hole it came out of: a blank
        # line at the top, or two in a row, would show up in the editor,
        # the PDF and the shared page.
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
    """Add a line at the end of the section, keeping one trailing newline
    at most. Used by restore: a line that comes back goes to the bottom
    rather than guessing where it was."""
    body = text.rstrip("\n")
    return f"{body}\n{line}" if body else line
