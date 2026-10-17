"""Comments on a note (W3 B-4, migration 0074, ADR-0071).

    GET    /v1/notes/{id}/comments                    list (view)
    POST   /v1/notes/{id}/comments                    add (comment)
    PATCH  /v1/notes/{id}/comments/{cid}              edit own (comment)
    POST   /v1/notes/{id}/comments/{cid}/resolve      resolve (edit)
    POST   /v1/notes/{id}/comments/{cid}/unresolve    reopen (edit)
    DELETE /v1/notes/{id}/comments/{cid}              soft delete (own, or manage)

Every route re-fetches the note by (tenant, note id) and the comment by
(note id, comment id), so a comment id from another note is a 404. Bodies are
content: never logged, never audited, never put in a notification.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..collaboration_metrics import comments_created
from ..deps import get_state, requires
from ..domain import access, action_items
from ..domain import comments_repository as comments_repo
from ..domain import notes_repository as repo
from ..domain.text import clean_comment
from ..notifications import emit_note_commented

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

AnchorKind = Literal["note", "section", "item"]

MAX_BODY = 2000
COMMENTS_PER_HOUR = 120
_RL_WINDOW_S = 3600
# Shown for an author whose profile is no longer readable here (left the workspace).
_FORMER_MEMBER = "Former member"


# ── Wire models ─────────────────────────────────────────────────────


class CommentAuthor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: UUID
    display_name: str


class CommentView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    author: CommentAuthor
    anchor_kind: AnchorKind
    anchor_key: str
    # False when the section or item it was written on is gone from the current version.
    anchor_present: bool
    body: str
    created_at: datetime
    edited_at: datetime | None
    resolved_at: datetime | None
    resolved_by_display: str | None
    can_edit: bool
    can_resolve: bool
    can_delete: bool


class CommentList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CommentView]


def _clean_body(value: str) -> str:
    cleaned = clean_comment(value, max_len=MAX_BODY, allow_links=True)
    if cleaned is None:
        raise ValueError("comment is empty")
    return cleaned


class CreateCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_kind: AnchorKind = "note"
    anchor_key: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=MAX_BODY)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _clean_body(value)


class EditCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_BODY)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _clean_body(value)


# ── Helpers ─────────────────────────────────────────────────────────


async def _anchor_keys(conn: object, note: repo.NoteRow, kinds: set[str]) -> dict[str, set[str]]:
    """Section and item keys of the note's current version, loaded only for the kinds asked."""
    keys: dict[str, set[str]] = {"section": set(), "item": set()}
    if not kinds & {"section", "item"}:
        return keys
    version = await repo.fetch_version(conn, version_id=note.current_version_id)  # type: ignore[arg-type]
    if version is None:
        return keys
    if "section" in kinds:
        keys["section"] = {s.section_key for s in version.content.sections or []}
    if "item" in kinds:
        items = await action_items.ensure_items(conn, note=note, version=version)
        keys["item"] = {it.item_key for it in items}
    return keys


def _present(comment: comments_repo.CommentRow, keys: dict[str, set[str]]) -> bool:
    if comment.anchor_kind == "note":
        return True
    return comment.anchor_key in keys.get(comment.anchor_kind, set())


async def _names(conn: object, subs: set[UUID]) -> dict[UUID, str]:
    members = await repo.fetch_members(conn, subs=sorted(subs))  # type: ignore[arg-type]
    return {m.sub: m.display_name for m in members}


def _view(
    comment: comments_repo.CommentRow,
    *,
    note: repo.NoteRow,
    claims: Claims,
    names: dict[UUID, str],
    present: bool,
) -> CommentView:
    mine = comment.author_sub == claims.sub
    return CommentView(
        id=comment.id,
        author=CommentAuthor(
            sub=comment.author_sub, display_name=names.get(comment.author_sub, _FORMER_MEMBER)
        ),
        anchor_kind=comment.anchor_kind,  # type: ignore[arg-type]
        anchor_key=comment.anchor_key,
        anchor_present=present,
        body=comment.body,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        resolved_at=comment.resolved_at,
        resolved_by_display=(
            names.get(comment.resolved_by, _FORMER_MEMBER)
            if comment.resolved_by is not None
            else None
        ),
        can_edit=mine and access.can_comment(note, claims),
        can_resolve=access.can_edit(note, claims),
        can_delete=mine or access.can_manage(note, claims),
    )


async def _single_view(
    conn: object, comment: comments_repo.CommentRow, note: repo.NoteRow, claims: Claims
) -> CommentView:
    keys = await _anchor_keys(conn, note, {comment.anchor_kind})
    subs = {comment.author_sub} | ({comment.resolved_by} if comment.resolved_by else set())
    return _view(
        comment,
        note=note,
        claims=claims,
        names=await _names(conn, subs),
        present=_present(comment, keys),
    )


async def _require_comment_row(
    conn: object, note_id: UUID, comment_id: UUID
) -> comments_repo.CommentRow:
    found = await comments_repo.fetch_comment(conn, note_id=note_id, comment_id=comment_id)  # type: ignore[arg-type]
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="comment not found")
    return found


