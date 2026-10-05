"""Putting a generated document into a note somebody may be typing in: the
engine never overwrites what a person wrote.

Per section: empty → write; byte-identical to the last generation's text
(`stats.section_hashes`) → write; a parked transcript no generation has written
yet → write over it; anything else is the author's, and this run's facts for it
become `suggested`. A generation that changes nothing writes no version.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from note_models import NoteContent, NoteSection, NoteStatus

from .. import carry_over
from .. import notes_repository as repo
from ..conflicts import OptimisticLockMismatchError
from . import roles
from .render import RenderedSection

logger = logging.getLogger(__name__)

# The head moving under us means somebody is typing right now.
MAX_WRITE_ATTEMPTS = 5
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0)

WRITTEN = "written"
SUGGESTED = "suggested"
# A fact kept only as evidence behind other lines.
EVIDENCE = "evidence"


def section_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class WriteOutcome:
    version_number: int | None = None
    written_sections: list[str] = field(default_factory=list)
    suggested_sections: list[str] = field(default_factory=list)
    section_hashes: dict[str, str] = field(default_factory=dict)
    """Generated sections from the last run that this run did not write
    again and nobody had edited: gone, so a re-run does not leave the
    old topics beside the new ones."""
    removed_sections: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.written_sections or self.removed_sections)


def _is_parked_transcript(section_key: str, existing: str, previous: dict[str, str]) -> bool:
    """The recording the from-transcript flow parked in the first prose section:
    the machine's, writable, but only while no generation has written the section."""
    if section_key in previous:
        return False
    from ..client_view import looks_like_transcript  # one rule for "is a transcript"

    return looks_like_transcript(existing)


def plan(
    content: NoteContent,
    sections: list[RenderedSection],
    *,
    previous_hashes: dict[str, str] | None = None,
) -> tuple[NoteContent, WriteOutcome]:
    """Decide, purely, what this generation may write."""
    previous = previous_hashes or {}
    outcome = WriteOutcome()
    by_key = {s.section_key: s for s in content.sections}
    updated = dict(by_key)
    order = [s.section_key for s in content.sections]

    rendered_keys = {r.section_key for r in sections}
    # Sections the last run wrote and this run did not go, only while still exactly
    # the last run's text: generated sections removed, template sections emptied
    # (the carried-over block stays).
    for key in list(order):
        current = by_key[key]
        if key in rendered_keys or key not in previous:
            continue
        carried_block, existing = carry_over.split_block(current.text or "")
        if section_hash(existing) != previous[key]:
            continue
        if roles.is_generated(key):
            order.remove(key)
            del updated[key]
        else:
            updated[key] = current.model_copy(update={"text": carried_block})
        outcome.removed_sections.append(key)

    for rendered in sections:
        current = by_key.get(rendered.section_key)
        if current is None:
            # No such section in the content: adding one changes nothing the author wrote.
            if not rendered.text.strip():
                continue
            updated[rendered.section_key] = NoteSection(
                section_key=rendered.section_key, text=rendered.text, title=rendered.title
            )
            order.append(rendered.section_key)
            outcome.written_sections.append(rendered.section_key)
            outcome.section_hashes[rendered.section_key] = section_hash(rendered.text)
            continue
        # The "Still open from…" block is neither the author's nor this run's: preserved,
        # and the rule applies to what follows it.
        carried_block, existing = carry_over.split_block(current.text or "")
        mine = (
            not existing.strip()
            or section_hash(existing) == previous.get(rendered.section_key)
            or _is_parked_transcript(rendered.section_key, existing, previous)
        )
        if not mine:
            outcome.suggested_sections.append(rendered.section_key)
            continue
        if existing == rendered.text:
            # Already exactly this. Not a change, so not a version.
            outcome.section_hashes[rendered.section_key] = section_hash(rendered.text)
            continue
        written = f"{carried_block}\n\n{rendered.text}" if carried_block else rendered.text
        updated[rendered.section_key] = current.model_copy(
            update={"text": written, "title": rendered.title or current.title}
        )
        outcome.written_sections.append(rendered.section_key)
        outcome.section_hashes[rendered.section_key] = section_hash(rendered.text)

    if not outcome.changed:
        return content, outcome
    return content.model_copy(update={"sections": [updated[key] for key in order]}), outcome


async def apply(
    conn: Any,
    *,
    note_id: UUID,
    sections: list[RenderedSection],
    requested_by: UUID,
    generation_id: UUID,
    prompt_version: str,
    step: str,
    previous_hashes: dict[str, str] | None = None,
) -> WriteOutcome:
    """Write one step of a generation into the note: row lock, re-read the head,
    plan, append a version; on a lost race, re-read and re-plan."""
    import asyncio

    for attempt in range(MAX_WRITE_ATTEMPTS):
        note = await repo.lock_note_for_update(conn, note_id=note_id)
        if note is None or note.status != NoteStatus.DRAFT:
            # Cancelled or deleted while we were working.
            return WriteOutcome()
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            return WriteOutcome()

        content, outcome = plan(version.content, sections, previous_hashes=previous_hashes)
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
                    "step": step,
                },
            )
        except OptimisticLockMismatchError:
            if attempt + 1 >= MAX_WRITE_ATTEMPTS:
                logger.warning(
                    "meeting_doc.write_gave_up",
                    extra={"note_id": str(note_id), "step": step},
                )
                return WriteOutcome()
            await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
            continue
        outcome.version_number = number
        return outcome
    return WriteOutcome()
