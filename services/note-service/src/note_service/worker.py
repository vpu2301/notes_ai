"""``python -m note_service.worker``: the process that writes notes.

Same code and image as note-service, different container: a generation is
minutes of model calls and must not run on the request loop. Queue from
`libs/jobs`, provider from `libs/models`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import Any
from uuid import UUID

from jobs import CostTable, HandlerSpec, JobContext, JobQueue, JobRunner, UsageLedger
from models import Registry, build_chat_provider
from observability import bootstrap

from .collaboration_metrics import rehome_total
from .config import settings
from .domain.note_move import REHOME_JOB_KIND
from .jobs.generate_note import GenerationDeps, handle_generate, mark_dead
from .jobs.rehome_media import handle_rehome, mark_failed

logger = logging.getLogger(__name__)

JOB_KIND = "note.generate"
# The lease must outlive a merely slow call, or the job is re-delivered while it runs.
LEASE_SECONDS = 120
# Cold start on a backend that scales from zero; the runner decides between waiting and failing.
COLD_START_SECONDS = 180
# Mostly waiting on the model; the provider's `max_concurrency` is the real cap.
BATCH = 2
# The one chat operation a generation makes.
WRITE_OPERATION = "write"


class _Providers:
    """One chat provider per resolved backend, built on first use (a Mac without a
    model server must still start the worker)."""

    def __init__(self, settings_source: Any = None, registry: Registry | None = None) -> None:
        # The process's one registry, built and probed by `build_state()`.
        self._registry: Registry | None = registry
        self._cache: dict[str, Any] = {}
        # Called synchronously by the registry, so it answers from a cache `warm()` fills per job.
        self._settings = settings_source

    def _load(self) -> Registry:
        if self._registry is None:
            from .domain.model_routing import load_registry

            # `validate=False`: an unrelated (ASR) misconfiguration must not stop notes.
            self._registry = load_registry(self._settings)
        return self._registry

    def _resolve(self, workspace_id: str) -> Any:
        return self._load().resolve(workspace_id, WRITE_OPERATION)

    async def warm(self, tenant_id: UUID) -> None:
        """Read this workspace's settings before anything resolves (probe hook, before the handler)."""
        if self._settings is not None:
            await self._settings.refresh(tenant_id)

    async def get(self, workspace_id: str) -> Any:
        """The workspace's writer; one instance per backend name."""
        resolved = self._resolve(workspace_id)
        provider = self._cache.get(resolved.name)
        if provider is None:
            provider = build_chat_provider(resolved)
            # The metric labels the run by backend.
            with contextlib.suppress(AttributeError):
                provider.backend_name = resolved.name
            self._cache[resolved.name] = provider
            logger.info("note_worker.provider_ready", extra=resolved.log_fields())
        return provider

    def fallbacks(self) -> list[dict[str, Any]]:
        """Env overrides this process resolved to their fallback, and why (provenance)."""
        return [o.log_fields() for o in self._load().active_overrides() if o.is_fallback]

    def backend_of(self, workspace_id: str) -> tuple[str, int]:
        return self._resolve(workspace_id).name, COLD_START_SECONDS

    async def probe(self, workspace_id: str) -> None:
        await (await self.get(workspace_id)).probe()

    async def aclose(self) -> None:
        for provider in self._cache.values():
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                logger.debug("note_worker.provider_close_failed", exc_info=True)
        self._cache.clear()


async def run() -> None:
    bootstrap(
        f"{settings.service_name}-worker",
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        log_level=settings.log_level,
        deployment_environment=settings.environment,
        package_name="note-service",
        disable_otel=settings.testing or settings.otel_sdk_disabled,
    )
    # Shares the API's state builder rather than a second copy of the wiring.
    from .main_deps import build_state, teardown_state

    state = await build_state()
    app_pool = state.app_pool
    jobs_pool = state.app_pool
    transcripts = state.transcripts_store

    providers = _Providers(
        state.workspace_model_settings, registry=getattr(state, "model_registry", None)
    )
    deps = GenerationDeps(
        app_pool=app_pool,
        transcripts_store=transcripts,
        provider_for=providers.get,
        build_sha=settings.build_sha,
        fallbacks=providers.fallbacks,
        note_instructions=settings.note_instructions_enabled,
        check_enabled=settings.note_check_enabled,
        # N0: the row the probe hook refreshed before this run (style, model parameters).
        settings_row=state.workspace_model_settings.row
        if state.workspace_model_settings is not None
        else None,
    )

    async def _run(ctx: JobContext) -> dict[str, Any] | None:
        return await handle_generate(
            deps, tenant_id=UUID(str(ctx.job.tenant_id)), payload=dict(ctx.job.payload)
        )

    def _backend(ctx: JobContext) -> tuple[str, int]:
        return providers.backend_of(str(ctx.job.tenant_id))

    async def _probe(ctx: JobContext) -> None:
        await providers.warm(UUID(str(ctx.job.tenant_id)))
        await providers.probe(str(ctx.job.tenant_id))

    async def _on_dead(ctx: JobContext, error_kind: str) -> None:
        # The probe fails before `_run` starts; without this a dead job stays `queued` forever.
        await mark_dead(
            deps,
            tenant_id=UUID(str(ctx.job.tenant_id)),
            payload=dict(ctx.job.payload),
            error_kind=error_kind,
        )

    # W5: a moved note's audio and transcripts, re-encrypted into the workspace it moved to.
    stores = {"audio": state.audio_store, "transcripts": transcripts}

    async def _rehome(ctx: JobContext) -> dict[str, Any] | None:
        try:
            return await handle_rehome(
                app_pool=app_pool,
                stores=stores,
                audit_writer=state.audit_writer,
                tenant_id=UUID(str(ctx.job.tenant_id)),
                payload=dict(ctx.job.payload),
                enqueued_at=ctx.job.created_at,
            )
        except Exception:
            rehome_total.add(1, {"result": "retry"})
            raise

    async def _rehome_dead(ctx: JobContext, error_kind: str) -> None:
        await mark_failed(
            app_pool=app_pool,
            audit_writer=state.audit_writer,
            tenant_id=UUID(str(ctx.job.tenant_id)),
            payload=dict(ctx.job.payload),
            error_kind=error_kind,
        )

    queue = JobQueue(jobs_pool)
    runner = JobRunner(
        queue,
        {
            JOB_KIND: HandlerSpec(run=_run, backend=_backend, probe=_probe, on_dead=_on_dead),
            REHOME_JOB_KIND: HandlerSpec(run=_rehome, on_dead=_rehome_dead),
        },
        worker_id=settings.registry_environ().get("HOSTNAME") or "note-worker",
        ledger=UsageLedger(CostTable.load(settings.models_config)),
        lease_seconds=LEASE_SECONDS,
        # Never two from the same workspace when somebody else is waiting (fair claim).
        batch=BATCH,
        per_tenant=settings.note_generation_per_tenant,
    )

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stopping.set)

    logger.info("note_worker.started", extra={"env": settings.environment})
    task = asyncio.create_task(runner.run_forever(), name="note-worker")
    try:
        await stopping.wait()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await providers.aclose()
        await teardown_state(state)
        logger.info("note_worker.stopped")


def main() -> None:  # pragma: no cover — process entry point
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
