"""What is still open from last time: the previous instalment's open action items,
restated as check items under a "Still open from {date}" heading. A carried item
keeps the PREVIOUS note's `item_key` and is never copied into the new note's own
items. Visibility (ADR-0057) is the caller's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

from . import lines as line_rules

# More than this and the block stops being a reminder and becomes a
# backlog nobody reads. The engine's completion prompt has the same cap.
MAX_CARRIED: Final = 15

SECTION_HEADING: Final[dict[str, str]] = {
    "en": "Still open from {date}",
    "de": "Noch offen seit {date}",
    "uk": "Ще відкрито з {date}",
}

# States a carried item can be in.
OPEN: Final = "open"
DONE_MENTIONED: Final = "done_mentioned"
DONE_MARKED: Final = "done_marked"
DROPPED: Final = "dropped"
DONE_STATES: Final = frozenset({DONE_MENTIONED, DONE_MARKED})


@dataclass(frozen=True, slots=True)
class CarriedItem:
    """One open item brought forward from the previous meeting."""

    item_key: str
    """Its key in the PREVIOUS note."""
    text: str
    owner_label: str | None
    due_text: str | None
    position: int
    state: str = OPEN
    done_quote: str | None = None
    done_speaker: str | None = None

    @property
    def is_done(self) -> bool:
        return self.state in DONE_STATES


def heading(previous_date: date, *, language: str = "en") -> str:
    """ "Still open from 12 Sep" — the date of the meeting they come from,
    which is what an author recognises, not a note code."""
    template = SECTION_HEADING.get(language, SECTION_HEADING["en"])
    return template.format(date=previous_date.strftime("%-d %b"))


def render_block(items: list[CarriedItem], previous_date: date, *, language: str = "en") -> str:
    """The block as markdown-lite check items.

    Rendered as text, in a section, like everything else: the markdown
    parser already draws `- [ ]` as a check item, the PDF and the shared
    page inherit it, and History shows a tick as an ordinary edit.
    """
    if not items:
        return ""
    out = [f"## {heading(previous_date, language=language)}"]
    for item in items:
        if item.state == DROPPED:
            continue
        box = "x" if item.is_done else " "
        line = line_rules.render_item(
            marker="", owner=item.owner_label, body=item.text, due_text=item.due_text
        )
        out.append(f"- [{box}] {line}")
    return "\n".join(out) if len(out) > 1 else ""


def carried_from(items: list, *, limit: int = MAX_CARRIED) -> list[CarriedItem]:
    """The previous note's items worth carrying: the open ones, in order.

    ``items`` are ``action_items_repository.ItemRow``s. Anything already
    done or dropped in the previous meeting stays there — a carried block
    of finished work is noise, and the point of the block is the two
    things nobody has done yet.
    """
    out: list[CarriedItem] = []
    for row in items:
        if getattr(row, "status", OPEN) != "open":
            continue
        out.append(
            CarriedItem(
                item_key=row.item_key,
                text=row.text,
                owner_label=row.owner_label,
                due_text=row.due_text,
                position=len(out),
            )
        )
        if len(out) == limit:
            break
    return out


def apply_states(items: list[CarriedItem], states: dict[str, dict]) -> list[CarriedItem]:
    """Fold the stored `note_carried_items` rows onto the parsed items."""
    out: list[CarriedItem] = []
    for item in items:
        row = states.get(item.item_key)
        if row is None:
            out.append(item)
            continue
        out.append(
            CarriedItem(
                item_key=item.item_key,
                text=item.text,
                owner_label=item.owner_label,
                due_text=item.due_text,
                position=item.position,
                state=str(row.get("state") or OPEN),
                done_quote=row.get("done_quote"),
                done_speaker=row.get("done_speaker"),
            )
        )
    return out


def split_block(text: str) -> tuple[str, str]:
    """``(the "Still open" block, everything after it)``.

    The block lives at the top of the action-items section, which is also
    where the engine writes this meeting's own tasks. Without this split
    the writer would see a section with text in it, decide it belongs to
    the author, and never write an action into a series meeting again —
    the two features would quietly cancel each other out.

    The block is recognised by its heading, in any of the languages it is
    written in, so a note whose section merely starts with a "## " is not
    mistaken for one.
    """
    lines = text.splitlines()
    if not lines or not _is_block_heading(lines[0]):
        return "", text
    end = len(lines)
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if not stripped:
            continue
        # The block is check items and nothing else; the first line that
        # is not one ends it.
        if not stripped.startswith(("- [ ]", "- [x]", "- [X]")):
            end = index
            break
    block = "\n".join(lines[:end]).rstrip()
    rest = "\n".join(lines[end:]).lstrip("\n")
    return block, rest


def _is_block_heading(line: str) -> bool:
    head = line.strip()
    if not head.startswith("##"):
        return False
    head = head.lstrip("#").strip()
    return any(
        head.startswith(template.split("{")[0].strip()) for template in SECTION_HEADING.values()
    )
