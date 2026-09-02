"""GET /v1/notes/{id}/sections/{section_key}/audio-clips — replay segments.

Lists the audio moments behind one note section so the author can
tap a sentence and hear the ground truth (sprint 15, ADR-0037).

Sections populated by the sprint-14 conversation draft carry
``transcript_segment_ids`` and map 1:1; everything older predates the
field (a sprint-08 placeholder) and falls back to the WHOLE session
transcript — replay still works, the FE aligns by timing. Timings +
speakers only, no transcript text: the text is already in the note the
caller just read.

Access: ``note.read`` plus the sprint-08 ``?purpose=`` rule for
non-authors.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from auth import Claims
from db import tenant_connection
from note_models import ReadPurpose

from ..deps import get_state, requires
from ..domain import access
from ..domain import audio_clips as clips
from ..domain import notes_repository as repo
from .notes_versions import _enforce_read_purpose

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


class AudioSegmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: UUID | None  # conversation-mode segments only; else null
    index: int  # position in the session transcript — stable address
    start_ms: int
    end_ms: int
    speaker: str | None
    speaker_role: str | None


@router.get(
    "/{note_id}/sections/{section_key}/audio-clips",
    response_model=list[AudioSegmentOut],
)
async def list_section_audio_segments(
    note_id: UUID,
    section_key: str,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: Annotated[
        ReadPurpose | None, Query(description="Required for non-author reads.")
    ] = None,
) -> list[AudioSegmentOut]:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # A private note the caller was not given is a 404 (0016).
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        _enforce_read_purpose(note, claims, purpose)

        if note.source_session_id is None:
            # Batch notes have no session transcript to list; clip
            # creation by explicit ms range still works (the FE holds the
            # batch transcript's timings).
            return []

        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
        section = next((s for s in version.content.sections if s.section_key == section_key), None)
        if section is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="section not found")

        transcript = await clips.load_session_transcript(conn, session_id=note.source_session_id)

    refs = clips.segments_from_transcript(transcript, segment_ids=section.transcript_segment_ids)
    return [
        AudioSegmentOut(
            segment_id=r.segment_id,
            index=r.index,
            start_ms=r.start_ms,
            end_ms=r.end_ms,
            speaker=r.speaker,
            speaker_role=r.speaker_role,
        )
        for r in refs
    ]
