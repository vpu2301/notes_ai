"""note-service entry point (templates + notes / versions / diff / search)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from observability import bootstrap, register_exception_handlers

from .config import settings
from .deps import install_state
from .main_deps import build_state, teardown_state
from .middleware import RequestIDMiddleware
from .routers import (
    audio_clips,
    calendar,
    health,
    notes,
    notes_amend,
    notes_audio,
    notes_diff,
    notes_drafts,
    notes_from_transcript,
    notes_lifecycle,
    notes_pdf,
    notes_search,
    notes_sharing,
    notes_synthesis,
    notes_versions,
    search_tips,
    shared_public,
    synonyms,
    templates,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    bootstrap(
        settings.service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        log_level=settings.log_level,
        deployment_environment=settings.environment,
        package_name="note-service",
        disable_otel=settings.testing or settings.otel_sdk_disabled,
    )
    state = await build_state()
    app.state.svc = state
    install_state(state)
    # Sprint 16: idle-draft cleanup hosted in-process (ADR-0041). Off by
    # default in dev; production flips MDX_BACKGROUND_JOBS. The job is
    # idempotent and also runs as a CLI for external cron.
    jobs: list[asyncio.Task[None]] = []
    if settings.background_jobs_enabled and not settings.testing:
        from datetime import timedelta

        from observability import run_periodic

        from .jobs import idle_draft_cleanup

        async def _idle_draft_iteration() -> dict[str, int]:
            return await idle_draft_cleanup.run_for_all_tenants(
                app_pool=state.app_pool,
                audit_writer=state.audit_writer,
                idle_for=timedelta(days=settings.idle_draft_days),
            )

        jobs.append(
            asyncio.create_task(
                run_periodic(
                    job_name="idle_draft_cleanup",
                    interval_seconds=settings.background_jobs_interval_s,
                    fn=_idle_draft_iteration,
                ),
                name="idle-draft-cleanup",
            )
        )
    logger.info(
        "note-service.started",
        extra={"service": settings.service_name, "env": settings.environment},
    )
    try:
        yield
    finally:
        for task in jobs:
            task.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        await teardown_state(state)
        logger.info("note-service.stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Note Service",
        description="Notes core: templates + notes / versions / diff / search.",
        version="0.8.0",
        openapi_version="3.1.0",
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
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
    app.include_router(templates.router)
    # Search route must be registered BEFORE the parameterised ``{note_id}``
    # routes so ``/v1/notes/search`` matches the search handler rather than
    # ``GET /v1/notes/{note_id}``.
    app.include_router(notes_search.router)
    # BEFORE notes.router: its literal paths (/from-transcript,
    # /by-source-job) must win over notes' /{note_id} catch-all.
    app.include_router(notes_from_transcript.router)
    app.include_router(notes.router)
    app.include_router(notes_drafts.router)
    app.include_router(notes_lifecycle.router)
    app.include_router(notes_amend.router)
    app.include_router(notes_diff.router)
    app.include_router(notes_versions.router)
    app.include_router(notes_pdf.router)
    app.include_router(notes_sharing.router)
    app.include_router(notes_synthesis.router)
    # Anonymous, token-addressed reads — no auth dependency at all.
    app.include_router(shared_public.router)
    # Sprint 15: audio replay (ADR-0037). No ordering hazard: the
    # multi-segment sections path can't be swallowed by /{note_id}.
    app.include_router(notes_audio.router)
    app.include_router(audio_clips.router)
    # Sprint 15: query expansion surfaces (ADR-0038).
    app.include_router(search_tips.router)
    app.include_router(synonyms.router)
    # 0019: calendar connections + the "Coming up" events read.
    app.include_router(calendar.router)
    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
