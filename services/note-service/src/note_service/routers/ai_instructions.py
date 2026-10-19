"""Note instructions (N1, N4): how this workspace wants its notes written.

    GET    /v1/ai/instructions[/{scope}]          every member: the text and what was understood
    PUT    /v1/ai/instructions[/{scope}]          admin: save; compiles once with the writing model
    POST   /v1/ai/instructions[/{scope}]/preview  admin: compile without saving (hourly cap)
    DELETE /v1/ai/instructions[/{scope}]          admin: back to writing as today

``scope`` is ``workspace`` (the paths without it) or a meeting family (``client``, ``team``,
…). A type text extends the workspace text: it is compiled together with it, parent first,
and records the workspace version it was built on. Saving or clearing the workspace text
marks every type row ``stale`` and queues their recompile; a stale row never runs.

The text is configuration treated as content: never in a log line, an audit payload, a
metric label or an error detail. What was understood is rendered by code from the
compiled profile; the model's only free text is the guidance, shown verbatim. With the
flag off every route answers 404 ``not_available``. Generated notes do not read the
profile yet (N2).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import ai_settings as settings_rules
from ..domain import note_instructions as ni
from ..domain import note_instructions_compiler as compiler
from ..domain import note_instructions_metrics as metrics
from ..domain import note_instructions_repository as repo
from ..jobs import recompile_instructions
from . import ai_settings as ai_settings_router

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
    """One scope that has a text: its version and whether it waits for a recompile."""

    model_config = ConfigDict(extra="forbid")

    scope: str
    version: int
    stale: bool


class InstructionsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    """0: no instructions; notes are written as today."""
    version: int
    text: str
    profile: dict[str, Any]
    profile_hash: str
    compile_status: str
    compile_error_kind: str | None
    """Rendered by code from the profile, one sentence per dial that differs from today."""
    understood: list[str]
    """Passed to the writer verbatim as wording guidance."""
    guidance: list[str]
    not_applied: list[NotAppliedView]
    can_edit: bool
    max_chars: int
    updated_at: datetime | None
    updated_by: UUID | None
    """N4 — the parents' versions this text was compiled with: `{"workspace": 3}`."""
    base_versions: dict[str, int] = Field(default_factory=dict)
    """The text this one extends (a type's: the workspace's); null for the workspace."""
    extends: ScopeRef | None = None
    """Saved, but waiting for the recompile after its parent changed: not used meanwhile."""
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


def profile_of(row: repo.Row | None) -> ni.WritingProfile:
    """The stored profile, or the empty one: an invalid stored profile is never used."""
    if row is None:
        return ni.EMPTY
    try:
        return ni.WritingProfile.model_validate(row.profile)
    except ValueError:
        logger.warning(
            "note_instructions.profile_invalid",
            extra={"tenant_id": str(row.tenant_id), "version": row.version},
        )
        return ni.EMPTY


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
    text: str | None = None,
    profile: ni.WritingProfile | None = None,
    compile_status: str | None = None,
    compile_error_kind: str | None = None,
) -> InstructionsView:
    """The stored row, or (preview) a compiled text beside the stored version."""
    shown = profile if profile is not None else profile_of(row)
    return InstructionsView(
        scope=scope,
        version=row.version if row is not None else 0,
        text=text if text is not None else (row.text if row is not None else ""),
        profile=shown.model_dump(mode="json"),
        profile_hash=ni.canonical_hash(shown),
        compile_status=compile_status
        or (
            # A stale row's last compile still stands for what it said; `stale` says the rest.
            ("compiled" if row.stale else row.compile_status) if row is not None else "compiled"
        ),
        compile_error_kind=(
            compile_error_kind
            if compile_status is not None
            else (row.compile_error_kind if row is not None else None)
        ),
        understood=ni.understood_lines(shown),
        guidance=list(shown.guidance),
        not_applied=[NotAppliedView(**item) for item in ni.not_applied_view(shown)],
        can_edit=bool(_ADMIN_ROLES & set(claims.roles)),
        max_chars=settings.note_instructions_max_chars,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
        base_versions=dict(row.base_versions) if row is not None else {},
        extends=ScopeRef(scope=parent.scope, version=parent.version)
        if parent is not None
        else None,
        stale=bool(row is not None and row.stale),
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


async def _check_budget(conn: Any, tenant_id: UUID) -> None:
    """A compile is a model call: refused, like a generation, once the month is spent."""
    row = await settings_rules.fetch(conn, tenant_id=tenant_id)
    _plan, limits = await ai_settings_router._plan(conn, tenant_id)
    budget = settings_rules.budget_cents(row, limits)
    spent = await settings_rules.month_to_date_cents(conn, tenant_id=tenant_id)
    if spent >= budget:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "budget_exceeded",
                "detail": "this workspace has spent its AI budget for the month",
                "spent_cents": spent,
                "budget_cents": budget,
            },
        )


async def _compile(tenant_id: UUID, text: str, *, kind: str) -> compiler.CompileResult:
    return await compile_for(tenant_id, text, kind=kind)


async def compile_for(tenant_id: UUID, text: str, *, kind: str) -> compiler.CompileResult:
    """One compile with the workspace's writing model; counted and timed, never logged as text."""
    from models import ConfigError

    state = get_state()
    try:
        provider = await state.note_instructions_compiler.for_workspace(str(tenant_id))
    except ConfigError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "model_unavailable", "detail": "no writing model is available"},
        ) from None
    started = time.monotonic()
    result = await compiler.compile_text(
        text, provider=provider, timeout_s=settings.note_instructions_compile_timeout_s
    )
    seconds = time.monotonic() - started
    metrics.compiles.add(1, {"outcome": result.status, "kind": kind})
    metrics.compile_seconds.record(seconds, {"outcome": result.status})
    for item in result.profile.not_applied:
        metrics.not_applied.add(1, {"reason": item.reason})
    if result.status == "compiled":
        logger.info(
            "note_instructions.compiled",
            extra={
                "tenant_id": str(tenant_id),
                "scope": repo.WORKSPACE,
                "backend": result.backend,
                "chars": len(text),
                "not_applied": len(result.profile.not_applied),
                "duration_ms": int(seconds * 1000),
            },
        )
    else:
        logger.warning(
            "note_instructions.compile_failed",
            extra={"tenant_id": str(tenant_id), "error_kind": result.error_kind},
        )
    return result


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


