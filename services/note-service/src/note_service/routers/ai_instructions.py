"""Note instructions (N1, N4): how this workspace wants its notes written.

    GET    /v1/ai/instructions[/{scope}]   every member: the text
    PUT    /v1/ai/instructions[/{scope}]   admin: save
    DELETE /v1/ai/instructions[/{scope}]   admin: back to writing as usual

``scope`` is ``workspace`` (the paths without it) or a meeting family (``client``, ``team``,
…). A type text extends the workspace text and records the workspace version it was saved
against. The text is stored and shown; nothing compiles it (Sprint R0) — the writer reads
it as written; with nothing saved it follows the default rules that ship
(``writer_templates/instructions.default.md``), which the view carries (P2a). The text is
configuration treated as content: never in a log line, an audit
payload, a metric label or an error detail. With the flag off every route answers 404
``not_available``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import note_instructions as ni
from ..domain import note_instructions_repository as repo
from ..domain import writer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ai/instructions", tags=["ai"])

_ADMIN_ROLES = frozenset({"tenant_admin"})


class InstructionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class NotAppliedView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    reason: str
    """The fixed sentence for the reason; clients show it as sent."""
    message: str


class ScopeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    version: int


class ScopeState(BaseModel):
    """One scope that has a text: its version."""

    model_config = ConfigDict(extra="forbid")

    scope: str
    version: int
    stale: bool


class InstructionsView(BaseModel):
    """The stored text. The ``profile``, ``understood``, ``guidance`` and ``not_applied``
    fields are the shape clients read; since Sprint R0 nothing compiles the text, so they
    are empty and ``compile_status`` is always ``compiled``."""

    model_config = ConfigDict(extra="forbid")

    scope: str
    """0: nothing saved; ``text`` is then the default rules."""
    version: int
    """The text the writer follows: the saved text, else the default rules (P2a)."""
    text: str
    """``workspace`` when a saved text replaces the default rules, else ``default``."""
    source: Literal["workspace", "default"] = "workspace"
    """The rules that ship, so a client can show and reset to them without a second call."""
    default_text: str = ""
    profile: dict[str, Any]
    profile_hash: str
    compile_status: str
    compile_error_kind: str | None
    understood: list[str]
    guidance: list[str]
    not_applied: list[NotAppliedView]
    can_edit: bool
    max_chars: int
    updated_at: datetime | None
    updated_by: UUID | None
    """N4 — the parents' versions this text was saved against: `{"workspace": 3}`."""
    base_versions: dict[str, int] = Field(default_factory=dict)
    """The text this one extends (a type's: the workspace's); null for the workspace."""
    extends: ScopeRef | None = None
    stale: bool = False
    """On the workspace view: every scope that has a text."""
    scopes: list[ScopeState] = Field(default_factory=list)


def _enabled() -> None:
    if not settings.note_instructions_enabled:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "not_available", "detail": "note instructions are not available"},
        )


def _require_admin(claims: Claims) -> None:
    if not (_ADMIN_ROLES & set(claims.roles)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="only a workspace admin can change how notes are written",
        )


def _scope(scope: str) -> str:
    if scope not in repo.SCOPES:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "scope_unknown", "detail": "no such kind of meeting"},
        )
    return scope


def _view(
    claims: Claims,
    *,
    row: repo.Row | None,
    scope: str = repo.WORKSPACE,
    parent: repo.Row | None = None,
    scopes: list[ScopeState] | None = None,
) -> InstructionsView:
    default_text = writer.default_instructions()
    return InstructionsView(
        scope=scope,
        version=row.version if row is not None else 0,
        text=row.text if row is not None else default_text,
        source="workspace" if row is not None else "default",
        default_text=default_text,
        profile=dict(ni.STORED_PROFILE),
        profile_hash=ni.STORED_PROFILE_HASH,
        compile_status=ni.STORED_COMPILE_STATUS,
        compile_error_kind=None,
        understood=[],
        guidance=[],
        not_applied=[],
        can_edit=bool(_ADMIN_ROLES & set(claims.roles)),
        max_chars=settings.note_instructions_max_chars,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
        base_versions=dict(row.base_versions) if row is not None else {},
        extends=ScopeRef(scope=parent.scope, version=parent.version)
        if parent is not None
        else None,
        stale=False,
        scopes=scopes or [],
    )


def _sanitised(text: str) -> str:
    """The text as it would be stored; longer than the limit is a 413, never a cut."""
    clean = ni.sanitize_text(text, max_chars=10 * settings.note_instructions_max_chars)
    if len(clean) > settings.note_instructions_max_chars:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "text_too_long",
                "detail": "the instructions are longer than the limit",
                "max_chars": settings.note_instructions_max_chars,
            },
        )
    return clean


