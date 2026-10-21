"""Note templates (Sprint P2): the built-in texts the writer shapes a note with, and a
workspace's own text for any of them.

    GET    /v1/ai/templates                 every member: every template (built-in or the
                                            workspace's override), per name and language
    GET    /v1/ai/templates/{name}?language= one
    PUT    /v1/ai/templates/{name}          admin: {language, markdown} — the override
    DELETE /v1/ai/templates/{name}?language= admin: back to the built-in text

A built-in is read-only (``source: builtin``); the override of the same name and language
is what the writer reads. The Markdown is content: never logged or audited.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import prompts, writer
from ..domain import templates_repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ai/templates", tags=["ai"])

_ADMIN_ROLES = frozenset({"tenant_admin"})
NAMES: tuple[str, ...] = (*writer.TEMPLATES, writer.AUTO)
MAX_CHARS = 4_000
Language = Literal["en", "de", "uk"]


class TemplateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    markdown: str = Field(max_length=10 * MAX_CHARS)


class TemplateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    language: str
    """``builtin``: the file that ships; ``workspace``: this workspace's own text."""
    source: Literal["builtin", "workspace"]
    markdown: str
    can_edit: bool
    updated_at: datetime | None = None
    updated_by: UUID | None = None


def _require_admin(claims: Claims) -> None:
    if not (_ADMIN_ROLES & set(claims.roles)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="only a workspace admin can change the note templates",
        )


def _name(name: str) -> str:
    if name not in NAMES:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "template_unknown", "detail": "no such template"},
        )
    return name


def _view(name: str, language: str, override: repo.Row | None, *, can_edit: bool) -> TemplateView:
    if override is not None:
        return TemplateView(
            name=name,
            language=language,
            source="workspace",
            markdown=override.markdown,
            can_edit=can_edit,
            updated_at=override.updated_at,
            updated_by=override.updated_by,
        )
    return TemplateView(
        name=name,
        language=language,
        source="builtin",
        markdown=writer.template_text(name, language),
        can_edit=can_edit,
    )


def validate_markdown(markdown: str) -> str:
    """The text as stored: trimmed, at most ``MAX_CHARS``, at least one ``## `` heading."""
    text = markdown.replace("\r\n", "\n").strip()
    if not text or len(text) > MAX_CHARS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "template_too_long" if text else "template_empty",
                "detail": f"a template is 1 to {MAX_CHARS} characters",
                "max_chars": MAX_CHARS,
            },
        )
    if not any(line.startswith("## ") for line in text.splitlines()):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "template_no_sections",
                "detail": 'a template needs at least one "## " heading',
            },
        )
    return text


async def _audit(claims: Claims, kind: str, payload: dict[str, Any]) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="tenant",
        target_id=claims.tid,
        payload=payload,  # name, language and counts only: never the text
        severity=Severity.INFO,
    )


@router.get("", response_model=list[TemplateView])
async def list_templates(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
    language: Language | None = Query(default=None),
) -> list[TemplateView]:
    """Every template, in `language` (default: every language), built-in or overridden."""
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        rows = await repo.fetch_all(conn, tenant_id=claims.tid)
    overrides = {(r.name, r.language): r for r in rows}
    can_edit = bool(_ADMIN_ROLES & set(claims.roles))
    languages = [language] if language else list(prompts.LANGUAGES)
    return [
        _view(name, lang, overrides.get((name, lang)), can_edit=can_edit)
        for name in NAMES
        for lang in languages
    ]


@router.get("/{name}", response_model=TemplateView)
async def get_template(
    name: str,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
    language: Language = Query(default="en"),
) -> TemplateView:
    name = _name(name)
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        row = await repo.fetch(conn, tenant_id=claims.tid, name=name, language=language)
    return _view(name, language, row, can_edit=bool(_ADMIN_ROLES & set(claims.roles)))


@router.put("/{name}", response_model=TemplateView)
async def put_template(
    name: str,
    body: TemplateBody,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> TemplateView:
    """This workspace's text for the template; the writer reads it from the next note on."""
    name = _name(name)
    _require_admin(claims)
    markdown = validate_markdown(body.markdown)
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        row = await repo.upsert(
            conn,
            tenant_id=claims.tid,
            name=name,
            language=body.language,
            markdown=markdown,
            updated_by=claims.sub,
        )
    await _audit(
        claims,
        audit_kinds.AI_TEMPLATE_CHANGED,
        {"name": name, "language": body.language, "chars": len(markdown)},
    )
    return _view(name, body.language, row, can_edit=True)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    name: str,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
    language: Language = Query(default="en"),
) -> Response:
    """Back to the built-in text. Idempotent."""
    name = _name(name)
    _require_admin(claims)
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        removed = await repo.delete(conn, tenant_id=claims.tid, name=name, language=language)
    if removed:
        await _audit(claims, audit_kinds.AI_TEMPLATE_RESET, {"name": name, "language": language})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
