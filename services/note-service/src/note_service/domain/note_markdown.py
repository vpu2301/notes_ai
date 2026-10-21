"""The writer's Markdown, read into items (Sprint P1). Nothing here drops, splits,
reorders or edits a line: every line of the note is in exactly one item (or is a
heading, the title or the template line), and unknown syntax is a paragraph verbatim.

A code fence the model wraps the whole note in (```markdown … ```) is skipped as
structure. Timestamps at the end of a bullet (``[12:34]``, ``[12:34, 41:02]``, ``[1:02:03]``) cite
the transcript turn whose span contains that moment (±2 s); failing that the nearest
turn, flagged ``cite_nearest``; a time past the end of the recording cites nothing and
is counted (``bad_cites``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

CITE_TOLERANCE_MS: Final = 2_000
UNSTRUCTURED_HEADING: Final = "Note"

SECTION_PREFIX: Final = "gen:"
_SLUG: Final = re.compile(r"[^\w]+", re.UNICODE)

BULLET: Final = "bullet"
PARAGRAPH: Final = "paragraph"
VOTE: Final = "vote"
CLAIM: Final = "claim"
TABLE_ROW: Final = "table_row"

_HEADING: Final = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_BULLET: Final = re.compile(r"^\s*[-*•]\s+(.*)$")
_TEMPLATE_LINE: Final = re.compile(
    r"^\s*\*{0,2}Template\*{0,2}\s*:\s*\*{0,2}\s*`?([\w-]+)`?\*{0,2}\s*$", re.I
)
_TIME: Final = re.compile(r"(?:(\d{1,2}):)?(\d{1,3}):(\d{2})")
_CITES: Final = re.compile(
    r"\s*\[((?:\d{1,2}:)?\d{1,3}:\d{2}(?:\s*,\s*(?:\d{1,2}:)?\d{1,3}:\d{2})*)\]\s*[.]?\s*$"
)
_TABLE_ROW: Final = re.compile(r"^\s*\|.*\|\s*$")
# A code fence around the whole note (``` or ```markdown): structure, not a line of the note.
_FENCE: Final = re.compile(r"^\s*```[\w-]*\s*$")
_TABLE_RULE: Final = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
# Header words that make a table a vote or a claims table (en/de/uk).
_VOTE_WORDS: Final = frozenset(
    {"result", "ayes", "nays", "ergebnis", "ja", "nein", "результат", "за", "проти"}
)
_CLAIM_WORDS: Final = frozenset({"who", "claim", "wer", "behauptung", "хто", "твердження"})


@dataclass(slots=True)
class Item:
    text: str
    kind: str
    cites: list[int] = field(default_factory=list)
    """Turn numbers; empty when the line names no time or the time is out of range."""
    cite_nearest: bool = False
    table_row: dict[str, Any] | None = None
    times_ms: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Section:
    heading: str
    level: int
    key: str
    items: list[Item] = field(default_factory=list)


@dataclass(slots=True)
class ParsedNote:
    title: str
    template_name: str | None
    sections: list[Section]
    bad_cites: int = 0
    unstructured: bool = False

    @property
    def items(self) -> list[tuple[Section, Item]]:
        return [(s, i) for s in self.sections for i in s.items]


def section_key(heading: str, taken: set[str]) -> str:
    """``gen:<slug>`` of a heading, unique within ``taken`` by a numeric suffix (≤ 64 chars)."""
    slug = _SLUG.sub("-", heading.casefold()).strip("-")[:40].strip("-") or "section"
    key = f"{SECTION_PREFIX}{slug}"
    n = 2
    while key in taken:
        key = f"{SECTION_PREFIX}{slug}-{n}"
        n += 1
    return key


def time_to_ms(text: str) -> int | None:
    m = _TIME.fullmatch(text.strip())
    if m is None:
        return None
    hours = int(m.group(1)) if m.group(1) else 0
    return ((hours * 60 + int(m.group(2))) * 60 + int(m.group(3))) * 1000


def split_cites(text: str) -> tuple[str, list[int]]:
    """``("the bullet", [754000, 2462000])`` — the trailing bracket off, its times in ms."""
    m = _CITES.search(text)
    if m is None:
        return text.rstrip(), []
    times = [t for part in m.group(1).split(",") if (t := time_to_ms(part)) is not None]
    return text[: m.start()].rstrip(), times


def _turn_for(ms: int, turns: list[Any]) -> tuple[int | None, bool, bool]:
    """``(turn number, nearest, out of range)`` for one moment."""
    if not turns:
        return None, False, True
    end = max(int(t.end_ms) for t in turns)
    if ms < 0 or ms > end + CITE_TOLERANCE_MS:
        return None, False, True
    # Among the turns the moment falls in, the one with the most words: a one-word
    # micro-turn ("The") sharing the second with a long statement is not the evidence.
    inside = [t for t in turns if int(t.start_ms) <= ms <= int(t.end_ms)]
    if inside:
        return int(max(inside, key=lambda t: len(str(t.text))).number), False, False
    close = [
        t
        for t in turns
        if int(t.start_ms) - CITE_TOLERANCE_MS <= ms <= int(t.end_ms) + CITE_TOLERANCE_MS
    ]
    if close:
        return int(max(close, key=lambda t: len(str(t.text))).number), False, False
    nearest = min(turns, key=lambda t: min(abs(int(t.start_ms) - ms), abs(int(t.end_ms) - ms)))
    return int(nearest.number), True, False


def _item(text: str, kind: str, turns: list[Any], note: ParsedNote, **extra: Any) -> Item:
    body, times = split_cites(text)
    item = Item(text=body, kind=kind, times_ms=times, **extra)
    for ms in times:
        number, nearest, bad = _turn_for(ms, turns)
        if bad:
            note.bad_cites += 1
            continue
        if number is not None and number not in item.cites:
            item.cites.append(number)
        item.cite_nearest = item.cite_nearest or nearest
    return item


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _table_kind(header: list[str]) -> str:
    words = {w for cell in header for w in re.findall(r"\w+", cell.casefold())}
    if words & _VOTE_WORDS:
        return VOTE
    if words & _CLAIM_WORDS:
        return CLAIM
    return TABLE_ROW


def parse(markdown: str, turns: list[Any]) -> ParsedNote:
    """The note as the writer wrote it, read into sections and items."""
    lines = [ln for ln in markdown.splitlines() if not _FENCE.match(ln)]
    note = ParsedNote(title="", template_name=None, sections=[])
    taken: set[str] = set()
    current: Section | None = None
    parent_key = ""
    paragraph: list[str] = []
    table: list[str] = []
    i = 0

    def section_for(heading: str, level: int) -> Section:
        nonlocal parent_key
        if level <= 2 or current is None:
            key = section_key(heading, taken)
            parent_key = key if level <= 2 else parent_key
        else:
            key = section_key(f"{parent_key[len(SECTION_PREFIX) :]}-{heading}", taken)
        taken.add(key)
        sec = Section(heading=heading, level=min(level, 3), key=key)
        note.sections.append(sec)
        return sec

    def ensure_section() -> Section:
        nonlocal current
        if current is None:
            note.unstructured = True
            current = section_for(UNSTRUCTURED_HEADING, 2)
        return current

    def flush_paragraph() -> None:
        if paragraph:
            ensure_section().items.append(_item("\n".join(paragraph), PARAGRAPH, turns, note))
            paragraph.clear()

    def flush_table() -> None:
        if not table:
            return
        rows = [_cells(r) for r in table if not _TABLE_RULE.match(r)]
        if not rows:
            table.clear()
            return
        header, body = rows[0], rows[1:]
        kind = _table_kind(header)
        if not body:
            # A header alone: kept as a paragraph, verbatim.
            ensure_section().items.append(_item("\n".join(table), PARAGRAPH, turns, note))
            table.clear()
            return
        for cells in body:
            times = [t for c in cells if (t := time_to_ms(c.strip("[] "))) is not None]
            text = " | ".join(cells)
            item = _item(text, kind, turns, note, table_row={"header": header, "cells": cells})
            for ms in times:
                number, nearest, bad = _turn_for(ms, turns)
                if bad:
                    note.bad_cites += 1
                    continue
                if number is not None and number not in item.cites:
                    item.cites.append(number)
                item.cite_nearest = item.cite_nearest or nearest
                item.times_ms.append(ms)
            ensure_section().items.append(item)
        table.clear()

    # The title: the first non-empty line, with any heading marks off.
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        head = _HEADING.match(lines[i])
        note.title = head.group(2) if head else lines[i].strip().strip("*").strip()
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        tpl = _TEMPLATE_LINE.match(lines[i])
        if tpl:
            note.template_name = tpl.group(1).casefold()
            i += 1

    for raw in lines[i:]:
        line = raw.rstrip("\n")
        if not line.strip():
            flush_paragraph()
            flush_table()
            continue
        if _TABLE_ROW.match(line) or (table and _TABLE_RULE.match(line)):
            flush_paragraph()
            table.append(line)
            continue
        flush_table()
        head = _HEADING.match(line)
        if head:
            flush_paragraph()
            current = section_for(head.group(2), len(head.group(1)))
            continue
        tpl = _TEMPLATE_LINE.match(line)
        if tpl and note.template_name is None:
            note.template_name = tpl.group(1).casefold()
            continue
        bullet = _BULLET.match(line)
        if bullet:
            flush_paragraph()
            ensure_section().items.append(_item(bullet.group(1), BULLET, turns, note))
            continue
        paragraph.append(line)
    flush_paragraph()
    flush_table()
    return note


def word_count(text: str) -> int:
    return len(text.split())
