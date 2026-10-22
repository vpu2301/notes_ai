"""Run lifecycle: ``start_run`` (submission) → ``begin_run`` (worker) → ``finish_run``.

Every function is fail-open: telemetry errors are counted and logged by the store, never raised."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from . import accum, context, metrics, overhead, runtime, store
from .ids import new_run_id
from .schema import Device, ErrorCategory, ProcessingRun, Reason, RunStatus
from .spans import open_model_activity
from .timing import critical_path_seconds, derive_status, ratios

logger = logging.getLogger("telemetry.runs")

# Measurements a run cannot have at submission; each starts as null + reason.
_PENDING: dict[str, Reason] = {
    "processing_wall_seconds": "not_measured",
    "rtf": "not_measured",
    "speedup": "not_measured",
    "asr_audio_processed_seconds": "not_measured",
    "telemetry_overhead_seconds": "not_measured",
    "telemetry_buffer_peak_bytes": "not_measured",
    # Client-derived; client events arrive in Sprint 3.
    "user_wait_seconds": "not_measured",
    "time_to_transcript_seconds": "not_measured",
    "time_to_speaker_labels_seconds": "not_measured",
    "time_to_notes_seconds": "not_measured",
}


@dataclass
class Settings:
    enabled: bool = True
    retention_days: int = 90
    app_commit: str | None = None
    app_build: str | None = None


_settings = Settings()


def configure(
    pool: Any | None,
    *,
    enabled: bool = True,
    retention_days: int = 90,
    app_commit: str | None = None,
    app_build: str | None = None,
    flush_interval_seconds: float = 1.0,
) -> None:
    """Install the process-wide store; ``pool=None`` → writes are no-ops; ``enabled=False`` →
    only the run row is written."""
    global _settings
    _settings = Settings(enabled, retention_days, app_commit, app_build)
    # Off still keeps the processing_run row (its status and wall time), so a run with
    # telemetry off can be compared with one with it on; everything else is a no-op.
    store.configure(
        store.TelemetryStore(
            pool, flush_interval_seconds=flush_interval_seconds, row_only=not enabled
        )
        if pool is not None
        else None
    )


def settings() -> Settings:
    return _settings


async def start_run(
    *,
    tenant_id: UUID,
    recording_id: UUID,
    kind: str = "initial",
    trigger: str = "user",
    created_by: UUID | None = None,
    reprocess_scope: str | None = None,
    audio_duration_seconds: float | None = None,
    submitted_at: datetime | None = None,
    run_id: UUID | None = None,
) -> context.RunRef | None:
    """Mint a run at submission and write it ``queued``."""
    # An explicit id makes minting idempotent (the INSERT ignores a second one).
    run_id = run_id or new_run_id()
    try:
        with overhead.measure(run_id):
            now = submitted_at or store.utcnow()
            reasons: dict[str, Reason] = dict(_PENDING)
            if audio_duration_seconds is None:
                reasons["audio_duration_seconds"] = "unavailable"
            # Counted by the INSERT itself (telemetry_open_runs()); the reason is dropped there.
            reasons["concurrent_runs_at_start"] = "unavailable"
            run = ProcessingRun(
                processing_run_id=run_id,
                tenant_id=tenant_id,
                recording_id=recording_id,
                kind=kind,  # type: ignore[arg-type]
                reprocess_scope=reprocess_scope,  # type: ignore[arg-type]
                trigger=trigger,  # type: ignore[arg-type]
                status="queued",
                submitted_at=now,
                audio_duration_seconds=audio_duration_seconds,
                created_by=created_by,
                retention_until=now + timedelta(days=_settings.retention_days),
                trace_id=context.current_trace_id(),
                null_reasons=reasons,
            )
        await store.get().insert_run(run)
    except Exception:  # noqa: BLE001 — fail-open
        logger.debug("telemetry.start_run_failed", exc_info=True)
        metrics.write_errors_total.add(1, {"entity": "run"})
    return context.RunRef(
        processing_run_id=run_id, tenant_id=tenant_id, recording_id=recording_id, kind=kind
    )


async def begin_run(
    run: context.RunRef,
    *,
    effective_config: dict[str, Any] | None = None,
    device_asr: Device | None = None,
    device_diarization: Device | None = None,
    device_llm: Device | None = None,
    record_context: bool = True,
) -> int:
    """The worker picked the run up: ``running``, other model activity, run context. Returns
    the run's attempt number (1 on the first pickup, +1 per queue redelivery) and makes it the
    default ``attempt`` of the spans that follow in this context; 0 when the run is already
    closed (a queue redelivery after it finished), and the run is left as it is."""
    record_context = record_context and _settings.enabled
    attempt = 1
    closed = False
    try:
        with overhead.measure(run.processing_run_id):
            activity = open_model_activity(run.processing_run_id)
            ctx = (
                runtime.collect_run_context(
                    run.processing_run_id,
                    run.tenant_id,
                    app_commit=_settings.app_commit,
                    app_build=_settings.app_build,
                    effective_config=effective_config or {},
                    device_asr=device_asr,
                    device_diarization=device_diarization,
                    device_llm=device_llm,
                )
                if record_context
                else None
            )
        got = await store.get().begin(run.tenant_id, run.processing_run_id, activity, ctx)
        closed = got == 0
        attempt = got or 1
    except Exception:  # noqa: BLE001
        logger.debug("telemetry.begin_run_failed", exc_info=True)
    context.set_attempt(attempt)
    return 0 if closed else attempt


async def finish_run(
    run: context.RunRef,
    *,
    result_stored: bool,
    stage_statuses: Iterable[tuple[str, str]] = (),
    cancelled: bool = False,
    status: RunStatus | None = None,
    error_category: ErrorCategory | None = None,
    asr_audio_processed_seconds: float | None = None,
    record_context_end: bool = True,
) -> RunStatus | None:
    """Close the run: flush its spans, derive status and the critical-path wall time."""
    run_id = run.processing_run_id
    try:
        s = store.get()
        await s.flush()
        final = status or derive_status(
            stage_statuses, result_stored=result_stored, cancelled=cancelled
        )
        submitted, audio, ends = await s.run_facts(run.tenant_id, run_id)
        with overhead.measure(run_id):
            if not ends and not _settings.enabled:
                ends = [store.utcnow()]  # telemetry off: no spans, the run ends now
            wall = critical_path_seconds(submitted, ends)
            rtf, speedup = ratios(wall, audio)
            fields: dict[str, Any] = {
                "status": final,
                "error_category": error_category if final in ("failed", "partial") else None,
                "finished_at": store.utcnow(),
                "processing_wall_seconds": wall,
                "rtf": rtf,
                "speedup": speedup,
            }
            reasons: dict[str, str] = {}
            if wall is None:
                reasons["processing_wall_seconds"] = "unavailable"
            if rtf is None:
                reasons["rtf"] = reasons["speedup"] = "unavailable"
            # A labelled sum: primary + recovery audio actually fed to ASR.
            audio_fed = asr_audio_processed_seconds
            if audio_fed is None:
                audio_fed = accum.audio_processed(run_id)
            if audio_fed is not None:
                fields["asr_audio_processed_seconds"] = round(audio_fed, 3)
            if final in ("failed", "partial") and error_category is None:
                fields["error_category"] = accum.first_error(run_id) or "unknown"
        if record_context_end and _settings.enabled:
            await s.finish_context(run.tenant_id, run_id, runtime.end_snapshot())
        # Overhead last, so it includes the writes above.
        fields["telemetry_overhead_seconds"] = round(overhead.seconds(run_id), 6)
        fields["telemetry_buffer_peak_bytes"] = overhead.peak_bytes(run_id)
        cleared = [k for k in fields if k in _PENDING or k == "audio_duration_seconds"]
        await s.update_run(run.tenant_id, run_id, fields, reasons, cleared)
        metrics.runs_total.add(1, {"kind": run.kind, "status": final})
        overhead.forget(run_id)
        accum.forget(run_id)
        return final
    except Exception:  # noqa: BLE001
        logger.debug("telemetry.finish_run_failed", exc_info=True)
        metrics.write_errors_total.add(1, {"entity": "run"})
        return None


async def extend_run(
    run: context.RunRef,
    *,
    ok: bool,
    error_category: ErrorCategory | None = None,
) -> RunStatus | None:
    """A later stage of an already-finished run (the initial run's note generation, which the
    client starts after the transcript): recompute the critical-path wall time over every span,
    and downgrade ``succeeded`` to ``partial`` when this stage failed. Never upgrades a status."""
    run_id = run.processing_run_id
    try:
        s = store.get()
        await s.flush()
        submitted, audio, ends = await s.run_facts(run.tenant_id, run_id)
        current = await s.run_status(run.tenant_id, run_id)
        with overhead.measure(run_id):
            if not ends and not _settings.enabled:
                ends = [store.utcnow()]  # telemetry off: no spans, the run ends now
            wall = critical_path_seconds(submitted, ends)
            rtf, speedup = ratios(wall, audio)
            fields: dict[str, Any] = {
                "processing_wall_seconds": wall,
                "rtf": rtf,
                "speedup": speedup,
            }
            final: RunStatus | None = current  # type: ignore[assignment]
            if not ok and current == "succeeded":
                final = "partial"
                fields.update(status="partial", error_category=error_category or "llm")
        fields["telemetry_overhead_seconds"] = round(overhead.seconds(run_id), 6)
        await s.update_run(run.tenant_id, run_id, fields, {}, [], only_open=False)
        overhead.forget(run_id)
        accum.forget(run_id)
        return final
    except Exception:  # noqa: BLE001
        logger.debug("telemetry.extend_run_failed", exc_info=True)
        return None
