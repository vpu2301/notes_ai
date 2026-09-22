"""The workspace glossary (Sprint 35, migration 0050).

    GET    /v1/glossary        every live term
    POST   /v1/glossary        remember a term (opt-in, one at a time)
    DELETE /v1/glossary/{id}   forget it — the creator or an admin
    GET    /v1/glossary/hint   the terms as a `vocabulary_hint` string

Nothing is learned silently. A client offers "Remember *John Mayer* for
this workspace?" after the author corrects a name, and only a yes reaches
``POST``. The list is visible and every entry is deletable, because the
failure mode of a vocabulary that learns by itself is that it learns
something wrong and nobody can find it.

Terms are personal and business data: tenant-scoped by RLS, never in a log
line or an audit payload (only counts and the closed ``kind`` vocabulary),
and gone with the tenant.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import glossary as rules
from ..domain import glossary_repository as glossary_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/glossary", tags=["glossary"])

_ADMIN_ROLES = frozenset({"tenant_admin"})


class TermView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    term: str
    kind: Literal["person", "company", "product", "term"]
    heard_as: list[str]
    created_at: datetime
    """Whether the caller may delete this one (its creator, or an admin)."""
    can_delete: bool


class AddTermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str = Field(max_length=rules.MAX_TERM * 2)
    kind: Literal["person", "company", "product", "term"] = "person"
    # What it was heard or spelled as before the author fixed it.
    heard_as: list[str] = Field(default_factory=list, max_length=16)


class HintView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hint: str
    terms: int


def _view(row: glossary_repo.GlossaryRow, claims: Claims) -> TermView:
    return TermView(
        id=row.id,
        term=row.term,
        kind=row.kind,  # type: ignore[arg-type]
        heard_as=row.heard_as,
        created_at=row.created_at,
        can_delete=row.created_by == claims.sub or bool(_ADMIN_ROLES & set(claims.roles)),
    )


async def _audit(claims: Claims, kind: str, payload: dict[str, object]) -> None:
    """Counts and the closed ``kind`` vocabulary only — never the term."""
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="tenant",
        target_id=claims.tid,
        payload=payload,
        severity=Severity.INFO,
    )


@router.get("", response_model=list[TermView])
async def list_glossary(
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> list[TermView]:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        rows = await glossary_repo.list_terms(conn)
    return [_view(row, claims) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TermView)
async def add_glossary_term(
    body: AddTermRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> TermView:
    """Remember one term.

    Adding a term the workspace already has is not an error: it merges the
    new mishearing into the existing entry and answers 200. Saying
    "remember John Mayer" after two different mistakes should teach the
    second one, not fail as a duplicate.
    """
    try:
        term = rules.clean_term(body.term)
        heard_as = rules.clean_heard_as(body.heard_as, term=term)
    except rules.GlossaryError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "detail": exc.detail},
        ) from None

    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        existing = await glossary_repo.find_term(conn, term=term)
        if existing is not None:
            merged = await glossary_repo.merge_heard_as(conn, row=existing, heard_as=heard_as)
            response.status_code = status.HTTP_200_OK
            return _view(merged, claims)

        if await glossary_repo.count_terms(conn) >= rules.MAX_TERMS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "glossary_full",
                    "detail": f"a workspace keeps at most {rules.MAX_TERMS} terms",
                },
            )
        try:
            row = await glossary_repo.add_term(
                conn,
                tenant_id=claims.tid,
                term=term,
                kind=body.kind,
                heard_as=heard_as,
                created_by=claims.sub,
            )
        except asyncpg.UniqueViolationError:
            # Added concurrently by another device; theirs is as good.
            again = await glossary_repo.find_term(conn, term=term)
            if again is None:
                raise
            response.status_code = status.HTTP_200_OK
            return _view(again, claims)

    await _audit(
        claims,
        audit_kinds.GLOSSARY_TERM_ADDED,
        {"kind": body.kind, "heard_as_count": len(heard_as)},
    )
    return _view(row, claims)


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(
    term_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> None:
    """Forget a term. Its creator, or an admin — a vocabulary one person
    can quietly change for everyone is a vocabulary nobody trusts."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        rows = {row.id: row for row in await glossary_repo.list_terms(conn)}
        row = rows.get(term_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="term not found")
        if row.created_by != claims.sub and not (_ADMIN_ROLES & set(claims.roles)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="only the person who added a term, or an admin, can remove it",
            )
        await glossary_repo.soft_delete_term(conn, term_id=term_id)
    await _audit(claims, audit_kinds.GLOSSARY_TERM_DELETED, {"kind": row.kind})


@router.get("/hint", response_model=HintView)
async def glossary_hint(
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> HintView:
    """The workspace's terms as the capture form's ``vocabulary_hint``.

    The clients fetch this and pre-fill the field, so the transcriber has
    the spellings before it guesses. It stays editable: the hint is a
    suggestion about this meeting, not a setting.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        terms = await glossary_repo.terms_for_matching(conn)
    return HintView(hint=rules.hint_text(terms), terms=len(terms))
