"""Putting a generated document into a note somebody may be typing in.

This is the module where the product's promise lives: **the engine never
overwrites what a person wrote.** Everything else is recoverable — a bad
summary is regenerated, a wrong owner is corrected — but text a person
typed and the machine replaced is gone, and they will not trust it again.

The rule is per SECTION, and it is decidable without guessing:

* the section is **empty** → write;
* its text is byte-identical to what the LAST generation put there
  (compared against `stats.section_hashes`) → nobody has touched it since,
  so write;
* the section holds a **transcript** and no generation has written it
  yet → that is the recording the from-transcript flow parked there as a
  placeholder, not a person's notes: write over it (the recording itself
  stays on the ASR job and in History);
* anything else → the author has been in there. Leave it exactly as it
  is, and keep this run's facts for that section as `suggested`, so
  Sprint 35's drawer can offer them without taking anything away.

A generation that changes no section writes no version at all: an
identical re-run after a crash must not fill History with noise.
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

# The head moving under us means somebody is typing right now. Retrying
# immediately would just lose the next race too.
MAX_WRITE_ATTEMPTS = 5
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0)

WRITTEN = "written"
SUGGESTED = "suggested"
# F2 — a fact kept only as evidence behind other lines (migration 0064).
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
    """The from-transcript flow drops the whole recording into the first
    prose section so a note is never blank. That text is the machine's,
    and the engine exists to replace it — but only while no generation
    has written the section: once one has, a dialogue there is something
    a person put back on purpose."""
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
    """Decide, purely, what this generation may write.

    Separated from the transaction so the decision can be tested on its
    own — it is the part that has to be right.
    """
    previous = previous_hashes or {}
    outcome = WriteOutcome()
    by_key = {s.section_key: s for s in content.sections}
    updated = dict(by_key)
    order = [s.section_key for s in content.sections]

    rendered_keys = {r.section_key for r in sections}
    # What the last run wrote and this run did not write again — the
    # topics came out differently, or nothing is written there any more
    # — goes, but only while it is still exactly what the last run
    # wrote. Edited, it is the author's. A generated section is removed;
    # a template section is emptied (its carried-over block, if any,
    # stays), so no stale heading survives beside the new blocks.
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
            # The note's content has no such section: a topic the
            # conversation had, or a template section an older note
            # lacks. The clients draw what the content has, so adding
            # one changes nothing the author wrote. An empty rendering
            # still adds nothing.
            if not rendered.text.strip():
                continue
            updated[rendered.section_key] = NoteSection(
                section_key=rendered.section_key, text=rendered.text, title=rendered.title
            )
            order.append(rendered.section_key)
            outcome.written_sections.append(rendered.section_key)
            outcome.section_hashes[rendered.section_key] = section_hash(rendered.text)
            continue
        # A "Still open from…" block belongs to the previous meeting, not
        # to the author and not to this run. It is preserved, and the rule
        # below applies to what follows it — otherwise the block would
        # make every series meeting's action section look author-written,
        # and the engine would never write a task into one again.
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
    """Write one step of a generation into the note.

    The caller holds a tenant connection; this takes the note's row lock,
    re-reads the head, plans against it and appends a version. On a lost
    race it re-reads and re-plans — the plan is cheap and the merge rule
    is what makes the retry correct rather than destructive.
    """
    import asyncio

    for attempt in range(MAX_WRITE_ATTEMPTS):
        note = await repo.lock_note_for_update(conn, note_id=note_id)
        if note is None or note.status != NoteStatus.DRAFT:
            # Cancelled or deleted while we were working. Nothing to do,
            # and nothing to complain about.
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
