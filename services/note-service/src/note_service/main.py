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
    calendar,
    glossary,
    health,
    notes,
    notes_ask,
    notes_audio,
    notes_corrections,
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

        # Sprint 34: captures whose client never came back (a crashed tab,
        # a killed app) stop claiming to be recording. Nothing is deleted.
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
        # Sprint 37: transcript snapshots whose worker was killed before
        # it could delete its own. Nothing older than a day survives.
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
    # Sprint 23: the anonymous shared surface is world-readable by design.
    # Added last, so it is the outermost layer and sees preflights first.
    app.add_middleware(AnonymousCorsMiddleware)
    app.include_router(health.router)
    app.include_router(templates.router)
    # Search route must be registered BEFORE the parameterised ``{note_id}``
    # routes so ``/v1/notes/search`` matches the search handler rather than
    # ``GET /v1/notes/{note_id}``.
    app.include_router(notes_search.router)
    # BEFORE notes.router: their literal paths (/from-transcript,
    # /by-source-job, /meeting) must win over notes' /{note_id} catch-all.
    app.include_router(notes_from_transcript.router)
    # Sprint 34: the note is created at record start (ADR-0055).
    app.include_router(notes_meeting.router)
    # Sprint 35: dismiss / restore / fix a line's owner or date. Before
    # notes.router for the same reason — literal segments first.
    app.include_router(notes_corrections.router)
    # Sprint 36: what is still open from last time, and the client version.
    app.include_router(notes_series.router)
    # Sprint 33: how the writing is going, and the facts behind it.
    app.include_router(notes_generation.router)
    app.include_router(notes.router)
    app.include_router(notes_drafts.router)
    app.include_router(notes_lifecycle.router)
    app.include_router(notes_diff.router)
    app.include_router(notes_versions.router)
    app.include_router(notes_pdf.router)
    app.include_router(notes_sharing.router)
    # Sprint 20: action items + recipient responses, author side.
    app.include_router(notes_items.router)
    # "Ask this note" — a question over the note and its transcript.
    app.include_router(notes_ask.router)
    # Anonymous, token-addressed reads — no auth dependency at all.
    app.include_router(shared_public.router)
    # Sprint 22: workspace-level sharing stats for admins (counts only).
    app.include_router(sharing_stats.router)
    # Sprint 15: audio replay (ADR-0037). No ordering hazard: the
    # multi-segment sections path can't be swallowed by /{note_id}.
    app.include_router(notes_audio.router)
    app.include_router(audio_clips.router)
    # Sprint 15: query expansion surfaces (ADR-0038).
    app.include_router(search_tips.router)
    app.include_router(synonyms.router)
    # 0019: calendar connections + the "Coming up" events read.
    app.include_router(calendar.router)
    # 0021: spaces — personal note folders shared across devices.
    app.include_router(spaces.router)
    # Sprint 35: the workspace glossary that feeds the vocabulary hint.
    app.include_router(glossary.router)
    # Sprint 37: who processes this workspace's meetings (ADR-0046 d.12).
    app.include_router(ai_settings.router)
    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
