"""GET /notes/{id}/versions[/{v}] — version history (M1·A1/A2).

Read-only. Mirrors ``notes_diff.py``: 404-first on the note, the same
non-author ``?purpose=`` enforcement ``get_note`` applies, and a
tenant-scoped connection so RLS does the isolation.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteAmendmentType, NoteContent, ReadPurpose

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import notes_repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


# ── Wire models ─────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteVersionSummary(_Strict):
    id: UUID
    version_number: int
    parent_version_id: UUID | None
    created_by: UUID
    created_at: str
    is_amendment: bool
    amendment_type: NoteAmendmentType | None
    amendment_reason: str | None


class NoteVersionDetail(NoteVersionSummary):
    content: NoteContent
    rendered_text: str


def _enforce_read_purpose(note: repo.NoteRow, claims: Claims, purpose: ReadPurpose | None) -> bool:
    """Returns ``is_author``; raises 422 when a non-author omits ``?purpose=``."""
    is_author = claims.sub == note.primary_author_id or claims.sub in note.co_author_ids
    if not is_author and purpose is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "https://errors.notes-ai/missing-read-purpose",
                "title": "Read purpose required",
                "detail": "Non-author reads must include ?purpose=<value>",
                "allowed": [p.value for p in ReadPurpose],
            },
        )
    return is_author


@router.get("/{note_id}/versions", response_model=list[NoteVersionSummary])
async def list_versions(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: Annotated[
        ReadPurpose | None, Query(description="Required for non-author reads.")
    ] = None,
) -> list[NoteVersionSummary]:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = await repo.fetch_note(conn, note_id=note_id)
        if note is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")
        _enforce_read_purpose(note, claims, purpose)
        summaries = await repo.list_version_summaries(conn, note_id=note_id)

    return [
        NoteVersionSummary(
            id=s.id,
            version_number=s.version_number,
            parent_version_id=s.parent_version_id,
            created_by=s.created_by,
            created_at=s.created_at.isoformat(),
            is_amendment=s.is_amendment,
            amendment_type=s.amendment_type,
            amendment_reason=s.amendment_reason,
        )
        for s in summaries
    ]


@router.get("/{note_id}/versions/{version_number}", response_model=NoteVersionDetail)
async def get_version(
    note_id: UUID,
    version_number: int,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: Annotated[
        ReadPurpose | None, Query(description="Required for non-author reads.")
    ] = None,
) -> NoteVersionDetail:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = await repo.fetch_note(conn, note_id=note_id)
        if note is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")
        is_author = _enforce_read_purpose(note, claims, purpose)
        version = await repo.fetch_version_by_number(
            conn, note_id=note_id, version_number=version_number
        )
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_VIEWED_FULL,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={
            "version_number": version_number,
            "purpose": purpose.value if purpose else "author",
            "is_author": is_author,
        },
        severity=Severity.INFO,
    )

    return NoteVersionDetail(
        id=version.id,
        version_number=version.version_number,
        parent_version_id=version.parent_version_id,
        created_by=version.created_by,
        created_at=version.created_at.isoformat(),
        is_amendment=version.is_amendment,
        amendment_type=version.amendment_type,
        amendment_reason=version.amendment_reason,
        content=version.content,
        rendered_text=version.rendered_text,
    )
