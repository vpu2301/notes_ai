"""Finalize / revert / cancel routes."""

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
from notification_events import Category

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import notes_repository as repo
from ..domain.finalize_validator import validate_finalize
from ..domain.note_lifecycle import (
    ConcurrentTransitionError,
    IllegalTransitionError,
    NoteStateMachine,
    NotPrimaryAuthorError,
    RevertWindowExceededError,
)
from ..notifications import emit_note_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

_sm = NoteStateMachine()


class FinalizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class FinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional optimistic-lock guard: when present it must equal the
    # note's current version number, else 409. Absent → fall back to the
    # status-based lock alone (backward compatible / no-body finalize).
    expected_version: int | None = Field(default=None, ge=1)
    # Links the originating dictation session to the note when not
    # already set at create time (Item 5).
    dictation_session_id: UUID | None = None


@router.post("/{note_id}/finalize", response_model=FinalizeResponse)
async def finalize_note(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
    body: FinalizeRequest | None = None,
) -> FinalizeResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.lock_note_for_update(conn, note_id=note_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")
        if row.status != NoteStatus.DRAFT:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error": "wrong_status_for_finalize",
                    "current_status": row.status.value,
                },
            )

        # Optional optimistic-lock guard (in addition to the status lock).
        if (
            body is not None
            and body.expected_version is not None
            and body.expected_version != row.current_version_number
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error": "optimistic_lock_mismatch",
                    "current_version": row.current_version_number,
                    "expected_version": body.expected_version,
                },
            )

        current = await repo.fetch_version(conn, version_id=row.current_version_id)
        assert current is not None

        # Load template to run finalize validation.
        template = await _fetch_template_definition(conn, template_id=current.content.template_id)
        problems = validate_finalize(
            content=current.content,
            template=template,
        )
        if problems:
            # Surface the per-section problems as first-class RFC-9457 extension
            # members (not stuffed into `detail`, which the global handler
            # str()-wraps) so the SPA can render field-level errors from JSON.
            exc = HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Note failed finalize validation.",
            )
            exc.problem_extras = {  # type: ignore[attr-defined]
                "code": "finalize_validation_failed",
                "problems": [p.as_dict() for p in problems],
            }
            raise exc

        # Session → note linkage (Item 5): backfill only when absent.
        source_session_id = row.source_session_id
        if (
            body is not None
            and body.dictation_session_id is not None
            and row.source_session_id is None
        ):
            await repo.set_source_session_id_if_absent(
                conn, note_id=note_id, session_id=body.dictation_session_id
            )
            source_session_id = body.dictation_session_id

        try:
            await _sm.finalize(conn, note_id=note_id)
        except ConcurrentTransitionError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error": "concurrent_transition",
                    "current_status": exc.observed_status.value if exc.observed_status else None,
                },
            ) from exc
        except IllegalTransitionError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    sections = current.content.sections
    low_confidence_count = sum(1 for s in sections if "[[" in (s.text or ""))
    field_types = {s.id: s.field_type.value for s in template.sections}

    # Sprint-13: ONE aggregated row per finalized note recording how many
    # typed fields still carried machine-extracted values when the author
    # finalized. A row per utterance would pollute the hash chain; this
    # answers "how much of this record did the machine propose" in one place.
    # Payload is counts + field types only — no values, no prose.
    extracted = sorted(
        {
            str(field_types.get(s.section_key, "unknown"))
            for s in sections
            if (s.field_specific_metadata or {}).get("source") == "extracted"
        }
    )
    if extracted:
        await state.audit_writer.write_event(
            tenant_id=claims.tid,
            kind=audit_kinds.FIELD_EXTRACTED,
            actor_sub=claims.sub,
            actor_role=(claims.roles[0] if claims.roles else None),
            target_kind="note",
            target_id=note_id,
            payload={
                "field_types": extracted,
                "section_count": sum(
                    1
                    for s in sections
                    if (s.field_specific_metadata or {}).get("source") == "extracted"
                ),
            },
            severity=Severity.INFO,
        )

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_FINALIZED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={"version_number": row.current_version_number},
        severity=Severity.INFO,
    )
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_COMPLETED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=str(note_id),
        payload={
            "version_number": row.current_version_number,
            "section_count": len(sections),
            "low_confidence_count": low_confidence_count,
            "source_session_id": str(source_session_id) if source_session_id else None,
        },
        severity=Severity.INFO,
    )

    # Sprint-12: tell the co-authors. After the audit writes and outside
    # the transaction — the note is already finalized, and a stalled
    # notification bus must not hold the response open (ADR-0029).
    await emit_note_event(
        state.redis,
        category=Category.NOTE_FINALIZED,
        tenant_id=claims.tid,
        note_id=note_id,
        note_code=row.code,
        actor_user_id=claims.sub,
        primary_author_id=row.primary_author_id,
        co_author_ids=tuple(row.co_author_ids),
    )
    return FinalizeResponse(id=note_id, status=NoteStatus.FINALIZED.value)


@router.post("/{note_id}/revert-to-draft", response_model=FinalizeResponse)
async def revert_to_draft(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> FinalizeResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.lock_note_for_update(conn, note_id=note_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")
        try:
            await _sm.revert_to_draft(conn, note_id=note_id, actor_user_id=claims.sub)
        except IllegalTransitionError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except NotPrimaryAuthorError as exc:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="only the primary author may revert",
            ) from exc
        except RevertWindowExceededError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="revert window of 1 hour has elapsed",
            ) from exc
        except ConcurrentTransitionError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_REVERTED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={},
        severity=Severity.INFO,
    )
    return FinalizeResponse(id=note_id, status=NoteStatus.DRAFT.value)


@router.post("/{note_id}/cancel", response_model=FinalizeResponse)
async def cancel_note(
    note_id: UUID,
    body: CancelRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> FinalizeResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.lock_note_for_update(conn, note_id=note_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")
        try:
            await _sm.cancel(
                conn,
                note_id=note_id,
                from_status=row.status,
                reason=body.reason,
            )
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
    return FinalizeResponse(id=note_id, status=NoteStatus.CANCELLED.value)


# ── Template fetch (lazy import to avoid circular) ──────────────────


async def _fetch_template_definition(conn, *, template_id: UUID):
    # note_service.domain.repository owns templates queries — we reuse
    # one of its helpers.
    import json

    from template_models import TemplateDefinition

    from ..domain.repository import get_template  # type: ignore

    row = await get_template(conn, template_id=template_id)
    if row is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="note references an unknown template",
        )
    raw = row["schema_jsonb"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    return TemplateDefinition.model_validate(raw)
