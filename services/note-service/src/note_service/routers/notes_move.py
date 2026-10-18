"""Between workspaces (W5).

    GET  /v1/notes/{id}/destinations   may I move or copy it, and what would refuse a move
    POST /v1/notes/{id}/move           same note, other workspace; media follows in a job
    POST /v1/notes/{id}/copy           a new note there from the current version, no recording

note-service cannot list another person's workspaces, so the client filters its own
switcher list (`GET /tenants`: `my_role`, `kind`, `status`) by `eligible_roles`; the
SQL function re-checks everything anyway. Both writes are idempotent by
``client_mutation_id`` for 10 minutes.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from notification_events import Category

from .. import audit_kinds
from ..collaboration_metrics import note_copies, note_moves, visibility_changed
from ..deps import get_state, requires
from ..domain import access, note_move
from ..domain import notes_repository as repo
from ..notifications import emit_note_event

router = APIRouter(prefix="/v1/notes", tags=["notes"])

_IDEMPOTENCY_S = 600

Blocker = Literal["media_shared", "generation_in_progress", "media_in_progress", "custom_template"]


class DestinationsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_move: bool
    can_copy: bool
    # Keep workspaces from `GET /tenants` with `status=active` and `my_role` in this list.
    eligible_roles: list[str]
    # Why a move would be refused right now; empty when nothing stands in the way.
    blockers: list[Blocker] = Field(default_factory=list)


class RelocateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    client_mutation_id: UUID


class MovedView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    workspace_id: UUID
    code: str
    visibility: str
    # rehoming: "Transcript on its way" until the media job finishes.
    media_state: str


class CopiedView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    workspace_id: UUID
    code: str


async def _audit(
    tenant_id: UUID, claims: Claims, kind: str, note_id: UUID, payload: dict[str, object]
) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=tenant_id,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload=payload,
        severity=Severity.INFO,
    )


async def _replayed(key: str) -> dict[str, object] | None:
    raw = await get_state().redis.get(key)
    return json.loads(raw) if raw else None


async def _remember(key: str, value: BaseModel) -> None:
    await get_state().redis.set(key, value.model_dump_json(), ex=_IDEMPOTENCY_S)


@router.get("/{note_id}/destinations", response_model=DestinationsView)
async def get_destinations(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> DestinationsView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        can_move = access.can_manage(note, claims)
        blockers = await note_move.blockers(conn, note=note) if can_move else []
    return DestinationsView(
        can_move=can_move,
        can_copy=True,  # anyone who sees it; the destination role is checked on POST
        eligible_roles=list(note_move.ELIGIBLE_ROLES),
        blockers=blockers,  # type: ignore[arg-type]
    )


@router.post("/{note_id}/move", response_model=MovedView)
async def move_note(
    note_id: UUID,
    body: RelocateRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> MovedView:
    state = get_state()
    replay_key = f"note:move:{claims.tid}:{body.client_mutation_id}"
    if (cached := await _replayed(replay_key)) is not None:
        return MovedView.model_validate(cached)

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
    try:
        moved = await note_move.move(
            app_pool=state.app_pool, note=note, actor=claims.sub, to_tenant_id=body.workspace_id
        )
    except note_move.RefusedError as exc:
        note_moves.add(1, {"result": "refused", "reason": exc.code})
        raise

    note_moves.add(1, {"result": "moved", "reason": "none"})
    media = moved.media_state != "ready"
    await _audit(
        moved.from_tenant_id,
        claims,
        audit_kinds.NOTE_MOVED,
        note_id,
        {"to_workspace_id": str(moved.to_tenant_id), "media": media},
    )
    await _audit(
        moved.to_tenant_id,
        claims,
        audit_kinds.NOTE_MOVED_IN,
        note_id,
        {"from_workspace_id": str(moved.from_tenant_id)},
    )
    if moved.visibility != note.visibility:
        visibility_changed.add(1, {"source": "move", "to": moved.visibility})
        await _audit(
            moved.to_tenant_id,
            claims,
            audit_kinds.NOTE_VISIBILITY_CHANGED,
            note_id,
            {
                "from": note.visibility,
                "to": moved.visibility,
                "reason": "move",
                "source": "default",
            },
        )
    if not access.is_author_team(note, claims.sub):
        # The author team hears in the workspace they know the note from.
        await emit_note_event(
            state.redis,
            category=Category.NOTE_MOVED,
            tenant_id=moved.from_tenant_id,
            note_id=note_id,
            note_code=note.code,
            actor_user_id=claims.sub,
            primary_author_id=note.primary_author_id,
            co_author_ids=tuple(note.co_author_ids),
            extra_payload={"to_workspace_id": str(moved.to_tenant_id)},
        )
    # Nobody is viewing it in the old workspace any more.
    await state.redis.delete(f"note:presence:{moved.from_tenant_id}:{note_id}")

    view = MovedView(
        note_id=note_id,
        workspace_id=moved.to_tenant_id,
        code=moved.code,
        visibility=moved.visibility,
        media_state=moved.media_state,
    )
    await _remember(replay_key, view)
    return view


@router.post("/{note_id}/copy", response_model=CopiedView, status_code=status.HTTP_201_CREATED)
async def copy_note(
    note_id: UUID,
    body: RelocateRequest,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> CopiedView:
    state = get_state()
    replay_key = f"note:copy:{claims.tid}:{body.client_mutation_id}"
    if (cached := await _replayed(replay_key)) is not None:
        return CopiedView.model_validate(cached)

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
    try:
        copy_id, code = await note_move.copy(
            app_pool=state.app_pool, note=note, actor=claims.sub, to_tenant_id=body.workspace_id
        )
    except note_move.RefusedError:
        note_copies.add(1, {"result": "refused"})
        raise
    note_copies.add(1, {"result": "copied"})

    await _audit(
        claims.tid,
        claims,
        audit_kinds.NOTE_COPIED_OUT,
        note_id,
        {"to_workspace_id": str(body.workspace_id), "copy_id": str(copy_id)},
    )
    await _audit(
        body.workspace_id,
        claims,
        audit_kinds.NOTE_CREATED,
        copy_id,
        {"code": code, "copied_from_note_id": str(note_id)},
    )
    view = CopiedView(note_id=copy_id, workspace_id=body.workspace_id, code=code)
    await _remember(replay_key, view)
    return view
