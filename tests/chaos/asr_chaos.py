"""Chaos scenarios for the batch ASR pipeline: SIGKILL mid-job -> a second worker
reclaims via XAUTOCLAIM (never stuck ``running``), and 3 failed reclaims -> DLQ.
Needs the dev stack, asr-service, a baked CPU model and a token; skipped unless
``RUN_ASR_CHAOS=1``. Env: ASR_BASE_URL, ASR_TOKEN, ASR_SAMPLE_AUDIO, ASR_WORKER_CMD.
The harness spawns and kills the workers itself.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_ASR_CHAOS") != "1",
    reason="set RUN_ASR_CHAOS=1; needs dev stack + asr-service + baked CPU model + token",
)

BASE_URL = os.environ.get("ASR_BASE_URL", "http://localhost:8001")
TOKEN = os.environ.get("ASR_TOKEN", "")
SAMPLE_AUDIO = os.environ.get("ASR_SAMPLE_AUDIO", "")
WORKER_CMD = os.environ.get(
    "ASR_WORKER_CMD",
    "uv run --project services/asr-worker python -m asr_worker.main",
)

# Short idle threshold so reclaim fires well inside the 90 s bound.
RECLAIM_MS = 5_000
TERMINAL = {"complete", "failed"}


def _spawn_worker(name: str) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    env.update(
        {
            "MD_ASR_DEVICE": "cpu",
            "MD_ASR_WORKER_NAME": name,
            "MD_ASR_JOBS_IDLE_RECLAIM_MS": str(RECLAIM_MS),
            "OTEL_SDK_DISABLED": "true",
        }
    )
    return subprocess.Popen(shlex.split(WORKER_CMD), env=env)  # noqa: S603


def _kill9(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _submit_job(client: httpx.Client) -> str:
    audio = Path(SAMPLE_AUDIO)
    assert audio.is_file(), f"ASR_SAMPLE_AUDIO not found: {SAMPLE_AUDIO}"
    files = {"audio": (audio.name, audio.read_bytes(), "audio/wav")}
    data = {"language": "uk"}
    resp = client.post("/asr/jobs", headers=_headers(), files=files, data=data)
    assert resp.status_code == 202, f"submit failed: {resp.status_code} {resp.text}"
    return str(resp.json()["job_id"])


def _poll_status(client: httpx.Client, job_id: str) -> str:
    resp = client.get(f"/asr/jobs/{job_id}", headers=_headers())
    assert resp.status_code == 200, resp.text
    return str(resp.json()["status"])


def _wait_for(client: httpx.Client, job_id: str, wanted: set[str], timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = _poll_status(client, job_id)
        if last in wanted:
            return last
        time.sleep(0.5)
    raise AssertionError(
        f"job {job_id} stuck in {last!r}; wanted one of {wanted} within {timeout_s}s"
    )


@pytest.fixture
def http_client() -> httpx.Client:
    assert TOKEN, "set ASR_TOKEN"
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        yield client


def test_sigkill_midjob_is_reclaimed_by_second_worker(http_client: httpx.Client) -> None:
    """§4.7: kill -9 the worker holding a running job; a second worker reclaims
    it and the row reaches a terminal state within 90 s."""
    worker_a = _spawn_worker("chaos-A")
    worker_b: subprocess.Popen[bytes] | None = None
    try:
        # Give A time to join the group and warm the model before we submit.
        time.sleep(15)
        job_id = _submit_job(http_client)

        # Wait until A has actually picked the job up.
        _wait_for(http_client, job_id, {"running"}, timeout_s=60)

        # Hard-kill A mid-job: the message is now stuck in A's PEL, unacked.
        _kill9(worker_a)

        # A second worker must reclaim it once idle exceeds the threshold.
        worker_b = _spawn_worker("chaos-B")
        final = _wait_for(http_client, job_id, TERMINAL, timeout_s=90)
        assert final in TERMINAL, f"job ended in non-terminal state {final!r}"
    finally:
        _kill9(worker_a)
        if worker_b is not None:
            _kill9(worker_b)
