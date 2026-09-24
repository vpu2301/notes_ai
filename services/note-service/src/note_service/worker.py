"""``python -m note_service.worker`` — the process that writes notes.

Same code and same image as note-service, different container. It is not
a new service (CTO rules §5): it shares the domain, the repositories and
the config. What it does not share is the API's failure and compute
profile — a generation is minutes of model calls and a lot of memory,
and running that on the request loop would tie a browser to it and let
one slow meeting starve every other note operation.

Everything it needs is already in the stack: `libs/jobs` for the queue
(leases, heartbeats, `waiting_on_model` for a backend that scales from
zero, and the usage ledger) and `libs/models` for the provider. This is
the queue's first consumer.
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
# A generation is minutes of model calls; the lease has to outlive a
# window that is merely slow, or the job is re-delivered while it runs.
LEASE_SECONDS = 120
# What "cold" costs on a backend that scales from zero — the runner uses
# it to decide between waiting and failing.
COLD_START_SECONDS = 180
# Two concurrent generations per replica: a generation is mostly waiting
# on the model, and the provider's own `max_concurrency` is the real cap.
BATCH = 2


class _Providers:
    """One chat provider per resolved backend, built on first use.

    Mirrors `domain/ask.py`: a dev Mac with no model server must still
    start the worker, and only a job that actually needs the model pays
    for finding out that it is missing.
    """

    def __init__(self, settings_source: Any = None) -> None:
        self._registry: Registry | None = None
        self._cache: dict[str, Any] = {}
        self._shadow_cache: dict[str, Any] = {}
        # Sprint 37: what the workspace's admin chose, and acknowledged.
        # The registry calls it synchronously once per resolve, so it
        # answers from a cache that `warm()` fills before each job.
        self._settings = settings_source

    def _resolve(self, workspace_id: str) -> Any:
        if self._registry is None:
            # `validate=False` for the same reason `ask.py` uses it: an
            # unrelated (ASR) misconfiguration must not stop notes being
            # written.
            self._registry = Registry.load(
                settings.models_config,
                env=settings.registry_env(),
                environ=settings.registry_environ(),
                validate=False,
                settings_source=(self._settings.cached if self._settings is not None else None),
            )
        return self._registry.resolve(workspace_id, "summarize")

    async def shadow(self, workspace_id: str) -> Any:
        """The candidate backend for this workspace, or None.

        Two gates, and the second is the important one: a shadow run
        processes a real meeting on a second company's hardware, so a
        workspace only shadows onto a processor its admin has already
        acknowledged. A candidate nobody agreed to is simply not
        rehearsed there — the flip waits for the acknowledgement.
        """
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
            # The metric labels the run by backend; the provider is the
            # only thing that knows which one it is.
            with contextlib.suppress(AttributeError):
                provider.backend_name = resolved.name
            self._shadow_cache[resolved.name] = provider
            logger.info("note_worker.shadow_provider_ready", extra=resolved.log_fields())
        return provider

    async def warm(self, tenant_id: UUID) -> None:
        """Read this workspace's settings before anything resolves.

        Called from the probe hook, which the runner awaits before the
        handler — so a tier chosen a second ago is the tier this job
        runs on, not the one cached from the previous job.
        """
        if self._settings is not None:
            await self._settings.refresh(tenant_id)

    async def get(self, workspace_id: str) -> Any:
        resolved = self._resolve(workspace_id)
        provider = self._cache.get(resolved.name)
        if provider is None:
            provider = build_chat_provider(resolved)
            self._cache[resolved.name] = provider
            logger.info("note_worker.provider_ready", extra=resolved.log_fields())
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
    # The worker shares the API's state builder rather than keeping a
    # second copy of the pool, envelope and object-store wiring in step.
    from .main_deps import build_state, teardown_state

    state = await build_state()
    app_pool = state.app_pool
    jobs_pool = state.app_pool
    transcripts = state.transcripts_store

    providers = _Providers(state.workspace_model_settings)
    deps = GenerationDeps(
        app_pool=app_pool,
        transcripts_store=transcripts,
        provider_for=providers.get,
        shadow_provider_for=providers.shadow,
        entity_model_tier=settings.note_entity_model_tier,
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
        # The probe above fails before `_run` starts, so without this a
        # dead job leaves its generation `queued` forever.
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
        # Two at a time, and never two from the same workspace when
        # somebody else is waiting (migration 0055). A workspace that
        # uploads fifty recordings gets them written — interleaved with
        # everyone else's, not in front of them.
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
