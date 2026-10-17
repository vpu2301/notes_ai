"""Who else has a note open (W3 B-6). No history: a Redis sorted set per note,
member = sub, score = last heartbeat; a member older than ``PRESENCE_TTL_S`` is
dropped on every read and write, and the key itself expires with the last one.

    POST /v1/notes/{id}/presence    heartbeat (view), 204
    GET  /v1/notes/{id}/presence    {viewers:[{sub, display_name}]} minus the caller

Fail-open: with Redis down a heartbeat is a no-op and nobody is listed.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from auth import Claims
from db import tenant_connection

from ..collaboration_metrics import presence_viewers
from ..deps import get_state, requires
from ..domain import access
from ..domain import notes_repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

PRESENCE_TTL_S = 45

# Indirection so tests can drive the clock.
_now = time.time


class Viewer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: UUID
    display_name: str


class PresenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    viewers: list[Viewer]


def _key(tenant_id: UUID, note_id: UUID) -> str:
    return f"note:presence:{tenant_id}:{note_id}"


@router.post("/{note_id}/presence", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> Response:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
    key = _key(claims.tid, note.id)
    now = _now()
    try:
        await state.redis.zadd(key, {str(claims.sub): now})
        await state.redis.zremrangebyscore(key, "-inf", now - PRESENCE_TTL_S)
        await state.redis.expire(key, PRESENCE_TTL_S)
    except Exception as exc:  # noqa: BLE001 — presence is decoration; fail open
        logger.warning("note.presence_redis_error", extra={"error_class": type(exc).__name__})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{note_id}/presence", response_model=PresenceView)
async def list_presence(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> PresenceView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        key = _key(claims.tid, note.id)
        now = _now()
        try:
            await state.redis.zremrangebyscore(key, "-inf", now - PRESENCE_TTL_S)
            raw = await state.redis.zrangebyscore(key, now - PRESENCE_TTL_S, "+inf")
        except Exception as exc:  # noqa: BLE001 — fail open
            logger.warning("note.presence_redis_error", extra={"error_class": type(exc).__name__})
            raw = []
        subs: list[UUID] = []
        for member in raw:
            try:
                sub = UUID(member.decode() if isinstance(member, bytes) else str(member))
            except ValueError:
                continue
            if sub != claims.sub:
                subs.append(sub)
        # profile_of_subs answers only for active members of this workspace.
        members = await repo.fetch_members(conn, subs=subs) if subs else []
    presence_viewers.record(len(members))
    return PresenceView(viewers=[Viewer(sub=m.sub, display_name=m.display_name) for m in members])
