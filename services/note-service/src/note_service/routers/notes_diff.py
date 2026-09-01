"""GET /notes/{id}/diff — day-5."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import Claims
from db import tenant_connection
from note_models import DiffResponse

from ..deps import get_state, requires
from ..domain import notes_repository as repo
from ..domain.diff_engine import compute_diff

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get("/{note_id}/diff", response_model=DiffResponse)
async def get_diff(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    from_: Annotated[str, Query(alias="from", description="version_id or version_number")],
    to: Annotated[str, Query(description="version_id or version_number")],
) -> DiffResponse:
    state = get_state()

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = await repo.fetch_note(conn, note_id=note_id)
        if note is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")

        from_version = await _resolve(conn, note_id=note_id, ref=from_)
        to_version = await _resolve(conn, note_id=note_id, ref=to)
        if from_version is None or to_version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found in this note")

        cache_hit = state.diff_cache.get(
            note_id=note_id, from_id=from_version.id, to_id=to_version.id
        )
        if cache_hit is not None:
            state.diff_cache_hit_metric.add(1, {"hit": "true"})
            return cache_hit
        state.diff_cache_hit_metric.add(1, {"hit": "false"})

        diff = compute_diff(
            note_id=str(note_id),
            from_version_id=str(from_version.id),
            from_version_number=from_version.version_number,
            from_content=from_version.content,
            to_version_id=str(to_version.id),
            to_version_number=to_version.version_number,
            to_content=to_version.content,
        )

    state.diff_cache.put(
        note_id=note_id,
        from_id=from_version.id,
        to_id=to_version.id,
        value=diff,
    )
    return diff


async def _resolve(conn, *, note_id: UUID, ref: str):
    if ref.isdigit():
        return await repo.fetch_version_by_number(conn, note_id=note_id, version_number=int(ref))
    try:
        version_id = UUID(ref)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"version reference {ref!r} is neither a version_number nor a UUID",
        ) from None
    v = await repo.fetch_version(conn, version_id=version_id)
    if v is None or v.note_id != note_id:
        return None
    return v
