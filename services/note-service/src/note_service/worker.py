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

from .config import settings
from .jobs.generate_note import GenerationDeps, handle_generate, mark_dead

logger = logging.getLogger(__name__)

JOB_KIND = "note.generate"
# The lease must outlive a merely slow window, or the job is re-delivered while it runs.
LEASE_SECONDS = 120
# Cold start on a backend that scales from zero; the runner decides between waiting and failing.
COLD_START_SECONDS = 180
# Mostly waiting on the model; the provider's `max_concurrency` is the real cap.
BATCH = 2


class _Providers:
    """One chat provider per resolved backend, built on first use (a Mac without a
    model server must still start the worker)."""

    def __init__(self, settings_source: Any = None, registry: Registry | None = None) -> None:
        # The process's one registry, built and probed by `build_state()`.
        self._registry: Registry | None = registry
        self._cache: dict[str, Any] = {}
        self._shadow_cache: dict[str, Any] = {}
        # Called synchronously by the registry, so it answers from a cache `warm()` fills per job.
        self._settings = settings_source

    def _resolve(self, workspace_id: str, operation: str = "summarize") -> Any:
        if self._registry is None:
            from .domain.model_routing import load_registry

            # `validate=False`: an unrelated (ASR) misconfiguration must not stop notes.
            self._registry = load_registry(self._settings)
        return self._registry.resolve(workspace_id, operation)

    async def shadow(self, workspace_id: str) -> Any:
        """The candidate backend for this workspace, or None: a workspace only shadows
        onto a processor its admin has acknowledged (real meetings on other hardware)."""
        name = settings.note_generation_shadow_backend
        if not name:
            return None
        try:
            self._resolve(workspace_id)  # ensures the registry is loaded
            assert self._registry is not None  # noqa: S101 — just loaded above
            resolved = self._registry.backend(name, expect_kind="chat")
        except Exception:  # noqa: BLE001
            logger.warning("note_worker.shadow_backend_unknown", extra={"backend": name})
            return None

        processor = resolved.processor
        if processor is not None and self._settings is not None:
            agreed = self._settings.acknowledged(UUID(workspace_id))
            if (
                processor.name.strip().casefold(),
                processor.region.strip().casefold(),
            ) not in agreed:
                return None

        provider = self._shadow_cache.get(resolved.name)
        if provider is None:
            provider = build_chat_provider(resolved)
            # The metric labels the run by backend.
            with contextlib.suppress(AttributeError):
                provider.backend_name = resolved.name
            self._shadow_cache[resolved.name] = provider
            logger.info("note_worker.shadow_provider_ready", extra=resolved.log_fields())
        return provider

    async def warm(self, tenant_id: UUID) -> None:
        """Read this workspace's settings before anything resolves (probe hook, before the handler)."""
        if self._settings is not None:
            await self._settings.refresh(tenant_id)

    async def get(self, workspace_id: str, operation: str = "summarize") -> Any:
        """The provider for one operation; one instance per backend name."""
        resolved = self._resolve(workspace_id, operation)
        provider = self._cache.get(resolved.name)
        if provider is None:
            provider = build_chat_provider(resolved)
            self._cache[resolved.name] = provider
            logger.info(
                "note_worker.provider_ready",
                extra={"operation": operation, **resolved.log_fields()},
            )
        return provider

    def backend_of(self, workspace_id: str) -> tuple[str, int]:
        return self._resolve(workspace_id).name, COLD_START_SECONDS

    async def probe(self, workspace_id: str) -> None:
        await (await self.get(workspace_id)).probe()

    async def aclose(self) -> None:
        for provider in (*self._cache.values(), *self._shadow_cache.values()):
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                logger.debug("note_worker.provider_close_failed", exc_info=True)
        self._cache.clear()
        self._shadow_cache.clear()


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
        # classify/title/entities resolve on their own routing row.
        operation_provider_for=providers.get,
        shadow_provider_for=providers.shadow,
        entity_model_tier=settings.note_entity_model_tier,
        coverage_retry_budget_s_per_hour=settings.note_coverage_retry_budget_s_per_hour,
        shadow_percent=(
            settings.note_generation_shadow_percent
            if settings.note_generation_shadow_backend
            else 0
        ),
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

    queue = JobQueue(jobs_pool)
    runner = JobRunner(
        queue,
        {JOB_KIND: HandlerSpec(run=_run, backend=_backend, probe=_probe, on_dead=_on_dead)},
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
