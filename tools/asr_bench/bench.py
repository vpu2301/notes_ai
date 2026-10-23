"""Shared pieces of the ASR performance harness (asr-perf-sprints, Sprint A).

Dev-only. Talks to the dev stack through the product API with the caller's own
credentials; reads numbers, never transcript text, except ``quality.py ref`` which
writes a pseudo-reference outside the repo.
"""

from __future__ import annotations

import csv
import os
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "asr-perf-sprints" / "evidence"
AUDIO_DIR = Path(os.environ.get("ASR_BENCH_AUDIO", Path.home() / "asr-perf-audio"))

AUTH_URL = os.environ.get("ASR_BENCH_AUTH_URL", "http://localhost:8000")
ASR_URL = os.environ.get("ASR_BENCH_ASR_URL", "http://localhost:8001")
NOTE_URL = os.environ.get("ASR_BENCH_NOTE_URL", "http://localhost:8006")
EMAIL = os.environ.get("ASR_BENCH_EMAIL", "member@tenant-a.example")
PASSWORD = os.environ.get("ASR_BENCH_PASSWORD", "dev-password")

ROW_FIELDS = (
    "run_id", "recording", "condition", "temp", "rep", "status", "attempts",
    "concurrent_runs_at_start", "excluded", "app_commit", "execution_mode",
    "memory_total_bytes", "backend", "model", "compute_type", "device", "device_observation",
    "audio_duration_seconds", "queue_wait_seconds", "audio_prep_seconds",
    "asr_model_startup_load_seconds", "asr_primary_wall_seconds", "asr_primary_rtf",
    "lid_call_count", "lid_total_seconds", "time_to_asr_start_seconds",
    "diarization_load_seconds", "diarization_infer_seconds", "pipeline_wall_seconds",
    "user_wait_seconds", "rss_peak_bytes", "swap_delta_bytes", "asr_audio_processed_seconds",
    "telemetry_overhead_seconds", "host_mem_free_pct", "power_source", "low_power_mode",
)  # fmt: skip


def login(email: str = EMAIL, password: str = PASSWORD) -> str:
    r = httpx.post(
        f"{AUTH_URL}/auth/login",
        json={"email": email, "password": password},
        headers={"X-Client-Type": "macos"},
        timeout=30,
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


class _Bearer(httpx.Auth):
    """Bearer token that logs in again on a 401: a 15-minute recording on CPU outlives one."""

    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx.Request):  # type: ignore[no-untyped-def]
        request.headers["Authorization"] = f"Bearer {self.token}"
        response = yield request
        if response.status_code == 401:
            self.token = login()
            request.headers["Authorization"] = f"Bearer {self.token}"
            yield request


def clients(token: str) -> tuple[httpx.Client, httpx.Client]:
    auth = _Bearer(token)
    return (
        httpx.Client(base_url=ASR_URL, auth=auth, timeout=120),
        httpx.Client(base_url=NOTE_URL, auth=auth, timeout=60),
    )


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _seconds(span: dict[str, Any]) -> float | None:
    if not span.get("start_wall_utc") or not span.get("end_wall_utc"):
        return None
    return (_ts(span["end_wall_utc"]) - _ts(span["start_wall_utc"])).total_seconds()


def _attr(span: dict[str, Any] | None, key: str) -> Any:
    return (span or {}).get("attributes", {}).get(key)


def _first(spans: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((s for s in spans if s["name"] == name), None)


def excluded_reason(run: dict[str, Any]) -> str:
    """Why a run may not enter a speed aggregate (empty = it may)."""
    if run.get("status") != "succeeded":
        return f"status:{run.get('status')}"
    if (run.get("attempts") or 1) > 1:
        return "attempt>1"
    if (run.get("concurrent_runs_at_start") or 0) > 0:
        return "concurrent"
    return ""


def row_from_run(export: dict[str, Any]) -> dict[str, Any]:
    """One CSV row from ``GET /v1/telemetry/runs/{id}`` (the structured run record)."""
    run = export["processing_run"]
    ctx = export.get("run_context") or {}
    attempts = run.get("attempts") or 1
    # Spans of an earlier attempt (requeue) do not describe the run that produced the result.
    spans = [s for s in export["spans"] if (s.get("attempt") or 1) == attempts]
    audio = run.get("audio_duration_seconds")

    primary = [s for s in spans if s["name"] == "asr.transcribe_runs"]
    primary_wall = (
        sum((_attr(s, "wall_seconds") or _seconds(s) or 0.0) for s in primary) if primary else None
    )
    asr_starts = [_ts(s["start_wall_utc"]) for s in spans if s["stage"] == "asr_primary"]
    lid = [s for s in spans if s["stage"] == "language_detection"]
    # A redelivered pickup of a finished job is a skipped span off the critical path.
    queue = [s for s in spans if s["name"] == "asr.queue_wait" and not _attr(s, "redelivery")]
    diar_load = _first(spans, "diarization.load")
    diar_infer = _first(spans, "diarization.infer")
    device = _attr(primary[0] if primary else None, "device") or ctx.get("device_asr") or {}
    rss = [v for v in (ctx.get("process_rss_start"), ctx.get("process_rss_end")) if v is not None]
    swap0, swap1 = ctx.get("swap_used_start"), ctx.get("swap_used_end")

    return {
        "run_id": run["processing_run_id"],
        "status": run.get("status"),
        "attempts": attempts,
        "concurrent_runs_at_start": run.get("concurrent_runs_at_start"),
        "excluded": excluded_reason(run),
        "app_commit": ctx.get("app_commit"),
        "execution_mode": ctx.get("execution_mode"),
        "memory_total_bytes": ctx.get("memory_total_bytes"),
        "backend": _attr(primary[0], "backend") if primary else None,
        "model": _attr(primary[0], "model") if primary else None,
        "compute_type": _attr(primary[0], "compute_type") if primary else None,
        "device": device.get("value"),
        "device_observation": device.get("observation"),
        "audio_duration_seconds": audio,
        "queue_wait_seconds": _attr(queue[0], "queue_wait_seconds") if queue else None,
        "audio_prep_seconds": _seconds(_first(spans, "asr.audio_prep") or {}),
        "asr_model_startup_load_seconds": _attr(_first(spans, "asr.model"), "startup_load_seconds"),
        "asr_primary_wall_seconds": primary_wall,
        "asr_primary_rtf": primary_wall / audio if primary_wall is not None and audio else None,
        "lid_call_count": len(lid),
        "lid_total_seconds": sum(_seconds(s) or 0.0 for s in lid),
        "time_to_asr_start_seconds": (
            (min(asr_starts) - _ts(run["submitted_at"])).total_seconds() if asr_starts else None
        ),
        "diarization_load_seconds": _attr(diar_load, "load_seconds"),
        "diarization_infer_seconds": _attr(diar_infer, "infer_seconds"),
        "pipeline_wall_seconds": run.get("processing_wall_seconds"),
        "user_wait_seconds": run.get("user_wait_seconds"),
        # The run records RSS at start and end only; no continuous peak exists in telemetry.
        "rss_peak_bytes": max(rss) if rss else None,
        "swap_delta_bytes": swap1 - swap0 if swap0 is not None and swap1 is not None else None,
        "asr_audio_processed_seconds": run.get("asr_audio_processed_seconds"),
        "telemetry_overhead_seconds": run.get("telemetry_overhead_seconds"),
    }


def append_csv(path: Path, row: dict[str, Any], fields: tuple[str, ...] = ROW_FIELDS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def median_min_max(values: list[float]) -> tuple[float, float, float] | None:
    if not values:
        return None
    return statistics.median(values), min(values), max(values)
