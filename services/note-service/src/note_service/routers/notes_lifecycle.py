"""Cancel route.

A note has one lifecycle transition left: ``draft → cancelled``. The
finalize / revert / amend lifecycle was retired (migration 0042): a note
is a living document that autosaves and can be shared at any time.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteStatus

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import access
from ..domain import notes_repository as repo
from ..domain.note_lifecycle import (
    ConcurrentTransitionError,
    IllegalTransitionError,
    NoteStateMachine,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

_sm = NoteStateMachine()


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


@router.post("/{note_id}/cancel", response_model=StatusResponse)
async def cancel_note(
    note_id: UUID,
    body: CancelRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> StatusResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # A private note the caller was not given is a 404 (0016).
        row = access.require_view(await repo.lock_note_for_update(conn, note_id=note_id), claims)
        try:
            await _sm.cancel(conn, note_id=note_id, from_status=row.status, reason=body.reason)
        except IllegalTransitionError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except ConcurrentTransitionError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_CANCELLED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={"reason": body.reason},
        severity=Severity.INFO,
    )
    return StatusResponse(id=note_id, status=NoteStatus.CANCELLED.value)
