"""Liveness + readiness for asr-service.

``/readyz`` actively probes DB, Redis, and object storage to support k8s readiness
gating. With no ``S3_ENDPOINT`` configured there is no object store to probe
(the local MinIO container is gone), so that leg reports ``skipped`` rather
than holding the pod out of the load balancer forever. Sprint 03 introduces the first multi-dependency readiness path —
keep it cheap (each probe ≤ 250 ms) so the cluster doesn't churn replicas.
"""

from __future__ import annotations

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
    s3: str


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
    status_code=status.HTTP_200_OK,
    summary="Readiness probe — verifies DB, Redis, object storage reachable",
)
async def readyz(response: Response) -> ReadyResponse:
    state = get_state()
    db_ok = "ok"
    redis_ok = "ok"
    s3_ok = "ok"

    try:
        async with state.app_pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        db_ok = f"fail: {type(exc).__name__}"

    try:
        pong = await state.redis.ping()
        if not pong:
            redis_ok = "fail: no pong"
    except Exception as exc:  # noqa: BLE001
        redis_ok = f"fail: {type(exc).__name__}"

    if not settings.s3_endpoint:
        s3_ok = "skipped: no S3_ENDPOINT"
    else:
        try:
            await state.s3.head_bucket(state.audio_store.bucket)
        except Exception as exc:  # noqa: BLE001
            s3_ok = f"fail: {type(exc).__name__}"

    # Any failing dependency flips the response code (a skipped object
    # store does not: there is nothing to be unready about).
    if db_ok != "ok" or redis_ok != "ok" or s3_ok.startswith("fail"):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="not_ready", db=db_ok, redis=redis_ok, s3=s3_ok)
    return ReadyResponse(status="ready", db=db_ok, redis=redis_ok, s3=s3_ok)
