"""Spaces — personal folders for notes, the same on every device (0021).

    GET    /v1/spaces                   the caller's spaces, each with the notes filed in it
    POST   /v1/spaces                   create → space
    PUT    /v1/spaces/{id}              rename → space
    DELETE /v1/spaces/{id}              delete (its notes become unfiled)
    PUT    /v1/notes/{note_id}/space    file the note in a space ({space_id: null} unfiles)

Spaces are personal: every route filters on the caller's ``sub`` on top
of tenant RLS. Filing does not touch the note itself — it is the
caller's own organisation of the notes they can already see, so it
needs only ``note.read``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import spaces_repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["spaces"])

_reader = requires("note.read", "note")


# ── Wire models ─────────────────────────────────────────────────────


class SpaceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    created_at: str
    # The notes the caller filed here, newest filing last.
    note_ids: list[UUID]


class SpacesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spaces: list[SpaceView]


class SpaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _trim(cls, name: str) -> str:
        trimmed = " ".join(name.split())
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed


class FileNoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None unfiles the note.
    space_id: UUID | None


def _iso(value: datetime) -> str:
    return value.isoformat()


def _view(row: repo.SpaceRow, note_ids: list[UUID]) -> SpaceView:
    return SpaceView(id=row.id, name=row.name, created_at=_iso(row.created_at), note_ids=note_ids)


async def _audit(claims: Claims, kind: str, space_id: UUID) -> None:
    state = get_state()
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="space",
        target_id=space_id,
        payload={"space_id": str(space_id)},
        severity=Severity.INFO,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/spaces", response_model=SpacesResponse)
async def list_spaces(claims: Annotated[Claims, Depends(_reader)]) -> SpacesResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        rows = await repo.list_spaces(conn, user_sub=claims.sub)
        items = await repo.list_items(conn, user_sub=claims.sub)
    by_space: dict[UUID, list[UUID]] = {row.id: [] for row in rows}
    for note_id, space_id in items.items():
        by_space.setdefault(space_id, []).append(note_id)
    return SpacesResponse(spaces=[_view(row, by_space.get(row.id, [])) for row in rows])


@router.post("/spaces", response_model=SpaceView, status_code=status.HTTP_201_CREATED)
async def create_space(body: SpaceBody, claims: Annotated[Claims, Depends(_reader)]) -> SpaceView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.create_space(
            conn, tenant_id=claims.tid, user_sub=claims.sub, name=body.name
        )
    await _audit(claims, audit_kinds.SPACE_CREATED, row.id)
    return _view(row, [])


@router.put("/spaces/{space_id}", response_model=SpaceView)
async def rename_space(
    space_id: UUID, body: SpaceBody, claims: Annotated[Claims, Depends(_reader)]
) -> SpaceView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.rename_space(conn, user_sub=claims.sub, space_id=space_id, name=body.name)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="space not found")
        items = await repo.list_items(conn, user_sub=claims.sub)
    await _audit(claims, audit_kinds.SPACE_RENAMED, row.id)
    return _view(row, [note for note, space in items.items() if space == row.id])


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(space_id: UUID, claims: Annotated[Claims, Depends(_reader)]) -> None:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        deleted = await repo.delete_space(conn, user_sub=claims.sub, space_id=space_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="space not found")
    await _audit(claims, audit_kinds.SPACE_DELETED, space_id)


@router.put("/notes/{note_id}/space", status_code=status.HTTP_204_NO_CONTENT)
async def file_note(
    note_id: UUID, body: FileNoteBody, claims: Annotated[Claims, Depends(_reader)]
) -> None:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        ok = await repo.set_note_space(
            conn,
            tenant_id=claims.tid,
            user_sub=claims.sub,
            note_id=note_id,
            space_id=body.space_id,
        )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="space not found")