async def _check_rate(claims: Claims) -> None:
    """120 comments per hour per (workspace, person); fail-open when Redis is down."""
    redis = get_state().redis
    bucket = int(time.time() // _RL_WINDOW_S)
    key = f"note:comment-rl:{claims.tid}:{claims.sub}:{bucket}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, _RL_WINDOW_S + 60)
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning(
            "note.comment_rate_limit_redis_error", extra={"error_class": type(exc).__name__}
        )
        return
    if count > COMMENTS_PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="comment rate limit reached",
            headers={"Retry-After": str(_RL_WINDOW_S - int(time.time() % _RL_WINDOW_S))},
        )


async def _still_readers(conn: object, note: repo.NoteRow, subs: list[UUID]) -> list[UUID]:
    """Earlier commenters who can still see the note: the author team, a live grant, or an
    active non-guest member of a workspace-visible note (owners/admins always)."""
    keep = [s for s in subs if access.is_author_team(note, s) or s in note.collaborators]
    rest = [s for s in subs if s not in keep]
    if rest:
        roles = await repo.membership_roles(conn, subs=rest)  # type: ignore[arg-type]
        for sub, role in roles.items():
            if role in ("owner", "admin") or (
                note.visibility == access.VISIBILITY_WORKSPACE and role in ("member", "viewer")
            ):
                keep.append(sub)
    return keep


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/{note_id}/comments", response_model=CommentList)
async def list_comments(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> CommentList:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        rows = await comments_repo.list_comments(conn, note_id=note.id)
        keys = await _anchor_keys(conn, note, {r.anchor_kind for r in rows})
        subs = {r.author_sub for r in rows} | {r.resolved_by for r in rows if r.resolved_by}
        names = await _names(conn, subs) if subs else {}
    return CommentList(
        items=[
            _view(r, note=note, claims=claims, names=names, present=_present(r, keys)) for r in rows
        ]
    )


@router.post("/{note_id}/comments", response_model=CommentView, status_code=status.HTTP_201_CREATED)
async def create_comment(
    note_id: UUID,
    body: CreateCommentRequest,
    # Commenting is not writing the note: a viewer on a workspace note may comment.
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> CommentView:
    state = get_state()
    anchor_key = "" if body.anchor_kind == "note" else body.anchor_key.strip()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_comment(await repo.fetch_note(conn, note_id=note_id), claims)
        await _check_rate(claims)
        if body.anchor_kind != "note":
            keys = await _anchor_keys(conn, note, {body.anchor_kind})
            if anchor_key not in keys[body.anchor_kind]:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="anchor not found")
        earlier = await comments_repo.commenters_on_anchor(
            conn, note_id=note.id, anchor_kind=body.anchor_kind, anchor_key=anchor_key
        )
        earlier = await _still_readers(conn, note, earlier)
        comment = await comments_repo.insert_comment(
            conn,
            tenant_id=claims.tid,
            note_id=note.id,
            author_sub=claims.sub,
            anchor_kind=body.anchor_kind,
            anchor_key=anchor_key,
            body=body.body,
        )
        view = await _single_view(conn, comment, note, claims)

    comments_created.add(1, {"anchor_kind": body.anchor_kind})
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_COMMENTED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note.id,
        payload={"anchor_kind": body.anchor_kind},
        severity=Severity.INFO,
    )
    await emit_note_commented(
        state.redis,
        tenant_id=claims.tid,
        note_id=note.id,
        note_code=note.code,
        actor_user_id=claims.sub,
        recipients=[note.primary_author_id, *note.co_author_ids, *earlier],
        anchor_kind=body.anchor_kind,
    )
    return view


@router.patch("/{note_id}/comments/{comment_id}", response_model=CommentView)
async def edit_comment(
    note_id: UUID,
    comment_id: UUID,
    body: EditCommentRequest,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> CommentView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_comment(await repo.fetch_note(conn, note_id=note_id), claims)
        comment = await _require_comment_row(conn, note.id, comment_id)
        if comment.author_sub != claims.sub:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": "not_comment_author", "detail": "only its author edits a comment"},
            )
        updated = await comments_repo.update_body(
            conn, note_id=note.id, comment_id=comment.id, body=body.body
        )
        if updated is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="comment not found")
        return await _single_view(conn, updated, note, claims)


async def _set_resolved(
    note_id: UUID, comment_id: UUID, claims: Claims, *, resolve: bool
) -> CommentView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_edit(await repo.fetch_note(conn, note_id=note_id), claims)
        comment = await _require_comment_row(conn, note.id, comment_id)
        updated = await comments_repo.set_resolved(
            conn,
            note_id=note.id,
            comment_id=comment.id,
            resolved_by=claims.sub if resolve else None,
        )
        if updated is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="comment not found")
        return await _single_view(conn, updated, note, claims)


@router.post("/{note_id}/comments/{comment_id}/resolve", response_model=CommentView)
async def resolve_comment(
    note_id: UUID,
    comment_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> CommentView:
    return await _set_resolved(note_id, comment_id, claims, resolve=True)


@router.post("/{note_id}/comments/{comment_id}/unresolve", response_model=CommentView)
async def unresolve_comment(
    note_id: UUID,
    comment_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> CommentView:
    return await _set_resolved(note_id, comment_id, claims, resolve=False)


@router.delete("/{note_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    note_id: UUID,
    comment_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> Response:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        comment = await _require_comment_row(conn, note.id, comment_id)
        if comment.author_sub != claims.sub:
            access.require_manage(note, claims)
        await comments_repo.soft_delete(
            conn, note_id=note.id, comment_id=comment.id, deleted_by=claims.sub
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
