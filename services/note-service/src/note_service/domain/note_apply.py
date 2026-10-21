"""Putting the writer's note into the note somebody may be typing in (Sprint P3).

The writer's sections become ``gen:`` sections of a new version: every earlier ``gen:``
section goes (a re-run must not leave old topics beside the new ones), every other
section — the author's pad, the template's fields, a parked transcript — stays byte for
byte. The title is written only while the note still has its placeholder
(``title_source = 'default'``). A generation that changes nothing writes no version.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from note_models import NoteContent, NoteSection, NoteStatus

from . import note_markdown
from . import notes_repository as repo
from .conflicts import OptimisticLockMismatchError

logger = logging.getLogger(__name__)

# The head moving under us means somebody is typing right now.
MAX_WRITE_ATTEMPTS = 5
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0)
PAD_KEY = "user_notes"
TITLE_DEFAULT = "default"
TITLE_AI = "ai"


@dataclass(slots=True)
class Outcome:
    version_number: int | None = None
    written_sections: list[str] = field(default_factory=list)
    section_hashes: dict[str, str] = field(default_factory=dict)
    title_written: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.written_sections) or self.title_written


def section_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _table(items: list[note_markdown.Item]) -> list[str]:
    header = list((items[0].table_row or {}).get("header") or [])
    if not header:
        return [it.text for it in items]
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    for it in items:
        cells = list((it.table_row or {}).get("cells") or [])
        out.append("| " + " | ".join(cells) + " |")
    return out


def section_text(section: note_markdown.Section) -> str:
    """The section's items as Markdown, without the cites (they live on the items): a
    bullet is ``- text``, a paragraph its lines, table rows one pipe table."""
    lines: list[str] = []
    table: list[note_markdown.Item] = []

    def flush() -> None:
        if table:
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(_table(table))
            lines.append("")
            table.clear()

    for item in section.items:
        if item.table_row:
            table.append(item)
            continue
        flush()
        if item.kind == note_markdown.BULLET:
            lines.append(f"- {item.text}")
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(item.text)
            lines.append("")
    flush()
    return "\n".join(lines).strip()


def plan(
    content: NoteContent, parsed: note_markdown.ParsedNote, *, title_source: str | None
) -> tuple[NoteContent, Outcome]:
    """The next content: the writer's sections after the pad (else first), everything
    else as it was. Pure."""
    outcome = Outcome()
    kept = [
        s for s in content.sections if not s.section_key.startswith(note_markdown.SECTION_PREFIX)
    ]
    new: list[NoteSection] = []
    for section in parsed.sections:
        text = section_text(section)
        if not text:
            continue
        new.append(
            NoteSection(section_key=section.key, text=text, title=section.heading.strip()[:120])
        )
        outcome.written_sections.append(section.key)
        outcome.section_hashes[section.key] = section_hash(text)
    at = next((i + 1 for i, s in enumerate(kept) if s.section_key == PAD_KEY), 0)
    sections = kept[:at] + new + kept[at:]
    title = content.title
    # The title as the model wrote it; code trims nothing but the ends.
    wanted = parsed.title.strip()
    if wanted and title_source in (None, TITLE_DEFAULT) and wanted != content.title:
        title = wanted
        outcome.title_written = True
    old = [(s.section_key, s.text, s.title) for s in content.sections]
    if old == [(s.section_key, s.text, s.title) for s in sections] and not outcome.title_written:
        return content, Outcome()
    return content.model_copy(update={"sections": sections, "title": title}), outcome


async def apply(
    conn: Any,
    *,
    note_id: UUID,
    parsed: note_markdown.ParsedNote,
    requested_by: UUID,
    generation_id: UUID,
    prompt_version: str,
) -> Outcome:
    """Row lock, re-read the head, plan, append a version; on a lost race, re-read and
    re-plan. Returns an empty outcome when the note is gone or nothing changed."""
    for attempt in range(MAX_WRITE_ATTEMPTS):
        note = await repo.lock_note_for_update(conn, note_id=note_id)
        if note is None or note.status != NoteStatus.DRAFT:
            return Outcome()
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            return Outcome()
        source = await conn.fetchval("SELECT title_source FROM notes WHERE id = $1", note_id)
        content, outcome = plan(version.content, parsed, title_source=source)
        if not outcome.changed:
            return outcome
        try:
            _, number = await repo.append_version(
                conn,
                note_id=note_id,
                expected_version=note.current_version_number,
                new_content=content,
                created_by=requested_by,
                diff_jsonb={"source": "generation"},
                extra_metadata={
                    "source": "generation",
                    "generation_id": str(generation_id),
                    "prompt_version": prompt_version,
                    "step": "write",
                },
                title_source=TITLE_AI if outcome.title_written else None,
            )
        except OptimisticLockMismatchError:
            if attempt + 1 >= MAX_WRITE_ATTEMPTS:
                logger.warning("note_apply.write_gave_up", extra={"note_id": str(note_id)})
                return Outcome()
            await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
            continue
        outcome.version_number = number
        return outcome
    return Outcome()
