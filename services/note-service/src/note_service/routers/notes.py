"""POST /notes + GET /notes/{id}."""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteContent, ReadPurpose

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import access, code_sequence, relocation
from ..domain import notes_repository as repo
from ..domain import visibility as visibility_defaults
from ._content_guard import ensure_valid_field_metadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


# ── Request / response shapes ───────────────────────────────────────


class CreateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: NoteContent
    co_author_ids: list[UUID] = Field(default_factory=list)
    source_session_id: UUID | None = None
    # W5: only an explicit author choice; omitted → the workspace's default.
    visibility: Literal["private", "workspace"] | None = None


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
    # The transcription job the note was made from; null when the transcript is not shared with you.
    source_job_id: UUID | None = None
    visibility: str = "workspace"
    # DEPRECATED (W3): always the legacy array; read `GET /{id}/sharing` instead.
    shared_with_ids: list[UUID] = Field(default_factory=list)
    # W3: what the caller may do here, and whether transcript/audio are theirs to open.
    my_level: str | None = None
    can_read_transcript: bool = False
    # Only filled for an oversight read, so the client can name whose note it shows.
    primary_author_name: str | None = None
    # W5: ready | rehoming ("Transcript on its way") | failed; a copy's source note.
    media_state: str = "ready"
    copied_from_note_id: UUID | None = None
    content: NoteContent | None = None
    section_labels: list[SectionLabel] | None = None


# ── Helpers ─────────────────────────────────────────────────────────


def _envelope(
    row: repo.NoteRow,
    *,
    content: NoteContent | None = None,
    section_labels: list[SectionLabel] | None = None,
    primary_author_name: str | None = None,
    claims: Claims | None = None,
) -> NoteEnvelope:
    transcript = claims is not None and access.can_read_transcript(row, claims)
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
        source_job_id=row.source_asr_job_id if transcript else None,
        visibility=row.visibility,
        shared_with_ids=row.shared_with_ids,
        my_level=access.level(row, claims) if claims is not None else None,
        can_read_transcript=transcript,
        primary_author_name=primary_author_name,
        media_state=row.media_state,
        copied_from_note_id=row.copied_from_note_id,
        content=content,
        section_labels=section_labels,
    )


async def _resolve_section_labels(
    conn: object, *, content: NoteContent
) -> list[SectionLabel] | None:
    """Localized section labels in content order: the template's name or the
    section's own ``title``; none for an unheaded block. ``None`` (never raises)
    when the template is gone and no section carries a title."""
    import json

    from template_models import TemplateDefinition

    from ..domain.repository import get_template

    template_names: dict[str, str] = {}
    try:
        tmpl_row = await get_template(conn, template_id=content.template_id)
        if tmpl_row is not None:
            raw = tmpl_row["schema_jsonb"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            definition = TemplateDefinition.model_validate(raw)
            template_names = {section.id: section.name for section in definition.sections}
    except Exception:
        logger.warning(
            "could not resolve template %s for section labels",
            content.template_id,
            exc_info=True,
        )

    labels: list[SectionLabel] = []
    for section in content.sections:
        name = template_names.get(section.section_key) or section.title
        if not name:
            continue
        # Mirror the single name into both locales (matches toStudioTemplate).
        labels.append(
            SectionLabel(section_key=section.section_key, name=LocalizedText(uk=name, en=name))
        )
    if not labels and not template_names:
        return None
    return labels


async def _resolve_section_names(conn: object, *, content: NoteContent) -> dict[str, str]:
    """``{section_key: heading}`` in content order, for the PDF renderer; unnamed sections absent."""
    labels = await _resolve_section_labels(conn, content=content) or []
    return {
        label.section_key: name for label in labels if (name := (label.name.en or label.name.uk))
    }


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
        await ensure_valid_field_metadata(conn, content=body.content)

        if body.visibility is not None:
            await visibility_defaults.require_allowed(
                conn, tenant_id=claims.tid, visibility=body.visibility
            )
        code = await code_sequence.next_code(conn, tenant_id=claims.tid)
        note_id, version_id = await repo.create_note_with_v1(
            conn,
            tenant_id=claims.tid,
            code=code,
            primary_author_id=claims.sub,
            co_author_ids=body.co_author_ids,
            template_id=body.content.template_id,
            template_schema_version=body.content.template_schema_version,
            template_source="user",
            source_session_id=body.source_session_id,
            content=body.content,
            visibility=body.visibility
            or await visibility_defaults.default_for_new_note(
                conn, tenant_id=claims.tid, template_id=body.content.template_id
            ),
            visibility_source="author" if body.visibility is not None else "default",
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
        found = await repo.fetch_note(conn, note_id=note_id)
        if found is None:
            # W5: an old deep link to a note that moved answers where it went.
            await relocation.raise_if_moved(conn, note_id=note_id, claims=claims)
        row = access.require_view(found, claims)

        # An oversight reader must say why they are reading; author team and sharees never do.
        is_author = access.require_read_purpose(row, claims, purpose)

        # An oversight reader is told whose note it is.
        primary_author_name: str | None = None
        if not is_author:
            members = await repo.fetch_members(conn, subs=[row.primary_author_id])
            primary_author_name = members[0].display_name if members else None

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

    return _envelope(
        row,
        content=content_obj,
        section_labels=section_labels,
        primary_author_name=primary_author_name,
        claims=claims,
    )
