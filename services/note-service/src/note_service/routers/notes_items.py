"""Author-side action items and recipient responses (Sprint 20, 0037).

    GET   /v1/notes/{id}/items                       items of the current version + responses
    PATCH /v1/notes/{id}/items/{item_id}             {status} — the one thing an author edits here
    GET   /v1/notes/{id}/responses                   every live response and flag, newest first
    POST  /v1/notes/{id}/responses/{response_id}/clear

Items are a projection of the section text (G-1), derived the first
time a version is read (`action_items.ensure_items`): their wording,
owner and date change by editing the note, never through this router. Status is the exception — "done" is a fact about the world, not
about the text — so it is the only writable field.

A recipient's comment is returned here verbatim. It is the author's to
read; the clients render it as text and nothing else.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import ReadPurpose

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import access, action_items
from ..domain import action_items_repository as items_repo
from ..domain import notes_repository as repo

router = APIRouter(prefix="/v1/notes", tags=["notes"])

ItemStatus = Literal["open", "done", "dropped"]
ResponseKind = Literal["confirm", "done", "dispute", "flag"]


class ResponseView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    link_id: UUID
    # The sender's own label for the recipient ("Tom @ Client").
    link_label: str
    kind: ResponseKind
    item_key: str | None
    section_key: str | None
    comment: str | None
    created_at: datetime
    cleared_at: datetime | None


class ItemCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirms: int
    dones: int
    disputes: int


class ItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    item_key: str
    position: int
    text: str
    owner_label: str | None
    owner_confidence: float | None
    due_date: date | None
    due_text: str | None
    due_confidence: float | None
    status: ItemStatus
    counts: ItemCounts
    responses: list[ResponseView]


class ItemStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ItemStatus


def _response_view(r: items_repo.ResponseRow) -> ResponseView:
    return ResponseView(
        id=r.id,
        link_id=r.link_id,
        link_label=r.link_label,
        kind=r.kind,  # type: ignore[arg-type]
        item_key=r.item_key,
        section_key=r.section_key,
        comment=r.comment,
        created_at=r.created_at,
        cleared_at=r.cleared_at,
    )


def item_views(
    items: list[items_repo.ItemRow], responses: list[items_repo.ResponseRow]
) -> list[ItemView]:
    by_key: dict[str, list[items_repo.ResponseRow]] = {}
    for r in responses:
        if r.item_key and r.cleared_at is None:
            by_key.setdefault(r.item_key, []).append(r)
    out: list[ItemView] = []
    for it in items:
        mine = by_key.get(it.item_key, [])
        out.append(
            ItemView(
                id=it.id,
                item_key=it.item_key,
                position=it.position,
                text=it.text,
                owner_label=it.owner_label,
                owner_confidence=it.owner_confidence,
                due_date=it.due_date,
                due_text=it.due_text,
                due_confidence=it.due_confidence,
                status=it.status,  # type: ignore[arg-type]
                counts=ItemCounts(
                    confirms=sum(1 for r in mine if r.kind == "confirm"),
                    dones=sum(1 for r in mine if r.kind == "done"),
                    disputes=sum(1 for r in mine if r.kind == "dispute"),
                ),
                responses=[_response_view(r) for r in mine],
            )
        )
    return out


async def _audit(claims: Claims, kind: str, note_id: UUID, payload: dict[str, object]) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload=payload,
        severity=Severity.INFO,
    )


@router.get("/{note_id}/items", response_model=list[ItemView])
async def list_items(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: ReadPurpose | None = Query(default=None),
) -> list[ItemView]:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        # Same rule as reading the note: an oversight reader says why.
        access.require_read_purpose(note, claims, purpose)
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        items = (
            await action_items.ensure_items(conn, note=note, version=version)
            if version is not None
            else []
        )
        responses = await items_repo.list_responses(conn, note_id=note_id)
    return item_views(items, responses)


@router.patch("/{note_id}/items/{item_id}", response_model=ItemView)
async def set_item_status(
    note_id: UUID,
    item_id: UUID,
    body: ItemStatusRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> ItemView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        item = await items_repo.fetch_item(conn, note_id=note_id, item_id=item_id)
        if item is None or item.note_version_id != note.current_version_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item not found")
        previous = item.status
        if previous != body.status:
            await items_repo.set_item_status(
                conn, item_id=item_id, status=body.status, actor_sub=claims.sub
            )
            item.status = body.status
        responses = await items_repo.list_responses(conn, note_id=note_id)
    if previous != body.status:
        await _audit(
            claims,
            audit_kinds.NOTE_ITEM_STATUS_CHANGED,
            note_id,
            {"item_key": item.item_key, "from": previous, "to": body.status},
        )
    return item_views([item], responses)[0]


@router.get("/{note_id}/responses", response_model=list[ResponseView])
async def list_responses(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: ReadPurpose | None = Query(default=None),
    include_cleared: bool = Query(default=False),
) -> list[ResponseView]:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        access.require_read_purpose(note, claims, purpose)
        rows = await items_repo.list_responses(
            conn, note_id=note_id, include_cleared=include_cleared
        )
    return [_response_view(r) for r in rows]


@router.post("/{note_id}/responses/{response_id}/clear", response_model=ResponseView)
async def clear_response(
    note_id: UUID,
    response_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> ResponseView:
    """The author clears a response (a resolved dispute, an abusive
    comment). The row stays, stamped with who cleared it and when."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        cleared = await items_repo.clear_response(
            conn, note_id=note_id, response_id=response_id, actor_sub=claims.sub
        )
    if cleared is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="response not found")
    await _audit(claims, audit_kinds.NOTE_RESPONSE_CLEARED, note_id, {"kind": cleared.kind})
    return _response_view(cleared)
