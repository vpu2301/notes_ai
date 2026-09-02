"""Anonymous reads of a publicly shared note (0016).

    GET /v1/shared/{token}        the note, rendered for reading
    GET /v1/shared/{token}/pdf    the same as a PDF

No bearer, no tenant claim: the token is the whole credential. It is
resolved through the SECURITY DEFINER function from migration 0016 and
only then does the request get an ordinary RLS-scoped connection for
the tenant it turned out to belong to. Every read is audited against
that tenant with no actor — the reader is, by definition, unknown.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from db import tenant_connection
from note_models import NoteStatus

from .. import audit_kinds
from ..config import settings
from ..deps import get_state
from ..domain import notes_repository as repo
from ..domain.branding import load_tenant_branding
from ..domain.pdf import render_note_pdf
from ..domain.share_tokens import hash_token, looks_like_token
from .notes import _resolve_section_labels

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/shared", tags=["shared"])


class SharedSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_key: str
    name: str
    text: str


class SharedNoteView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    title: str
    status: str
    updated_at: str
    sections: list[SharedSection]
    # Whose workspace this came from — the tenant's display name, not a
    # person's.
    issuer_name: str


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="this link is not valid any more")


async def _resolve(token: str) -> tuple[UUID, UUID, UUID]:
    if not looks_like_token(token):
        raise _not_found()
    state = get_state()
    # The resolver runs outside any tenant scope: a plain pool connection.
    async with state.app_pool.acquire() as conn:
        found = await repo.resolve_share_link(conn, token_hash=hash_token(token))
    if found is None:
        raise _not_found()
    return found


async def _audit_view(tenant_id: UUID, note_id: UUID, link_id: UUID, *, fmt: str) -> None:
    state = get_state()
    await state.audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.NOTE_VIEWED_VIA_LINK,
        actor_sub=None,
        actor_role=None,
        target_kind="note",
        target_id=note_id,
        payload={"link_id": str(link_id), "format": fmt},
        severity=Severity.INFO,
    )


@router.get("/{token}", response_model=SharedNoteView)
async def read_shared_note(token: str) -> SharedNoteView:
    tenant_id, note_id, link_id = await _resolve(token)
    state = get_state()
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        note = await repo.fetch_note(conn, note_id=note_id)
        if note is None or note.status == NoteStatus.CANCELLED:
            raise _not_found()
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise _not_found()
        labels = await _resolve_section_labels(conn, content=version.content) or []
        branding = await load_tenant_branding(conn, tenant_id=str(tenant_id))
        await repo.record_share_link_view(conn, link_id=link_id)

    names = {label.section_key: label.name.en or label.name.uk for label in labels}
    order = [label.section_key for label in labels]
    sections = sorted(
        version.content.sections or [],
        key=lambda s: order.index(s.section_key) if s.section_key in order else len(order),
    )
    await _audit_view(tenant_id, note_id, link_id, fmt="html")
    return SharedNoteView(
        code=note.code,
        title=version.content.title or note.title,
        status=note.status.value,
        updated_at=note.updated_at.isoformat(),
        sections=[
            SharedSection(
                section_key=s.section_key,
                name=names.get(s.section_key, s.section_key),
                text=s.text or "",
            )
            for s in sections
            if (s.text or "").strip()
        ],
        issuer_name=(
            branding.issuer_name if branding.issuer_name != "—" else settings.pdf_issuer_name
        ),
    )


@router.get("/{token}/pdf", responses={200: {"content": {"application/pdf": {}}}})
async def read_shared_note_pdf(token: str) -> Response:
    tenant_id, note_id, link_id = await _resolve(token)
    state = get_state()
    async with tenant_connection(state.app_pool, tenant_id) as conn:
        note = await repo.fetch_note(conn, note_id=note_id)
        if note is None or note.status == NoteStatus.CANCELLED:
            raise _not_found()
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise _not_found()
        branding = await load_tenant_branding(conn, tenant_id=str(tenant_id))
        await repo.record_share_link_view(conn, link_id=link_id)

    issuer = branding.issuer_name if branding.issuer_name != "—" else settings.pdf_issuer_name
    is_draft = note.status not in (NoteStatus.FINALIZED, NoteStatus.AMENDED)
    pdf_bytes = render_note_pdf(
        note=note, version=version, issuer_name=issuer, is_draft=is_draft, language="en"
    )
    await _audit_view(tenant_id, note_id, link_id, fmt="pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{note.code}.pdf"'},
    )
