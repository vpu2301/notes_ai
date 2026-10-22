"""Run recordings through the product path and store the telemetry reports.

    uv run python tools/asr_bench/run_matrix.py --sprint A --condition baseline-cpu \
        --recordings de-2m en-2m --warm --repeat 3

Per run: wait until the caller has no job in flight, upload the file to ``POST /asr/jobs``
exactly as the web upload does (language ``auto``, diarize on, source ``upload``), wait for
the job, start the note with ``POST /v1/notes/from-transcript`` (what the web does when the
transcript is ready), wait for the note generation to close the run, then save
``<recording>_<cold|warm>_<n>.md`` (the run report) and a row in ``runs.csv`` under
``asr-perf-sprints/evidence/<sprint>/<condition>/``.

Cold: ``--restart-cmd`` runs before every repetition (default: restart the asr-worker
container); the job then waits in the queue while the worker boots. Warm: one extra first
run is made and marked ``excluded=warmup``. Failed/partial/cancelled runs, runs with
attempt > 1 and runs with ``concurrent_runs_at_start`` > 0 are kept in the CSV with the
reason in ``excluded`` and left out of every aggregate.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402

DEFAULT_RESTART = "docker compose restart asr-worker"
PG_CONTAINER = os.environ.get("ASR_BENCH_PG_CONTAINER", "notes-ai-postgres-1")
TERMINAL = {"complete", "failed", "cancelled"}
POLL_S = 1.0


def audio_file(recording: str) -> Path:
    found = sorted(
        p for p in bench.AUDIO_DIR.glob(f"{recording}.*") if not p.name.endswith(".json")
    )
    if not found:
        raise SystemExit(f"no audio for {recording} in {bench.AUDIO_DIR}")
    return found[0]


def host_mem_free_pct() -> float | None:
    try:
        out = subprocess.run(
            ["memory_pressure", "-Q"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"free percentage:\s*(\d+)", out)
    return float(m.group(1)) if m else None


def open_runs() -> int:
    """Runs open on the whole stack, every workspace (the API shows only the caller's jobs).
    A cold restart while another job runs would kill it."""
    out = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-d", "notes", "-Atc",
         "SELECT telemetry_open_runs()"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return int(out.stdout.strip() or 0)


def wait_idle(asr: httpx.Client, timeout_s: float) -> None:
    """Until no job of the caller is queued or running and no run is open on the stack."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        jobs = asr.get("/asr/jobs").raise_for_status().json()
        if not any(j["status"] in ("queued", "running") for j in jobs) and open_runs() == 0:
            return
        time.sleep(15)
    raise SystemExit("the stack did not become idle")


def wait_run(note: httpx.Client, run_id: str, notes: bool, timeout_s: float) -> dict[str, Any]:
    """The run record once it is closed (and, with notes, once note generation ended)."""
    deadline = time.monotonic() + timeout_s
    export: dict[str, Any] = {}
    while time.monotonic() < deadline:
        export = note.get(f"/v1/telemetry/runs/{run_id}").raise_for_status().json()
        if export["processing_run"].get("finished_at"):
            gen = [s for s in export["spans"] if s["name"] == "notes.generate"]
            if not notes or (gen and all(s.get("end_wall_utc") for s in gen)):
                return export
        time.sleep(POLL_S * 5)
    return export


def one_run(
    asr: httpx.Client,
    note: httpx.Client,
    path: Path,
    title: str,
    timeout_s: float,
) -> dict[str, Any]:
    with path.open("rb") as f:
        r = asr.post(
            "/asr/jobs",
            files={"audio": (path.name, f)},
            data={"language": "auto", "diarize": "true", "capture_source": "upload"},
        )
    r.raise_for_status()
    job_id = r.json()["id"]
    runs = note.get(f"/v1/telemetry/recordings/{job_id}/runs").raise_for_status().json()
    run_id = runs["runs"][0]["processing_run_id"]
    deadline = time.monotonic() + timeout_s
    status = "queued"
    while status not in TERMINAL and time.monotonic() < deadline:
        time.sleep(POLL_S)
        status = asr.get(f"/asr/jobs/{job_id}").raise_for_status().json()["status"]
    notes = status == "complete"
    if notes:
        note.post(
            "/v1/notes/from-transcript", json={"asr_job_id": job_id, "title": title}
        ).raise_for_status()
    export = wait_run(note, run_id, notes, timeout_s)
    export["_report_md"] = note.get(f"/v1/telemetry/runs/{run_id}/report.md").text
    return export


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--sprint", required=True)
    p.add_argument("--condition", required=True)
    p.add_argument("--recordings", nargs="+", required=True)
    p.add_argument("--repeat", type=int, required=True)
    temp = p.add_mutually_exclusive_group(required=True)
    temp.add_argument("--cold", action="store_true")
    temp.add_argument("--warm", action="store_true")
    p.add_argument("--restart-cmd", action="append", help=f"cold only; default {DEFAULT_RESTART!r}")
    p.add_argument("--timeout", type=float, default=3 * 3600, help="per run, seconds")
    a = p.parse_args()

    kind = "cold" if a.cold else "warm"
    restarts = a.restart_cmd or [DEFAULT_RESTART]
    out = bench.EVIDENCE / a.sprint / a.condition
    out.mkdir(parents=True, exist_ok=True)
    asr, note = bench.clients(bench.login())

    for recording in a.recordings:
        path = audio_file(recording)
        # Warm: run 0 warms the worker and is kept but excluded.
        reps = range(1, a.repeat + 1) if a.cold else range(0, a.repeat + 1)
        for n in reps:
            wait_idle(asr, a.timeout)
            if a.cold:
                for cmd in restarts:
                    subprocess.run(shlex.split(cmd), check=True, cwd=bench.REPO)
            # Tokens are short-lived; a 15-minute recording outlives one.
            asr, note = bench.clients(bench.login())
            free = host_mem_free_pct()
            export = one_run(asr, note, path, f"asr-bench {recording} {a.condition}", a.timeout)
            name = f"{recording}_{kind}_{n}"
            (out / f"{name}.md").write_text(export.pop("_report_md"))
            row = bench.row_from_run(export)
            if a.warm and n == 0:
                row["excluded"] = row["excluded"] or "warmup"
            row.update(
                recording=recording, condition=a.condition, temp=kind, rep=n,
                host_mem_free_pct=free,
            )  # fmt: skip
            bench.append_csv(out / "runs.csv", row)
            print(
                f"{name}: {row['status']} wall={row['pipeline_wall_seconds']} "
                f"asr_rtf={row['asr_primary_rtf']} lid={row['lid_call_count']}/"
                f"{row['lid_total_seconds']:.1f}s excluded={row['excluded'] or '-'}",
                flush=True,
            )


if __name__ == "__main__":
    main()
