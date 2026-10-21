"""Instructions for one note — "Write this note differently" (Sprint N4).

    GET    /v1/notes/{note_id}/instructions   an editor: the note's text
    PUT    /v1/notes/{note_id}/instructions   an editor: save (empty text = remove)
    DELETE /v1/notes/{note_id}/instructions   an editor: back to the workspace's

The text extends its parents — the workspace text, then the text of the note's meeting
type — and records the versions it was saved against. Nothing compiles it (Sprint R0):
the writer reads it as written. The client rewrites the note with the existing
``POST …/generation``. The text is content: never logged, audited or measured.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteStatus

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import access
from ..domain import meetings_repository as meetings
from ..domain import note_instructions as ni
from ..domain import note_instructions_repository as repo
from ..domain import notes_repository as notes_repo
from . import ai_instructions as workspace_routes
from .ai_instructions import InstructionsRequest, InstructionsView, ScopeRef

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["ai"])


async def note_family(conn: Any, note_id: UUID) -> str | None:
    """The meeting family the note is written as: its meeting's type; None for `auto`
    (no type → the workspace text alone)."""
    meeting = await meetings.fetch(conn, note_id=note_id)
    family = meeting.meeting_type if meeting is not None else None
    return family if family in repo.TYPE_SCOPES else None


async def _editable(conn: Any, note_id: UUID, claims: Claims, *, writing: bool) -> Any:
    note = access.require_edit(await notes_repo.fetch_note(conn, note_id=note_id), claims)
    if writing and note.status != NoteStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "note_cancelled", "detail": "the note is no longer a draft"},
        )
    if writing and note.source_asr_job_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "no_transcript", "detail": "this note was not made from a recording"},
        )
    return note


async def _parents(conn: Any, tenant_id: UUID, note_id: UUID) -> list[repo.Row]:
    """The texts this note's text extends, parent first: the workspace's, the type's."""
    family = await note_family(conn, note_id)
    scopes = (repo.WORKSPACE, family) if family else (repo.WORKSPACE,)
    rows = await repo.fetch_many(conn, tenant_id=tenant_id, scopes=scopes)
    return [rows[s] for s in scopes if s in rows]


def _view(claims: Claims, row: repo.NoteRow | None, parents: list[repo.Row]) -> InstructionsView:
    nearest = parents[-1] if parents else None
    return InstructionsView(
        scope=repo.NOTE,
        version=1 if row is not None else 0,
        text=row.text if row is not None else "",
        profile=dict(ni.STORED_PROFILE),
        profile_hash=ni.STORED_PROFILE_HASH,
        compile_status=ni.STORED_COMPILE_STATUS,
        compile_error_kind=None,
        understood=[],
        guidance=[],
        not_applied=[],
        can_edit=True,
        max_chars=settings.note_instructions_max_chars,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
        base_versions=dict(row.base_versions) if row is not None else {},
        extends=ScopeRef(scope=nearest.scope, version=nearest.version) if nearest else None,
    )


async def _audit(claims: Claims, note_id: UUID, kind: str, payload: dict[str, object]) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload=payload,  # counts and scope names only: never the text
        severity=Severity.INFO,
    )


@router.get("/{note_id}/instructions", response_model=InstructionsView)
async def get_note_instructions(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> InstructionsView:
    workspace_routes._enabled()
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        await _editable(conn, note_id, claims, writing=False)
        row = await repo.fetch_note(conn, note_id=note_id)
        parents = await _parents(conn, claims.tid, note_id)
    return _view(claims, row, parents)


async def _clear(claims: Claims, note_id: UUID) -> None:
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        await _editable(conn, note_id, claims, writing=False)
        removed = await repo.delete_note(conn, note_id=note_id)
    if removed:
        await _audit(claims, note_id, audit_kinds.NOTE_INSTRUCTIONS_CLEARED, {})


@router.put("/{note_id}/instructions", response_model=InstructionsView)
async def put_note_instructions(
    note_id: UUID,
    body: InstructionsRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> InstructionsView:
    """Save this note's text. Empty text removes it. The client then rewrites the note
    (``POST …/generation``)."""
    workspace_routes._enabled()
    text = workspace_routes._sanitised(body.text)
    state = get_state()
    if not text:
        await _clear(claims, note_id)
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            parents = await _parents(conn, claims.tid, note_id)
        return _view(claims, None, parents)
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        await _editable(conn, note_id, claims, writing=True)
        existing = await repo.fetch_note(conn, note_id=note_id)
        parents = await _parents(conn, claims.tid, note_id)
        row = await repo.upsert_note(
            conn,
            tenant_id=claims.tid,
            note_id=note_id,
            text=text,
            profile=dict(ni.STORED_PROFILE),
            profile_hash=ni.STORED_PROFILE_HASH,
            compile_status=ni.STORED_COMPILE_STATUS,
            compile_error_kind=None,
            compiler_version=ni.STORED_COMPILER_VERSION,
            base_versions={p.scope: p.version for p in parents},
            updated_by=claims.sub,
        )
    await _audit(
        claims,
        note_id,
        audit_kinds.NOTE_INSTRUCTIONS_CHANGED,
        {"chars": len(text), "base_scopes": [p.scope for p in parents]},
    )
    if existing is None:
        response.status_code = status.HTTP_201_CREATED
    return _view(claims, row, parents)


@router.delete("/{note_id}/instructions", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note_instructions(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> Response:
    workspace_routes._enabled()
    await _clear(claims, note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
