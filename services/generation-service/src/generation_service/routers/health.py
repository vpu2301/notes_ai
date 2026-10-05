"""Liveness + readiness probes.

Feature disabled = ready (reported as ``layer_c_enabled: false``); feature on with
an unreachable backend = unready.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ..config import settings

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    state = getattr(request.app.state, "svc", None)
    if state is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "starting"}
    try:
        await state.redis.ping()
    except Exception:  # noqa: BLE001 — any probe failure means not-ready
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "layer_c_enabled": settings.layer_c_enabled}
    if not settings.layer_c_enabled:
        return {"status": "ready", "layer_c_enabled": False}
    backend_ok = state.inference is not None and await state.inference.ready()
    if not backend_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unready",
            "layer_c_enabled": True,
            "reason": "inference backend unreachable",
        }
    # Reachable but cold backend is not ready.
    if not getattr(state, "warmed", True):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unready",
            "layer_c_enabled": True,
            "reason": "model warming",
            "warmed": False,
        }
    return {
        "status": "ready",
        "layer_c_enabled": True,
        "model": settings.gen_model,
        "warmed": True,
    }
