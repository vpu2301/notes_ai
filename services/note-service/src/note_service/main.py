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
from .middleware import AnonymousCorsMiddleware, RequestIDMiddleware
from .routers import (
    ai_settings,
    audio_clips,
    billing,
    calendar,
    glossary,
    health,
    notes,
    notes_ask,
    notes_audio,
    notes_corrections,
    notes_dates,
    notes_diff,
    notes_drafts,
    notes_from_transcript,
    notes_generation,
    notes_items,
    notes_lifecycle,
    notes_meeting,
    notes_pdf,
    notes_search,
    notes_series,
    notes_sharing,
    notes_versions,
    search_tips,
    shared_public,
    sharing_stats,
    spaces,
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
    # In-process scheduler (ADR-0041); the jobs are idempotent and also run as CLIs.
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

        # Captures whose client never came back stop claiming to be recording.
        from .jobs import meeting_state_sweeper

        async def _meeting_sweep_iteration() -> dict[str, int]:
            return await meeting_state_sweeper.run_for_all_tenants(
                app_pool=state.app_pool,
                audit_writer=state.audit_writer,
                stale_hours=settings.meeting_stale_hours,
            )

        jobs.append(
            asyncio.create_task(
                run_periodic(
                    job_name="meeting_state_sweeper",
                    interval_seconds=settings.background_jobs_interval_s,
                    fn=_meeting_sweep_iteration,
                ),
                name="meeting-state-sweeper",
            )
        )
        # Transcript snapshots whose worker died before deleting its own.
        from .jobs import snapshot_sweeper

        async def _snapshot_sweep_iteration() -> dict[str, int]:
            return await snapshot_sweeper.run_for_all_tenants(
                app_pool=state.app_pool,
                store=state.transcripts_store,
                audit_writer=state.audit_writer,
                stale_hours=settings.generation_snapshot_hours,
            )

        jobs.append(
            asyncio.create_task(
                run_periodic(
                    job_name="snapshot_sweeper",
                    interval_seconds=settings.background_jobs_interval_s,
                    fn=_snapshot_sweep_iteration,
                ),
                name="snapshot-sweeper",
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
    # allow_credentials=True (HttpOnly cookie) forbids a wildcard origin: explicit allow-list.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["WWW-Authenticate"],
        max_age=600,
    )
    # The anonymous shared surface is world-readable; added last so it sees preflights first.
    app.add_middleware(AnonymousCorsMiddleware)
    app.include_router(health.router)
    app.include_router(templates.router)
    # Literal paths (/search, /from-transcript, /meeting, …) must be registered
    # BEFORE notes.router's /{note_id} catch-all.
    app.include_router(notes_search.router)
    app.include_router(notes_from_transcript.router)
    app.include_router(notes_meeting.router)
    app.include_router(notes_corrections.router)
    app.include_router(notes_series.router)
    app.include_router(notes_generation.router)
    app.include_router(notes_dates.router)
    app.include_router(notes.router)
    app.include_router(notes_drafts.router)
    app.include_router(notes_lifecycle.router)
    app.include_router(notes_diff.router)
    app.include_router(notes_versions.router)
    app.include_router(notes_pdf.router)
    app.include_router(notes_sharing.router)
    app.include_router(notes_items.router)
    app.include_router(notes_ask.router)
    # Anonymous, token-addressed reads: no auth dependency at all.
    app.include_router(shared_public.router)
    app.include_router(sharing_stats.router)
    app.include_router(notes_audio.router)
    app.include_router(audio_clips.router)
    app.include_router(search_tips.router)
    app.include_router(synonyms.router)
    app.include_router(calendar.router)
    app.include_router(spaces.router)
    app.include_router(glossary.router)
    app.include_router(ai_settings.router)
    app.include_router(billing.router)
    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