async def _audit(claims: Claims, kind: str, payload: dict[str, object]) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="tenant",
        target_id=claims.tid,
        # Scope, version and counts only: never the text.
        payload=payload,
        severity=Severity.INFO,
    )


async def _parent_and_rows(
    conn: Any, tenant_id: UUID, scope: str
) -> tuple[repo.Row | None, repo.Row | None]:
    """``(the row of this scope, the workspace row when the scope is a type)``."""
    rows = await repo.fetch_many(conn, tenant_id=tenant_id, scopes=(scope, repo.WORKSPACE))
    return rows.get(scope), (rows.get(repo.WORKSPACE) if scope != repo.WORKSPACE else None)


def _bases(scope: str, parent: repo.Row | None) -> dict[str, int]:
    return {repo.WORKSPACE: parent.version} if scope != repo.WORKSPACE and parent else {}


async def _scopes(conn: Any, tenant_id: UUID) -> list[ScopeState]:
    rows = await repo.fetch_many(conn, tenant_id=tenant_id, scopes=repo.SCOPES)
    return [
        ScopeState(scope=s, version=rows[s].version, stale=False) for s in repo.SCOPES if s in rows
    ]


async def _get(claims: Claims, scope: str) -> InstructionsView:
    _enabled()
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        row, parent = await _parent_and_rows(conn, claims.tid, scope)
        scopes = await _scopes(conn, claims.tid) if scope == repo.WORKSPACE else None
    return _view(claims, row=row, scope=scope, parent=parent, scopes=scopes)


@router.get("", response_model=InstructionsView)
async def get_instructions(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> InstructionsView:
    return await _get(claims, repo.WORKSPACE)


@router.get("/{scope}", response_model=InstructionsView)
async def get_scoped_instructions(
    scope: str,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> InstructionsView:
    _enabled()
    return await _get(claims, _scope(scope))


async def _clear(claims: Claims, scope: str) -> repo.Row | None:
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        row = await repo.fetch(conn, tenant_id=claims.tid, scope=scope)
        if row is not None:
            await repo.delete(conn, tenant_id=claims.tid, scope=scope)
    if row is not None:
        await _audit(
            claims,
            audit_kinds.AI_INSTRUCTIONS_CLEARED,
            {"scope": scope, "version": row.version},
        )
    return row


async def _put(
    claims: Claims, scope: str, body: InstructionsRequest, response: Response
) -> InstructionsView:
    _enabled()
    _require_admin(claims)
    text = _sanitised(body.text)
    if not text:
        await _clear(claims, scope)
        return await _get(claims, scope)

    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        existing, parent = await _parent_and_rows(conn, claims.tid, scope)
        if existing is not None and existing.text == text:
            return _view(claims, row=existing, scope=scope, parent=parent)
        row = await repo.upsert(
            conn,
            tenant_id=claims.tid,
            scope=scope,
            text=text,
            profile=dict(ni.STORED_PROFILE),
            profile_hash=ni.STORED_PROFILE_HASH,
            compile_status=ni.STORED_COMPILE_STATUS,
            compile_error_kind=None,
            compiler_version=ni.STORED_COMPILER_VERSION,
            backend=None,
            updated_by=claims.sub,
            bump_version=existing is not None and existing.text != text,
            base_versions=_bases(scope, parent),
        )
    await _audit(
        claims,
        audit_kinds.AI_INSTRUCTIONS_CHANGED,
        {"scope": scope, "version": row.version, "chars": len(text)},
    )
    if existing is None:
        response.status_code = status.HTTP_201_CREATED
    return _view(claims, row=row, scope=scope, parent=parent)


@router.put("", response_model=InstructionsView)
async def put_instructions(
    body: InstructionsRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> InstructionsView:
    """Save. Identical text is not a new version; an empty text clears the instructions."""
    return await _put(claims, repo.WORKSPACE, body, response)


@router.put("/{scope}", response_model=InstructionsView)
async def put_scoped_instructions(
    scope: str,
    body: InstructionsRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> InstructionsView:
    """A meeting type's text, extending the workspace text."""
    _enabled()
    return await _put(claims, _scope(scope), body, response)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instructions(
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> Response:
    _enabled()
    _require_admin(claims)
    await _clear(claims, repo.WORKSPACE)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{scope}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scoped_instructions(
    scope: str,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> Response:
    _enabled()
    _require_admin(claims)
    await _clear(claims, _scope(scope))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
