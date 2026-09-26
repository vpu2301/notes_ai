"""Linking a new meeting to the one before it, and bringing its open
items forward (Sprint 36).

The one rule that matters is the visibility rule (ADR-0057):

    a previous note is used only when the AUTHOR OF THE NEW NOTE may
    view it.

RLS scopes every query to the tenant, and "my colleague's private 1:1"
is inside my tenant — so the tenant boundary is not the boundary here.
Every path through this module resolves the candidate note and puts it
through :func:`access.can_view` before reading a word of it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

import asyncpg

from auth import Claims
from note_models import NoteContent

from . import access, action_items, carry_over
from . import action_items_repository as items_repo
from . import meetings_repository as meetings
from . import notes_repository as repo
from .meeting_doc import series as series_rules

logger = logging.getLogger(__name__)

ACTIONS_SECTION = "action_items"


async def link_and_carry(
    conn: asyncpg.Connection,
    *,
    claims: Claims,
    note_id: UUID,
    started_at: datetime,
    title: str,
    calendar_context: dict,
    content: NoteContent,
    language: str = "en",
) -> NoteContent:
    """Work out the series, find the previous note, and fold its open
    items into this one's content.

    Returns the content to store — unchanged when there is no series, no
    readable previous note, or nothing still open. Never raises: a
    meeting must start whatever the history says.
    """
    key, source = series_rules.series_key(calendar_context, title=title)
    if key is None:
        return content
    try:
        await meetings.set_series(
            conn, note_id=note_id, series_key=key, series_source=source, previous_note_id=None
        )
        previous = await _previous_readable(
            conn, claims=claims, series_key=key, before=started_at, exclude=note_id
        )
        if previous is None:
            return content
        return await carry_into(
            conn,
            claims=claims,
            note_id=note_id,
            previous=previous,
            content=content,
            language=language,
        )
    except Exception:  # noqa: BLE001
        # Carry-over is a convenience on top of a meeting that is already
        # recording. It never costs the meeting.
        logger.warning("series.carry_over_failed", extra={"note_id": str(note_id)}, exc_info=True)
        return content


async def _previous_readable(
    conn: asyncpg.Connection,
    *,
    claims: Claims,
    series_key: str,
    before: datetime,
    exclude: UUID,
) -> repo.NoteRow | None:
    """The newest earlier note in the series that this author may view.

    Walks the candidates rather than taking the single newest: a
    colleague's private note in the middle of a shared series should not
    blank out the carry-over, it should be skipped.
    """
    for candidate in await meetings.previous_in_series(
        conn, series_key=series_key, before=before, exclude=exclude
    ):
        note = await repo.fetch_note(conn, note_id=candidate)
        if note is not None and access.can_view(note, claims):
            return note
    return None


async def carry_into(
    conn: asyncpg.Connection,
    *,
    claims: Claims,
    note_id: UUID,
    previous: repo.NoteRow,
    content: NoteContent,
    language: str = "en",
) -> NoteContent:
    """Insert the previous note's open items as a "Still open" block.

    The caller has already established that ``previous`` is readable.
    """
    if not access.can_view(previous, claims):  # defence in depth
        return content
    version = await repo.fetch_version(conn, version_id=previous.current_version_id)
    if version is None:
        return content
    rows = await action_items.ensure_items(conn, note=previous, version=version)
    items = carry_over.carried_from(rows)
    if not items:
        return content

    await meetings.put_carried_items(
        conn,
        tenant_id=claims.tid,
        note_id=note_id,
        from_note_id=previous.id,
        items=[(i.item_key, i.position) for i in items],
    )
    current = await meetings.fetch(conn, note_id=note_id)
    await meetings.set_series(
        conn,
        note_id=note_id,
        series_key=current.series_key if current else None,
        series_source=current.series_source if current else None,
        previous_note_id=previous.id,
    )
    block = carry_over.render_block(items, previous.updated_at.date(), language=language)
    return _with_block(content, block)


def _with_block(content: NoteContent, block: str) -> NoteContent:
    """Put the block at the TOP of the action-items section.

    Above the new meeting's own actions because that is the reading
    order: what was already owed, then what was just agreed.
    """
    if not block:
        return content
    sections = list(content.sections)
    for index, section in enumerate(sections):
        if section.section_key != ACTIONS_SECTION:
            continue
        body = (section.text or "").strip()
        sections[index] = section.model_copy(
            update={"text": f"{block}\n\n{body}" if body else block}
        )
        return content.model_copy(update={"sections": sections})
    return content


async def carried_view(
    conn: asyncpg.Connection, *, note_id: UUID, claims: Claims
) -> tuple[list[carry_over.CarriedItem], repo.NoteRow | None]:
    """The carried items with their current state, and where they came
    from — or nothing, when the source note is no longer readable."""
    rows = await meetings.carried_items(conn, note_id=note_id)
    if not rows:
        return [], None
    from_id = rows[0]["from_note_id"]
    previous = await repo.fetch_note(conn, note_id=from_id)
    if previous is None or not access.can_view(previous, claims):
        # Access can be taken away after the fact; the block stops
        # resolving rather than keeping a window open into the old note.
        return [], None
    version = await repo.fetch_version(conn, version_id=previous.current_version_id)
    source = (
        {
            i.item_key: i
            for i in carry_over.carried_from(
                await action_items.ensure_items(conn, note=previous, version=version), limit=100
            )
        }
        if version is not None
        else {}
    )
    states = {str(r["item_key"]): dict(r) for r in rows}
    items: list[carry_over.CarriedItem] = []
    for row in rows:
        key = str(row["item_key"])
        origin = source.get(key)
        items.append(
            carry_over.CarriedItem(
                item_key=key,
                text=origin.text if origin else "",
                owner_label=origin.owner_label if origin else None,
                due_text=origin.due_text if origin else None,
                position=int(row["position"]),
            )
        )
    return carry_over.apply_states(items, states), previous


async def item_rows_for(
    conn: asyncpg.Connection, *, note: repo.NoteRow
) -> list[items_repo.ItemRow]:
    version = await repo.fetch_version(conn, version_id=note.current_version_id)
    if version is None:
        return []
    return await action_items.ensure_items(conn, note=note, version=version)
