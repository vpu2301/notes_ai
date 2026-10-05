"""The `/ws/notifications` route: authorize (ws/upgrade.py), then hand off (ws/handler.py)."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.websockets import WebSocket

from ..deps import get_state
from ..ws.handler import run_session
from ..ws.upgrade import UpgradeRejected, authorize_upgrade, ws_code_for_http

router = APIRouter()


@router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket) -> None:
    state = get_state()
    try:
        upgrade = await authorize_upgrade(websocket, jwks_cache=state.jwks_cache)
    except UpgradeRejected as rejection:
        # Mapped 4xxx close code tells the client why; accept() is needed first to send one.
        await websocket.close(code=ws_code_for_http(rejection.status_code))
        return

    await run_session(websocket, upgrade=upgrade, state=state)
