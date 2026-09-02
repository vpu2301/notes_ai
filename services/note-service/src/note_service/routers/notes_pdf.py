"""GET /notes/{id}/pdf — server-rendered PDF (M1·A3 + draft export).

Renders the current version of a note as a PDF. Draft notes are
rendered with a visible DRAFT treatment (watermark + banner) so a
work-in-progress export is never mistaken for the final record. Only a
*cancelled* note is refused (409); a finalized/amended note can be
exported "clean" via ``?variant=clean``. The weasyprint import lives
behind ``domain.pdf`` so it never loads on the router import path.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteStatus, ReadPurpose

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import access
from ..domain import notes_repository as repo
from ..domain.branding import load_tenant_branding
from ..domain.pdf import render_note_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get(
    "/{note_id}/pdf",
    summary="Render the current version as a PDF (draft watermark for draft notes; 409 only for cancelled).",
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_note_pdf(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: Annotated[
        ReadPurpose | None, Query(description="Required for non-author reads.")
    ] = None,
    variant: Annotated[
        Literal["draft", "clean"],
        Query(
            description="'clean' is only honoured for finalized/amended notes; drafts always render as draft."
        ),
    ] = "draft",
    lang: Annotated[
        Literal["uk", "en", "de"] | None,
        Query(description="Render language; falls back to 'en'."),
    ] = None,
) -> Response:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)

        is_author = access.is_author_team(note, claims.sub) or claims.sub in note.shared_with_ids
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

        # A cancelled note must never be exported.
        if note.status == NoteStatus.CANCELLED:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "type": "https://errors.notes-ai/note-cancelled",
                    "title": "Note is cancelled",
                    "status": status.HTTP_409_CONFLICT,
                    "detail": (f"note {note_id} is cancelled and cannot be rendered to PDF"),
                    "note_status": note.status.value,
                },
            )

        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")

        # Tenant branding for the document header (issuer name). Read under the
        # same RLS-scoped connection; falls back to the configured default when
        # the tenant carries no branding.
        branding = await load_tenant_branding(conn, tenant_id=str(claims.tid))

    # Draft treatment whenever the note is still a draft, OR when explicitly
    # requested via ``variant=draft``. ``clean`` is only honoured for
    # finalized/amended notes; a draft is forced to draft regardless.
    is_final = note.status in (NoteStatus.FINALIZED, NoteStatus.AMENDED)
    is_draft = (not is_final) or variant == "draft"
    language = lang or "en"

    # Prefer the tenant's registered/legal name as the document issuer; fall
    # back to the service-level default when the tenant has no branding set.
    issuer_name = branding.issuer_name if branding.issuer_name != "—" else settings.pdf_issuer_name
    pdf_bytes = render_note_pdf(
        note=note,
        version=version,
        issuer_name=issuer_name,
        is_draft=is_draft,
        language=language,
    )

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_PDF_RENDERED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload={
            "version_number": version.version_number,
            "size_bytes": len(pdf_bytes),
            "purpose": purpose.value if purpose else "author",
            "variant": "draft" if is_draft else "clean",
            "note_status": note.status.value,
        },
        severity=Severity.INFO,
    )

    filename = f"note-{note_id}-draft.pdf" if is_draft else f"note-{note_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
