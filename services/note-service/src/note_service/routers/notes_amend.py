"""POST /notes/{id}/amend — sprint-08 day-4.

Amending a FINALIZED note appends a new ``note_versions`` row with
``is_amendment=true`` and moves the note to ``amended``. Further
amendments keep appending versions (status stays ``amended``).
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
from note_models import NoteAmendmentType, NoteContent, NoteStatus

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import access
from ..domain import notes_repository as repo
from ..domain.diff_engine import compute_diff, section_diff_summary
from ..domain.note_lifecycle import ConcurrentTransitionError, NoteStateMachine
from ._content_guard import ensure_valid_field_metadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

_sm = NoteStateMachine()


class AmendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amendment_type: NoteAmendmentType
    amendment_reason: str = Field(min_length=1, max_length=4000)
    content: NoteContent


class AmendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    version_number: int
    parent_version_id: UUID
    is_amendment: bool
    amendment_type: NoteAmendmentType
    note_status: str
    diff_summary: dict[str, list[str]]


@router.post(
    "/{note_id}/amend",
    response_model=AmendResponse,
    responses={
        422: {
            "description": "`amend_requires_finalized`, or sprint-13 field-metadata "
            "validation: `field_metadata_invalid` / `choice_value_unknown` "
            "(section-addressed problems in `problems[]`)."
        }
    },
)
async def amend_note(
    note_id: UUID,
    body: AmendRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> AmendResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # A private note the caller was not given is a 404 (0016).
        row = access.require_view(await repo.lock_note_for_update(conn, note_id=note_id), claims)
        if row.status not in (NoteStatus.FINALIZED, NoteStatus.AMENDED):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "amend_requires_finalized",
                    "current_status": row.status.value,
                },
            )

        current = await repo.fetch_version(conn, version_id=row.current_version_id)
        assert current is not None

        # Sprint-13: typed field metadata must be valid at every write.
        await ensure_valid_field_metadata(conn, content=body.content)

        diff = compute_diff(
            note_id=str(note_id),
            from_version_id=str(current.id),
            from_version_number=current.version_number,
            from_content=current.content,
            to_version_id="pending",
            to_version_number=current.version_number + 1,
            to_content=body.content,
        )

        new_id, new_n = await repo.append_version(
            conn,
            note_id=note_id,
            expected_version=row.current_version_number,
            new_content=body.content,
            created_by=claims.sub,
            diff_jsonb=section_diff_summary(diff),
            is_amendment=True,
            amendment_type=body.amendment_type,
            amendment_reason=body.amendment_reason,
            parent_version_id_override=current.id,
        )

        try:
            await _sm.mark_amended(conn, note_id=note_id, from_status=row.status)
        except ConcurrentTransitionError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_AMENDED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={
            "version_number": new_n,
            "amendment_type": body.amendment_type.value,
            "parent_version_id": str(current.id),
        },
        severity=Severity.INFO,
    )

    return AmendResponse(
        version_id=new_id,
        version_number=new_n,
        parent_version_id=current.id,
        is_amendment=True,
        amendment_type=body.amendment_type,
        note_status=NoteStatus.AMENDED.value,
        diff_summary=section_diff_summary(diff),
    )
