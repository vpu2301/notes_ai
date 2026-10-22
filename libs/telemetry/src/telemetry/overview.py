"""Dashboard aggregates over stored runs (telemetry sprint 4). Pure: computed from the run
records, never from Prometheus. Percentiles are nearest-rank, so they are values that occurred.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from .report import stage_shares
from .schema import RunExport

STATUSES = ("succeeded", "partial", "failed", "cancelled", "running", "queued")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _backend(spans: list[Any]) -> str | None:
    value = spans[0].attributes.get("backend") if spans else None
    return str(value) if value is not None else None


def aggregate(records: list[RunExport]) -> dict[str, Any]:
    runs = [r.processing_run for r in records]
    counts = {s: sum(1 for r in runs if r.status == s) for s in STATUSES}
    rtf = [r.rtf for r in runs if r.rtf is not None]
    wait = [r.user_wait_seconds for r in runs if r.user_wait_seconds is not None]
    overhead = [
        r.telemetry_overhead_seconds for r in runs if r.telemetry_overhead_seconds is not None
    ]
    totals: dict[str, float] = {}
    measured = 0
    for record in records:
        shares = stage_shares(record)
        if shares:
            measured += 1
        for stage, share in shares.items():
            totals[stage] = totals.get(stage, 0.0) + share
    backends: dict[tuple[str, str, str, str], int] = {}

    def use(kind: str, name: str | None, device: str | None, observation: str | None) -> None:
        if name is None and device is None:
            return
        key = (kind, name or "—", device or "—", observation or "configured")
        backends[key] = backends.get(key, 0) + 1

    for record in records:
        ctx = record.run_context
        asr = [s for s in record.spans if s.stage == "asr_primary" and s.parent_span_id not in
               {p.span_id for p in record.spans if p.stage == "asr_primary"}]  # fmt: skip
        diar = [s for s in record.spans if s.stage == "diarization_infer"]
        if asr or (ctx and ctx.device_asr):
            device = ctx.device_asr if ctx else None
            use("asr", _backend(asr),
                device.value if device else None, device.observation if device else None)  # fmt: skip
        if diar or (ctx and ctx.device_diarization):
            device = ctx.device_diarization if ctx else None
            use("diarization", _backend(diar),
                device.value if device else None, device.observation if device else None)  # fmt: skip
        for model in sorted({c.model or c.backend for c in record.llm_calls}):
            device = ctx.device_llm if ctx else None
            use("llm", model, device.value if device else None,
                device.observation if device else None)  # fmt: skip
    return {
        "runs": len(runs),
        "status_counts": counts,
        "rtf": {"p50": percentile(rtf, 0.5), "p95": percentile(rtf, 0.95), "n": len(rtf)},
        "user_wait_seconds": {
            "p50": percentile(wait, 0.5),
            "p95": percentile(wait, 0.95),
            "n": len(wait),
        },  # fmt: skip
        "telemetry_overhead_seconds": {
            "median": statistics.median(overhead) if overhead else None,
            "n": len(overhead),
        },
        # Mean over the runs whose wall time is known (`runs_with_wall`).
        "stage_share": {k: totals[k] / measured for k in sorted(totals)} if measured else {},
        "runs_with_wall": measured,
        "backends": [
            {"kind": k[0], "name": k[1], "device": k[2], "observation": k[3], "runs": n}
            for k, n in sorted(backends.items())
        ],
    }
