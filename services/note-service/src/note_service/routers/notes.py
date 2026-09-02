"""POST /notes + GET /notes/{id} — sprint-08 day-1/day-6."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteContent, ReadPurpose

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import access, code_sequence
from ..domain import notes_repository as repo
from ._content_guard import ensure_valid_field_metadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


# ── Request / response shapes ───────────────────────────────────────


class CreateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: NoteContent
    co_author_ids: list[UUID] = Field(default_factory=list)
    source_session_id: UUID | None = None


class NoteCreatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    version_id: UUID
    version_number: int
    status: str


class LocalizedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uk: str
    en: str


class SectionLabel(BaseModel):
    """Human-readable, localized title for one note section.

    Templates are per-language (a template row is either ``uk`` or ``en``),
    so the section ``name`` is a single string in the template's own
    language. We mirror it into BOTH ``uk`` and ``en`` here — the same
    behaviour the frontend's ``toStudioTemplate`` uses — so the SPA/PDF can
    render section titles without re-fetching the template, and historical
    notes carry their labels even if the template later changes.
    """

    model_config = ConfigDict(extra="forbid")

    section_key: str
    name: LocalizedText


class NoteEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    status: str
    current_version_id: UUID
    current_version_number: int
    primary_author_id: UUID
    co_author_ids: list[UUID]
    title: str
    created_at: str
    updated_at: str
    finalized_at: str | None
    cancelled_at: str | None
    # 0016 — who may read it beyond the author team.
    visibility: str = "workspace"
    shared_with_ids: list[UUID] = Field(default_factory=list)
    content: NoteContent | None = None
    section_labels: list[SectionLabel] | None = None


# ── Helpers ─────────────────────────────────────────────────────────


def _envelope(
    row: repo.NoteRow,
    *,
    content: NoteContent | None = None,
    section_labels: list[SectionLabel] | None = None,
) -> NoteEnvelope:
    return NoteEnvelope(
        id=row.id,
        code=row.code,
        status=row.status.value,
        current_version_id=row.current_version_id,
        current_version_number=row.current_version_number,
        primary_author_id=row.primary_author_id,
        co_author_ids=row.co_author_ids,
        title=row.title,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        finalized_at=row.finalized_at.isoformat() if row.finalized_at else None,
        cancelled_at=row.cancelled_at.isoformat() if row.cancelled_at else None,
        visibility=row.visibility,
        shared_with_ids=row.shared_with_ids,
        content=content,
        section_labels=section_labels,
    )


async def _resolve_section_labels(
    conn: object, *, content: NoteContent
) -> list[SectionLabel] | None:
    """Build localized section labels from the note's template.

    Resolves the template by ``content.template_id`` (reusing the domain
    ``get_template`` repository helper within the caller's RLS-scoped
    connection) and emits one :class:`SectionLabel` per template section,
    ordered by the section ``order``. Returns ``None`` — never raises — if
    the template was deleted or cannot be parsed, so a missing template
    degrades gracefully instead of 500-ing the read.

    Note: only the current template row is persisted per ``template_id``
    (cosmetic edits update in place), so we resolve against it; section
    names are cosmetic and never participate in ``body_hash``.
    """
    import json

    from template_models import TemplateDefinition

    from ..domain.repository import get_template

    try:
        tmpl_row = await get_template(conn, template_id=content.template_id)  # type: ignore[arg-type]
        if tmpl_row is None:
            return None
        raw = tmpl_row["schema_jsonb"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        definition = TemplateDefinition.model_validate(raw)
    except Exception:
        logger.warning(
            "could not resolve template %s for section labels",
            content.template_id,
            exc_info=True,
        )
        return None

    return [
        # Templates are per-language; mirror the single name into both
        # locales (matches the frontend's toStudioTemplate behaviour).
        SectionLabel(section_key=section.id, name=LocalizedText(uk=section.name, en=section.name))
        for section in sorted(definition.sections, key=lambda s: s.order)
    ]


# ── Routes ──────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=NoteCreatedResponse,
    responses={
        422: {
            "description": "Sprint-13 field-metadata validation: "
            "`field_metadata_invalid` / `choice_value_unknown` "
            "(section-addressed problems in `problems[]`)."
        }
    },
)
async def create_note(
    body: CreateNoteRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> NoteCreatedResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # Sprint-13: typed field metadata must be valid at every write.
        await ensure_valid_field_metadata(conn, content=body.content)

        code = await code_sequence.next_code(conn, tenant_id=claims.tid)
        note_id, version_id = await repo.create_note_with_v1(
            conn,
            tenant_id=claims.tid,
            code=code,
            primary_author_id=claims.sub,
            co_author_ids=body.co_author_ids,
            template_id=body.content.template_id,
            template_schema_version=body.content.template_schema_version,
            source_session_id=body.source_session_id,
            content=body.content,
        )

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_CREATED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={"code": code, "version_id": str(version_id)},
        severity=Severity.INFO,
    )

    return NoteCreatedResponse(
        id=note_id,
        code=code,
        version_id=version_id,
        version_number=1,
        status="draft",
    )


@router.get("/{note_id}", response_model=NoteEnvelope)
async def get_note(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: Annotated[
        ReadPurpose | None,
        Query(description="Required for non-author reads."),
    ] = None,
    include_content: bool = Query(default=True),
) -> NoteEnvelope:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # A private note the caller was not given is a 404, not a 403.
        row = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)

        # Read-purpose enforcement: required if requester is not author/co-author.
        # Someone the note was shared with reads as a collaborator.
        is_author = access.is_author_team(row, claims.sub) or claims.sub in row.shared_with_ids
        if not is_author and purpose is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "type": "https://errors.notes-ai/missing-read-purpose",
                    "title": "Read purpose required",
                    "detail": "Non-author reads must include ?purpose=<value>",
                    "allowed": [p.value for p in ReadPurpose],
                },
            )

        content_obj: NoteContent | None = None
        section_labels: list[SectionLabel] | None = None
        if include_content:
            v = await repo.fetch_version(conn, version_id=row.current_version_id)
            content_obj = v.content if v else None
            if content_obj is not None:
                section_labels = await _resolve_section_labels(conn, content=content_obj)

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_VIEWED_FULL,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={
            "purpose": purpose.value if purpose else "author",
            "is_author": is_author,
        },
        severity=Severity.INFO,
    )

    return _envelope(row, content=content_obj, section_labels=section_labels)
