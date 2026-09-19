"""asr-service entry point.

Sprint 03 surface:
- ``/healthz`` / ``/readyz``
- ``/asr/jobs``   POST upload, GET list, GET id, DELETE id

Use ``create_app()`` for tests; production runs via
``uvicorn asr_service.main:app --host 0.0.0.0 --port 8000``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from observability import bootstrap, register_exception_handlers
from observability.problem_details import http_exception_handler
from storage import ObjectStoreNotConfiguredError

from .config import settings
from .deps import install_state
from .domain.reaper import reaper_loop
from .main_deps import build_state, teardown_state
from .middleware import RequestIDMiddleware
from .routers import health, jobs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    bootstrap(
        settings.service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        log_level=settings.log_level,
        deployment_environment=settings.environment,
        package_name="asr-service",
        disable_otel=settings.testing or settings.otel_sdk_disabled,
    )

    state = await build_state()
    app.state.svc = state
    install_state(state)

    # Out-of-process backstop for jobs stranded by a dead worker — the
    # worker is the only writer of a job's terminal status, and it cannot
    # write one for the crash that killed it.
    reaper_stop = asyncio.Event()
    reaper_task: asyncio.Task[None] | None = None
    if settings.job_reaper_enabled:
        reaper_task = asyncio.create_task(reaper_loop(state, reaper_stop))

    logger.info(
        "asr-service starting",
        extra={
            "service": settings.service_name,
            "env": settings.environment,
            "issuer": settings.auth_issuer,
            "audio_bucket": settings.s3_audio_bucket,
            "job_reaper": settings.job_reaper_enabled,
        },
    )
    try:
        yield
    finally:
        reaper_stop.set()
        if reaper_task is not None:
            reaper_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await reaper_task
        await teardown_state(state)
        logger.info("asr-service shutting down")


async def _object_store_not_configured(
    request: Request, exc: ObjectStoreNotConfiguredError
) -> JSONResponse:
    """The service runs without an object store when ``S3_ENDPOINT`` is
    empty, but a transcript (or audio) then cannot be fetched or stored.
    Say so with a 503 and a machine-readable code instead of the 500
    "An unexpected error occurred" that hid the cause (request
    39BEEB90-…, NOTE-2026-00016). The stored transcript is not gone —
    that is the 410 — the service just has nowhere to read it from."""
    logger.warning(
        "object_store_not_configured",
        extra={"path": str(request.url.path), "method": request.method},
    )
    http_exc = HTTPException(status_code=503, detail=str(exc))
    http_exc.problem_extras = {  # type: ignore[attr-defined]
        "type_uri": "urn:mdx:storage:not-configured",
        "code": "object_store_not_configured",
    }
    return await http_exception_handler(request, http_exc)


def create_app() -> FastAPI:
    app = FastAPI(
        title="ASR Service",
        description="Batch ASR orchestrator (upload, queue, fetch).",
        version="0.3.0",
        openapi_version="3.1.0",
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.add_exception_handler(ObjectStoreNotConfiguredError, _object_store_not_configured)  # type: ignore[arg-type]
    # CORS for the SPA. allow_credentials=True is required so the browser sends
    # the HttpOnly `mdx_rt` cookie on cross-origin XHR; that forbids a wildcard
    # origin, so origins are an explicit allow-list (mirror auth-service A3).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["WWW-Authenticate"],
        max_age=600,
    )
    app.include_router(health.router)
    app.include_router(jobs.router)
    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
