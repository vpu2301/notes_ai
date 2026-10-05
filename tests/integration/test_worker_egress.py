"""A worker cannot reach an arbitrary host (RUN_EGRESS_TEST=1): drives
scripts/k8s/egress-allowlist.sh against the running cluster, and a ``diarize=true``
job still completes on pyannote community-1 with the hub and telemetry unreachable.
"""

from __future__ import annotations

import io
import math
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EGRESS_TEST") != "1",
    reason="set RUN_EGRESS_TEST=1; needs a running staging cluster or compose stack with the allowlist applied",
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k8s" / "egress-allowlist.sh"

# Hosts the in-process diarizer must never need.
DIARIZER_FORBIDDEN_HOSTS = ("otel.pyannote.ai", "huggingface.co")
PYANNOTE_ENGINE = "pyannote-community-1"

AUTH_URL = os.environ.get("EGRESS_AUTH_URL", "http://localhost:8000")
ASR_URL = os.environ.get("EGRESS_ASR_URL", "http://localhost:8001")
# The dev stack's seeded member (same default as scripts/smoke/ios_signup_e2e.py).
EMAIL = os.environ.get("EGRESS_TEST_EMAIL", "member@tenant-a.example")
PASSWORD = os.environ.get("EGRESS_TEST_PASSWORD", "dev-password")
JOB_DEADLINE_S = float(os.environ.get("EGRESS_JOB_DEADLINE_S", "600"))


def _run_allowlist_test() -> str:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "test"], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def _worker_exec(code: str) -> str:
    """``python3 -c code`` in the worker — the same pod/container the script probes."""
    ns = os.environ.get("NS", "notes-staging")
    pod = ""
    if shutil.which("kubectl"):
        pod = subprocess.run(
            ["kubectl", "-n", ns, "get", "pod", "-l", "app=asr-worker", "-o",
             "jsonpath={.items[0].metadata.name}"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.strip()  # fmt: skip
    cmd = (
        ["kubectl", "-n", ns, "exec", pod, "--", "python3", "-c", code]
        if pod
        else ["docker", "compose", "exec", "-T", "asr-worker", "python3", "-c", code]
    )
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout


def _two_voice_wav(seconds: float = 12.0, rate: int = 16_000) -> bytes:
    """Two alternating pitched tones, not speech: the assertion is that the pipeline RAN offline."""
    frames = []
    for n in range(int(rate * seconds)):
        t = n / rate
        f0 = 140.0 if int(t // 2) % 2 == 0 else 230.0
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 4 * t)
        frames.append(int(9_000 * env * math.sin(2 * math.pi * f0 * t)))
    samples = struct.pack(f"<{len(frames)}h", *frames)
    data = io.BytesIO()
    data.write(b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt ")
    data.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
    data.write(b"data" + struct.pack("<I", len(samples)) + samples)
    return data.getvalue()


def test_worker_cannot_reach_example_com_but_reaches_model_endpoint() -> None:
    assert "example.com blocked" in _run_allowlist_test()


def test_diarized_job_completes_with_pyannote_and_hub_unreachable() -> None:
    import httpx

    out = _run_allowlist_test()
    for host in DIARIZER_FORBIDDEN_HOSTS:
        assert f"{host} blocked" in out, out

    engine = _worker_exec("import os; print(os.environ.get('MDX_DIAR_ENGINE', 'legacy'))").strip()
    if engine not in ("pyannote", "http"):
        pytest.skip(
            f"worker runs MDX_DIAR_ENGINE={engine!r}; set 'pyannote' (shape A) or "
            "'http' (shape B) to test v2 egress"
        )

    login = httpx.post(
        f"{AUTH_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    fixture = os.environ.get("EGRESS_DIAR_AUDIO")
    audio = Path(fixture).read_bytes() if fixture else _two_voice_wav()
    submitted = httpx.post(
        f"{ASR_URL}/asr/jobs",
        headers=headers,
        files={"audio": ("egress.wav", audio, "audio/wav")},
        data={"language": "en", "diarize": "true"},
        timeout=60,
    )
    assert submitted.status_code < 300, submitted.text
    job_id = submitted.json()["id"]

    status = ""
    deadline = time.monotonic() + JOB_DEADLINE_S
    while time.monotonic() < deadline:
        polled = httpx.get(f"{ASR_URL}/asr/jobs/{job_id}", headers=headers, timeout=30)
        status = polled.json().get("status", "")
        if status in {"complete", "completed", "failed", "error"}:
            break
        time.sleep(2)
    assert status.startswith("complet"), f"job {job_id} ended {status!r}"

    result = httpx.get(f"{ASR_URL}/asr/jobs/{job_id}/result", headers=headers, timeout=30)
    assert result.status_code == 200, result.text
    diarization = result.json()["metadata"].get("diarization") or {}
    # Not merely "completed": a load failure completes the job undiarized or
    # on another engine, and both hosting shapes name the engine.
    assert diarization.get("engine") == PYANNOTE_ENGINE, diarization
