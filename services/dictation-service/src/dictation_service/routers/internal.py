"""Loopback-only scale-in drain hook, called from the pod's own preStop.

POST flips the one-way draining flag (no new sessions, /readyz 503); GET
reports progress. Non-loopback clients are refused outright.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from ..deps import get_state

router = APIRouter(prefix="/internal", tags=["internal"])

_LOOPBACKS = {"127.0.0.1", "::1", "localhost"}


class DrainStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draining: bool
    active_sessions: int
    total_weight: int


def _loopback_only(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in _LOOPBACKS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="internal surface is loopback-only",
        )


@router.post("/drain", response_model=DrainStatus, summary="Begin scale-in drain")
async def begin_drain(request: Request) -> DrainStatus:
    _loopback_only(request)
    state = get_state()
    state.session_manager.begin_drain()
    return _status(state)


@router.get("/drain", response_model=DrainStatus, summary="Drain progress")
async def drain_status(request: Request) -> DrainStatus:
    _loopback_only(request)
    return _status(get_state())


def _status(state: object) -> DrainStatus:
    manager = state.session_manager  # type: ignore[attr-defined]
    return DrainStatus(
        draining=manager.draining,
        active_sessions=manager.active_count,
        total_weight=manager.total_weight,
    )
