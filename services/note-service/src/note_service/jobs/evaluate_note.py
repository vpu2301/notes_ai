"""The ``note.evaluate`` job: one experiment's runs, one at a time, into the
experiment's own tables and the object store.

The same pipeline a generation runs, with a different sink: nothing here calls the
note writer, stores items, names a note, notifies anybody or touches a calendar.
Every run reads the experiment's own fixed snapshot of its source, with the
configuration pinned when the experiment was queued. Runs go one by one (bounded
provider calls); cancellation is checked before each, so an in-flight run may finish
and its usage is still counted. Usage is accounted per run, failed runs included.
"""

from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from db import tenant_connection

from ..domain import experiments
from ..domain import prompt_profiles as profiles
from ..domain.meeting_doc import doclint, pipeline, types, windows
from ..domain.meeting_doc.stage_provider import Metered, StageProvider

logger = logging.getLogger(__name__)


class EvaluationDeps:
    """What the job needs; tests fill it with fakes. ``provider_named(name)`` builds a
    registered backend by name (the pinned binding); ``provider_for(tenant)`` is the
    workspace's routed writer, used for a stage with no binding. ``costs`` is the
    cost table (``jobs.costs.CostTable``) or None (cost unknown)."""

    def __init__(
        self,
        *,
        app_pool: Any,
        transcripts_store: Any,
        provider_for: Any,
        provider_named: Any = None,
        costs: Any = None,
    ) -> None:
        self.app_pool = app_pool
        self.transcripts_store = transcripts_store
        self.provider_for = provider_for
        self.provider_named = provider_named
        self.costs = costs


