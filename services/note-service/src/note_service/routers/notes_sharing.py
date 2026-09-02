"""Delete, visibility and sharing for one note (0016).

    GET    /v1/notes/{id}/sharing        who can see it, and the public link
    PUT    /v1/notes/{id}/visibility     private | workspace
    POST   /v1/notes/{id}/share          give a workspace member access (+ notify)
    DELETE /v1/notes/{id}/share/{sub}    take it back
    POST   /v1/notes/{id}/public-link    "anyone with the link" (idempotent)
    DELETE /v1/notes/{id}/public-link    revoke it
    DELETE /v1/notes/{id}                soft delete

Sharing with a member goes out as a ``note.shared_with_you`` notification
(in-app and e-mail per their preferences) carrying the note code and the
sharer's name — never the title or content (ADR-0031). Someone who is not
a member cannot be granted access; the client offers the public link
instead.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from notification_events import Category

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import access
from ..domain import notes_repository as repo
from ..domain.share_tokens import hash_token, token_for
from ..notifications import emit_note_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

Visibility = Literal["private", "workspace"]

# Public links do not expire by default; an author who wants a
# deadline sets one when creating the link.
_MAX_LINK_DAYS = 365


# ── Wire models ─────────────────────────────────────────────────────


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: UUID
    email: str
    display_name: str


class PublicLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    # The SPA path an anonymous reader opens; the client prefixes its
    # own origin so links point at whichever host served the page.
    path: str
    created_at: str
    expires_at: str | None
    view_count: int
    last_viewed_at: str | None


class SharingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    visibility: Visibility
    can_manage: bool
    can_delete: bool
    shared_with: list[Member]
    public_link: PublicLink | None


class VisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Loose shape check only; the real test is "is this a member".
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PublicLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_in_days: int | None = Field(default=None, ge=1, le=_MAX_LINK_DAYS)


class DeletedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    deleted_at: str


# ── Helpers ─────────────────────────────────────────────────────────


def _link_view(link: repo.ShareLinkRow) -> PublicLink:
    token = token_for(link.id, key_hex=settings.share_link_hmac_key_hex)
    return PublicLink(
        token=token,
        path=f"/s/{token}",
        created_at=link.created_at.isoformat(),
        expires_at=link.expires_at.isoformat() if link.expires_at else None,
        view_count=link.view_count,
        last_viewed_at=link.last_viewed_at.isoformat() if link.last_viewed_at else None,
    )


async def _sharing_view(conn: object, note: repo.NoteRow, claims: Claims) -> SharingView:
    members = await repo.fetch_members(conn, subs=note.shared_with_ids)  # type: ignore[arg-type]
    link = await repo.fetch_live_share_link(conn, note_id=note.id)  # type: ignore[arg-type]
    return SharingView(
        note_id=note.id,
        visibility=note.visibility,  # type: ignore[arg-type]
        can_manage=access.can_manage(note, claims),
        can_delete=access.can_delete(note, claims),
        shared_with=[
            Member(sub=m.sub, email=m.email, display_name=m.display_name) for m in members
        ],
        public_link=_link_view(link) if link else None,
    )


async def _audit(claims: Claims, kind: str, note_id: UUID, payload: dict[str, object]) -> None:
    state = get_state()
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload=payload,
        severity=Severity.INFO,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/{note_id}/sharing", response_model=SharingView)
async def get_sharing(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        return await _sharing_view(conn, note, claims)


@router.put("/{note_id}/visibility", response_model=SharingView)
async def set_visibility(
    note_id: UUID,
    body: VisibilityRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        previous = note.visibility
        if previous != body.visibility:
            await repo.set_visibility(conn, note_id=note_id, visibility=body.visibility)
            note = await repo.fetch_note(conn, note_id=note_id) or note
        view = await _sharing_view(conn, note, claims)
    if previous != body.visibility:
        await _audit(
            claims,
            audit_kinds.NOTE_VISIBILITY_CHANGED,
            note_id,
            {"from": previous, "to": body.visibility},
        )
    return view


@router.post("/{note_id}/share", response_model=SharingView)
async def share_with_member(
    note_id: UUID,
    body: ShareRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        member = await repo.find_member_by_email(conn, email=str(body.email))
        if member is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "not_a_member",
                    "detail": "nobody in your workspace has that e-mail address",
                },
            )
        already = member.sub in note.shared_with_ids or access.is_author_team(note, member.sub)
        if not already:
            await repo.add_shared_with(conn, note_id=note_id, user_sub=member.sub)
            note = await repo.fetch_note(conn, note_id=note_id) or note
        # The sharer's name for the notification — a person, not a sub.
        (me,) = await repo.fetch_members(conn, subs=[claims.sub]) or [None]
        view = await _sharing_view(conn, note, claims)

    if not already:
        await _audit(
            claims, audit_kinds.NOTE_SHARED, note_id, {"with": str(member.sub), "via": "member"}
        )
        await emit_note_event(
            state.redis,
            category=Category.NOTE_SHARED_WITH_YOU,
            tenant_id=claims.tid,
            note_id=note_id,
            note_code=note.code,
            actor_user_id=claims.sub,
            # The recipient hint IS the sharee — nobody else is told.
            primary_author_id=member.sub,
            extra_payload={"shared_by_display": me.display_name if me else "A colleague"},
        )
    return view


@router.delete("/{note_id}/share/{user_sub}", response_model=SharingView)
async def unshare_member(
    note_id: UUID,
    user_sub: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        if user_sub in note.shared_with_ids:
            await repo.remove_shared_with(conn, note_id=note_id, user_sub=user_sub)
            note = await repo.fetch_note(conn, note_id=note_id) or note
        view = await _sharing_view(conn, note, claims)
    await _audit(claims, audit_kinds.NOTE_UNSHARED, note_id, {"with": str(user_sub)})
    return view


@router.post("/{note_id}/public-link", response_model=SharingView)
async def create_public_link(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
    body: PublicLinkRequest | None = None,
) -> SharingView:
    """Idempotent: a note has at most one live link, and asking again
    returns it rather than minting a second."""
    state = get_state()
    created = False
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        link = await repo.fetch_live_share_link(conn, note_id=note_id)
        if link is None:
            link_id = uuid4()
            expires = None
            if body is not None and body.expires_in_days is not None:
                expires = datetime.now(UTC) + timedelta(days=body.expires_in_days)
            link = await repo.create_share_link(
                conn,
                link_id=link_id,
                tenant_id=claims.tid,
                note_id=note_id,
                token_hash=hash_token(token_for(link_id, key_hex=settings.share_link_hmac_key_hex)),
                created_by=claims.sub,
                expires_at=expires,
            )
            created = True
        view = await _sharing_view(conn, note, claims)
    if created:
        await _audit(
            claims,
            audit_kinds.NOTE_LINK_CREATED,
            note_id,
            {
                "link_id": str(link.id),
                "expires_at": view.public_link.expires_at if view.public_link else None,
            },
        )
    return view


@router.delete("/{note_id}/public-link", response_model=SharingView)
async def revoke_public_link(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        revoked = await repo.revoke_share_links(conn, note_id=note_id, actor_sub=claims.sub)
        view = await _sharing_view(conn, note, claims)
    if revoked:
        await _audit(claims, audit_kinds.NOTE_LINK_REVOKED, note_id, {"revoked": revoked})
    return view


@router.delete("/{note_id}", response_model=DeletedResponse)
async def delete_note(
    note_id: UUID,
    request: Request,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> DeletedResponse:
    """Soft delete. The note leaves every list and read path and its
    public links stop working; the row and its versions are kept."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_delete(await repo.fetch_note(conn, note_id=note_id), claims)
        await repo.soft_delete_note(conn, note_id=note_id, actor_sub=claims.sub)
    deleted_at = datetime.now(UTC)
    await _audit(
        claims,
        audit_kinds.NOTE_DELETED,
        note_id,
        {
            "code": note.code,
            "status": note.status.value,
            "user_agent": request.headers.get("user-agent", "")[:120],
        },
    )
    return DeletedResponse(id=note_id, deleted_at=deleted_at.isoformat())
