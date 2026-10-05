"""Liveness + readiness probes.

A worker without a warm diarizer stays ready for dictation but advertises
``conversation_ready=false``.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from ..config import settings
from ..deps import get_state

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    db: str
    redis: str
    model_loaded: bool
    gpu_available: bool
    # ── conversation capacity ────────────────────────────────────────
    conversation_enabled: bool
    diarizer_loaded: bool
    conversation_ready: bool
    diarizer_error: str | None = None
    # Live capacity, so an operator can see why a worker refuses sessions.
    capacity_used: int
    capacity_max: int
    conversation_session_weight: int
    conversation_slots_free: int


@router.get(
    "/healthz",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/readyz",
    summary="Readiness probe — DB, Redis, Whisper, GPU",
)
async def readyz(response: Response) -> ReadyResponse:
    state = get_state()
    db_ok = "ok"
    redis_ok = "ok"
    try:
        async with state.app_pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        db_ok = f"fail: {type(exc).__name__}"
    try:
        pong = await cast("Awaitable[bool]", state.redis.ping())
        if not pong:
            redis_ok = "fail: no pong"
    except Exception as exc:  # noqa: BLE001
        redis_ok = f"fail: {type(exc).__name__}"
    model_loaded = state.engine.is_loaded
    gpu_available = _gpu_available()

    diar = state.diarization_engine
    conversation_ready = diar.ready_for_conversation
    weight = settings.conversation_session_weight
    used = state.session_manager.total_weight
    free = max(0, settings.per_worker_max_sessions - used)

    # Whisper is required, the diarizer is not; draining also flips readiness.
    ok = db_ok == "ok" and redis_ok == "ok" and model_loaded and not state.session_manager.draining
    response.status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if ok else "not_ready",
        db=db_ok,
        redis=redis_ok,
        model_loaded=model_loaded,
        gpu_available=gpu_available,
        conversation_enabled=diar.enabled,
        diarizer_loaded=diar.loaded,
        conversation_ready=conversation_ready,
        diarizer_error=diar.last_error,
        capacity_used=used,
        capacity_max=settings.per_worker_max_sessions,
        conversation_session_weight=weight,
        # Zero unless the diarizer is warm.
        conversation_slots_free=(free // weight) if (conversation_ready and weight > 0) else 0,
    )


def _gpu_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False