async def handle_evaluate(deps: EvaluationDeps, *, tenant_id: UUID, payload: dict) -> dict:
    """Run what is pending of one experiment. Returns counts only."""
    experiment_id = UUID(str(payload["experiment_id"]))
    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        experiment = await experiments.fetch(conn, experiment_id=experiment_id)
        if experiment is None or experiment.state in experiments.FINAL:
            return {"skipped": "not_active"}
        await experiments.set_state(
            conn, experiment_id=experiment_id, state="running", only_from=experiments.ACTIVE
        )
        planned = await experiments.runs(conn, experiment_id=experiment_id)

    sources: dict[int, dict[str, Any]] = {}
    done = failed = 0
    for run in [r for r in planned if r.state == "pending"]:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            current = await experiments.fetch(conn, experiment_id=experiment_id)
            if current is None or current.state == "cancelled":
                await experiments.cancel_pending(
                    conn, experiment_id=experiment_id, error_kind="cancelled"
                )
                break
            over = current.tokens_used >= current.token_cap or (
                current.cost_known and current.spent_cents >= current.budget_cap_cents
            )
            if over:
                await experiments.cancel_pending(
                    conn, experiment_id=experiment_id, error_kind="budget_exhausted"
                )
                break
            await experiments.start_run(conn, run_id=run.id)

        started = time.monotonic()
        meters: list[Metered] = []
        artifact: str | None = None
        error: str | None = None
        metrics: dict[str, Any] = {}
        try:
            if run.source_index not in sources:
                sources[run.source_index] = await _source(
                    deps, tenant_id, current, run.source_index
                )
            produced = await _run_one(
                deps, tenant_id, current, run, sources[run.source_index], meters
            )
            artifact = experiments.artifact_key(tenant_id, experiment_id, run.id)
            await deps.transcripts_store.put(
                key=artifact,
                plaintext=json.dumps(produced["artifact"]).encode("utf-8"),
                tenant_id=tenant_id,
                aad=run.id.bytes,
            )
            metrics = produced["metrics"]
            done += 1
        except Exception as exc:  # noqa: BLE001 — a failed run is a result, not a crash
            logger.warning("note_evaluate.run_failed", extra={"run": str(run.id)}, exc_info=True)
            error = str(getattr(exc, "kind", None) or type(exc).__name__)[:60]
            failed += 1
        calls = [c for m in meters for c in m.calls]
        tokens = sum(c.get("input_tokens", 0) + c.get("output_tokens", 0) for c in calls)
        cents = _cost(deps.costs, calls)
        metrics = {**metrics, "calls": per_model(calls), "tokens": tokens}
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            await experiments.finish_run(
                conn,
                experiment_id=experiment_id,
                run_id=run.id,
                state="failed" if error else "done",
                artifact_key=artifact,
                metrics=metrics,
                error_kind=error,
                cost_cents=cents,
                tokens=tokens,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        final = await experiments.runs(conn, experiment_id=experiment_id)
        states = {r.state for r in final}
        outcome = (
            "completed"
            if states == {"done"}
            else "failed"
            if "done" not in states and "cancelled" not in states
            else "partial"
        )
        current = await experiments.fetch(conn, experiment_id=experiment_id)
        if current is not None and current.state != "cancelled":
            await experiments.set_state(
                conn, experiment_id=experiment_id, state=outcome, only_from=experiments.ACTIVE
            )
    return {"runs_done": done, "runs_failed": failed}


async def _source(
    deps: EvaluationDeps, tenant_id: UUID, experiment: Any, index: int
) -> dict[str, Any]:
    """The experiment's own frozen copy of one source (sealed with the experiment id)."""
    raw = await deps.transcripts_store.get(
        key=experiments.source_key(tenant_id, experiment.id, index),
        tenant_id=tenant_id,
        aad=experiment.id.bytes,
    )
    return json.loads(raw)


async def _provider(deps: EvaluationDeps, tenant_id: UUID, binding: dict[str, Any] | None) -> Any:
    name = (binding or {}).get("backend")
    if name and deps.provider_named is not None:
        return await deps.provider_named(name)
    return await deps.provider_for(str(tenant_id))


async def _run_one(
    deps: EvaluationDeps,
    tenant_id: UUID,
    experiment: Any,
    run: Any,
    source: dict[str, Any],
    meters: list[Metered],
) -> dict[str, Any]:
    """One candidate on one source: the engine and its linter, nothing written."""
    snap = run.config_snapshot
    config = profiles.ProfileConfig.model_validate(snap.get("config") or {})
    result = source["result"]
    if experiment.output_language == "auto":
        language, _ = pipeline.resolve_output_language(result)
    else:
        language = experiment.output_language
    staged: dict[str, Any] = {}
    for stage in profiles.STAGES:
        inner = await _provider(deps, tenant_id, (snap.get("models") or {}).get(stage))
        params = config.params.get(stage) or profiles.StageParams()
        meter = Metered(
            StageProvider(
                inner,
                stage=stage,
                temperature=params.temperature,
                max_output_tokens=params.max_output_tokens,
                timeout_s=params.timeout_s,
            ),
            stage=stage,
        )
        meters.append(meter)
        staged[stage] = meter

    from .generate_note import _recording_type

    turns = windows.prepare_turns(windows.turns_from_result(result)).turns
    extractor = staged["extraction"]
    built = windows.build_windows(
        turns, max_chars=windows.window_chars(getattr(extractor, "context_window", None))
    )
    family_code = source.get("template_family")
    recording_type, recording_source = await _recording_type(
        extractor,
        meeting=SimpleNamespace(
            meeting_type=source.get("meeting_type") or "auto", calendar_context={}
        ),
        template_family=types.family_for_template(family_code),
        built=built,
        turns=turns,
        language=language,
    )
    document = await pipeline.run(
        result,
        provider=extractor,
        role_by_key=dict(source.get("role_by_key") or {}),
        output_language=language,
        family=types.family_for_recording_type(recording_type),
        built=built,
        recording_type=recording_type,
        recording_type_source=recording_source,
        multilingual=bool(snap.get("multilingual", True)),
        fidelity=bool(snap.get("fidelity", True)),
        instructions=profiles.stage_overrides(config),
        stage_providers=staged,
        length=experiment.length,
    )
    document = await doclint.enforce(document, regenerate=document.regenerator)
    return {"artifact": artifact_of(document, language), "metrics": metrics_of(document)}


def artifact_of(document: Any, language: str) -> dict[str, Any]:
    """The produced note for side-by-side review: lines with their citations, and each
    cited fact's original quote, its language and time range (never a translation
    presented as a quote). Stored encrypted under the experiment, read under the
    source's access rules."""
    return {
        "language": language,
        "sections": [
            {
                "section_key": s.section_key,
                "title": s.title,
                "lines": [
                    {"kind": ln.kind, "text": ln.text, "fact_ids": list(ln.fact_ids)}
                    for ln in s.lines
                ],
            }
            for s in document.sections
        ],
        "facts": [
            {
                "item_key": f.item_key,
                "kind": f.kind,
                "text": f.text,
                "quote": f.quote,
                "source_language": f.source_language,
                "start_ms": f.start_ms,
                "end_ms": f.end_ms,
                "speaker_label": f.speaker_label,
                "attributed_to": f.attributed_to,
                "flags": list(f.flags),
            }
            for f in document.facts
        ],
    }


# Stage counts and outcomes a comparison shows; never text.
_METRIC_KEYS = (
    "prompt_version",
    "fidelity",
    "multilingual_evidence",
    "output_language",
    "length",
    "languages",
    "meaning_check",
    "meaning_unverified",
    "merge",
    "incomplete",
    "summary_fallback",
    "topics_fallback",
    "facts_after_merge",
    "lines_total",
    "excluded_language_ms",
    "coverage_gaps",
)


def metrics_of(document: Any) -> dict[str, Any]:
    stats = document.stats or {}
    return {
        **{k: stats.get(k) for k in _METRIC_KEYS},
        "windows_failed": document.windows_failed,
        "partial": document.partial,
    }


def per_model(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calls grouped by stage, backend and model: what actually answered."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for c in calls:
        key = (str(c.get("stage")), str(c.get("backend")), str(c.get("model_id")))
        g = grouped.setdefault(
            key,
            {"stage": key[0], "backend": key[1], "model_id": key[2], "calls": 0, "failed": 0,
             "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
        )  # fmt: skip
        g["calls"] += 1
        g["failed"] += 0 if c.get("ok") else 1
        g["input_tokens"] += c.get("input_tokens", 0)
        g["output_tokens"] += c.get("output_tokens", 0)
        g["latency_ms"] += c.get("latency_ms", 0)
    return list(grouped.values())


def _cost(costs: Any, calls: list[dict[str, Any]]) -> float | None:
    """Cents from the cost table; None (unknown) when any backend is unpriced."""
    if costs is None:
        return None
    from models import UsageRecord

    cents = 0.0
    for c in calls:
        backend = str(c.get("backend") or "")
        if not costs.is_priced(backend):
            return None
        cents += costs.estimate_cents(
            UsageRecord(
                backend=backend,
                model_id=str(c.get("model_id") or ""),
                operation="chat.complete",
                ok=bool(c.get("ok")),
                latency_ms=int(c.get("latency_ms", 0)),
                input_tokens=int(c.get("input_tokens", 0)),
                output_tokens=int(c.get("output_tokens", 0)),
            )
        )
    return round(cents, 4)