def _compiled_text(scope: str, text: str, parent: repo.Row | None) -> str:
    """A type text is compiled with the workspace text before it (later parts win)."""
    return compiler.join([parent.text, text]) if scope != repo.WORKSPACE and parent else text


def _bases(scope: str, parent: repo.Row | None) -> dict[str, int]:
    return {repo.WORKSPACE: parent.version} if scope != repo.WORKSPACE and parent else {}


async def _scopes(conn: Any, tenant_id: UUID) -> list[ScopeState]:
    rows = await repo.fetch_many(conn, tenant_id=tenant_id, scopes=repo.SCOPES)
    return [
        ScopeState(scope=s, version=rows[s].version, stale=rows[s].stale)
        for s in repo.SCOPES
        if s in rows
    ]


async def _types_changed(conn: Any, tenant_id: UUID, workspace_version: int) -> None:
    """The workspace text changed: every type row is stale until the job recompiles it."""
    if await repo.mark_types_stale(conn, tenant_id=tenant_id):
        await get_state().job_queue.enqueue(
            tenant_id,
            recompile_instructions.JOB_KIND,
            {"scope": "*"},
            max_attempts=recompile_instructions.MAX_ATTEMPTS,
            idempotency_key=recompile_instructions.idempotency_key(workspace_version),
            conn=conn,
        )


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
            if scope == repo.WORKSPACE:
                # The type texts are recompiled without a parent.
                await _types_changed(conn, claims.tid, row.version + 1)
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
        if (
            existing is not None
            and existing.text == text
            and existing.compile_status == "compiled"
            and existing.compiler_version == compiler.COMPILER_VERSION
            and existing.base_versions == _bases(scope, parent)
        ):
            return _view(claims, row=existing, scope=scope, parent=parent)
        await _check_budget(conn, claims.tid)

    # Outside the transaction: no connection is held during the model call.
    result = await _compile(claims.tid, _compiled_text(scope, text, parent), kind="save")
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.upsert(
            conn,
            tenant_id=claims.tid,
            scope=scope,
            text=text,
            profile=result.profile.model_dump(mode="json"),
            profile_hash=ni.canonical_hash(result.profile),
            compile_status=result.status,
            compile_error_kind=result.error_kind,
            compiler_version=compiler.COMPILER_VERSION,
            backend=result.backend,
            updated_by=claims.sub,
            bump_version=existing is not None and existing.text != text,
            base_versions=_bases(scope, parent),
        )
        if scope == repo.WORKSPACE and (existing is None or existing.text != text):
            await _types_changed(conn, claims.tid, row.version)
    await _audit(
        claims,
        audit_kinds.AI_INSTRUCTIONS_CHANGED,
        {
            "scope": scope,
            "version": row.version,
            "chars": len(text),
            "compile_status": result.status,
            "not_applied": len(result.profile.not_applied),
            "dials": ni.non_default_dials(result.profile),
        },
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
    """Save and compile. Identical text is not compiled again (unless the compiler changed
    or the last compile failed); a failed compile is saved with the empty profile and says
    so — it is not an error. An empty text clears the instructions."""
    return await _put(claims, repo.WORKSPACE, body, response)


@router.put("/{scope}", response_model=InstructionsView)
async def put_scoped_instructions(
    scope: str,
    body: InstructionsRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> InstructionsView:
    """A meeting type's text, compiled together with the workspace text."""
    _enabled()
    return await _put(claims, _scope(scope), body, response)


async def _preview(
    claims: Claims, scope: str, body: InstructionsRequest, response: Response
) -> InstructionsView:
    _enabled()
    _require_admin(claims)
    text = _sanitised(body.text)
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        stored, parent = await _parent_and_rows(conn, claims.tid, scope)
        if text:
            await _check_budget(conn, claims.tid)
    if not text:
        return _view(
            claims, row=stored, scope=scope, parent=parent, text="", profile=ni.EMPTY,
            compile_status="compiled",
        )  # fmt: skip
    allowed, retry_after = await state.note_instructions_rate_limiter.check(tenant_id=claims.tid)
    if not allowed:
        metrics.previews_limited.add(1)
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "too_many_previews",
                "detail": "too many previews this hour",
                "retry_after_s": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    result = await _compile(claims.tid, _compiled_text(scope, text, parent), kind="preview")
    return _view(
        claims,
        row=stored,
        scope=scope,
        parent=parent,
        text=text,
        profile=result.profile,
        compile_status=result.status,
        compile_error_kind=result.error_kind,
    )


@router.post("/preview", response_model=InstructionsView)
async def preview_instructions(
    body: InstructionsRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> InstructionsView:
    """What saving this text would do: compiled, nothing written. Capped per hour."""
    return await _preview(claims, repo.WORKSPACE, body, response)


@router.post("/{scope}/preview", response_model=InstructionsView)
async def preview_scoped_instructions(
    scope: str,
    body: InstructionsRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> InstructionsView:
    """A type text's combined readout (with the workspace text), nothing written."""
    _enabled()
    return await _preview(claims, _scope(scope), body, response)


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
