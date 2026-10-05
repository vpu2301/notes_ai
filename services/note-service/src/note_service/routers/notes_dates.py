"""A calendar file for a date the note names.

    GET /v1/notes/{id}/dates/{item_key}.ics

The ``DESCRIPTION`` is the quote, so the read goes through ``require_view`` and
the read-purpose rule. Nothing is written anywhere but the audit log.
"""

from __future__ import annotations

import json
import logging
from datetime import date, time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import ReadPurpose

from .. import audit_kinds, generation_metrics
from ..deps import get_state, requires
from ..domain import access, ics_writer
from ..domain import generation_repository as gen_repo
from ..domain import notes_repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


def _when(row: object) -> tuple[date, time | None]:
    """The resolved date (and time) of a key-date row."""
    raw = row["mentions"]  # type: ignore[index]
    mentions = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    if mentions:
        first = mentions[0]
        at = time.fromisoformat(first["time"]) if first.get("time") else None
        return date.fromisoformat(first["date"]), at
    due = row["due_date"]  # type: ignore[index]
    if due is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no date on this line")
    return due, None


@router.get("/{note_id}/dates/{item_key}.ics")
async def date_ics(
    note_id: UUID,
    item_key: str,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: ReadPurpose | None = None,
) -> Response:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        access.require_read_purpose(note, claims, purpose)
        rows = await gen_repo.items_for_note(conn, note_id=note_id, current_only=True)
    row = next((r for r in rows if r["item_key"] == item_key and r["kind"] == "date"), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such date")
    on, at = _when(row)
    body = ics_writer.event(
        uid=f"{item_key}@{note_id}",
        summary=str(row["text"]),
        description=str(row["quote"]),
        on=on,
        at=at,
    )
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_DATE_EXPORTED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={"item_key": item_key, "timed": at is not None},
        severity=Severity.INFO,
    )
    generation_metrics.dates_exported.add(1)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{item_key}.ics"'},
    )
