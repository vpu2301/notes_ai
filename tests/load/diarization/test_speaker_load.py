"""Speaker-labeling load + soak, staging only: 20 concurrent 60-min diarized jobs
(queue wait p95 <= 10 min, diarization <= 0.25x audio p95, notes stay fast), 50 re-runs
across 10 tenants (only 202/409/429, no starvation), and a soak loop.

    RUN_SPEAKER_LOAD=1 ASR_BASE=... SPEAKER_LOAD_TOKENS=... SPEAKER_LOAD_AUDIO=... NOTES_BASE=... uv run pytest tests/load/diarization -s
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from datetime import datetime
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SPEAKER_LOAD") != "1",
    reason="staging only: set RUN_SPEAKER_LOAD=1, ASR_BASE, SPEAKER_LOAD_TOKENS, SPEAKER_LOAD_AUDIO",
)

ASR = os.environ.get("ASR_BASE", "").rstrip("/")
NOTES = os.environ.get("NOTES_BASE", ASR).rstrip("/")
TOKENS = [t for t in os.environ.get("SPEAKER_LOAD_TOKENS", "").split(",") if t]
AUDIO = os.environ.get("SPEAKER_LOAD_AUDIO", "")


def _p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=20)[-1] if len(values) >= 2 else (values or [0.0])[0]


async def _submit(client: Any, token: str) -> str:
    with open(AUDIO, "rb") as fh:
        resp = await client.post(
            f"{ASR}/asr/jobs",
            headers={"Authorization": f"Bearer {token}"},
            files={"audio": (os.path.basename(AUDIO), fh.read(), "audio/flac")},
            data={"language": "auto", "diarize": "true"},
        )
    resp.raise_for_status()
    return str(resp.json()["id"])


async def _wait(client: Any, token: str, job: str, *, key: str, done: set[str]) -> dict[str, Any]:
    while True:
        view = (
            await client.get(f"{ASR}/asr/jobs/{job}", headers={"Authorization": f"Bearer {token}"})
        ).json()
        if view.get(key) in done:
            return view
        await asyncio.sleep(10)


async def test_scenario_1_concurrent_diarized_jobs() -> None:
    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        token = TOKENS[0]
        jobs = await asyncio.gather(*(_submit(client, token) for _ in range(20)))
        notes_ms: list[float] = []

        async def notes_smoke() -> None:
            for _ in range(60):
                t0 = time.perf_counter()
                await client.get(f"{NOTES}/v1/notes", headers={"Authorization": f"Bearer {token}"})
                notes_ms.append((time.perf_counter() - t0) * 1000)
                await asyncio.sleep(5)

        views, _ = await asyncio.gather(
            asyncio.gather(
                *(_wait(client, token, j, key="status", done={"complete", "failed"}) for j in jobs)
            ),
            notes_smoke(),
        )
        waits = [
            (
                datetime.fromisoformat(v["started_at"]) - datetime.fromisoformat(v["queued_at"])
            ).total_seconds()
            for v in views
            if v.get("started_at")
        ]
        ratios = []
        for j in jobs:
            result = (
                await client.get(
                    f"{ASR}/asr/jobs/{j}/result", headers={"Authorization": f"Bearer {token}"}
                )
            ).json()
            stats = (result.get("metadata") or {}).get("diarization") or {}
            audio_s = (result.get("segments") or [{}])[-1].get("end_ms", 0) / 1000
            if stats.get("seconds") and audio_s:
                ratios.append(stats["seconds"] / audio_s)
    print(
        f"\n[load-1] failed={sum(v['status'] == 'failed' for v in views)} "
        f"queue_wait_p95_s={_p95(waits):.0f} diar_ratio_p95={_p95(ratios):.3f} "
        f"notes_p95_ms={_p95(notes_ms):.0f}"
    )
    assert all(v["status"] == "complete" for v in views)
    assert _p95(waits) <= 600
    assert _p95(ratios) <= 0.25


async def test_scenario_2_rerun_burst_across_tenants() -> None:
    import httpx

    assert len(TOKENS) >= 10, "one token per tenant, 10 tenants"
    async with httpx.AsyncClient(timeout=60) as client:
        jobs = await asyncio.gather(*(_submit(client, t) for t in TOKENS[:10]))
        await asyncio.gather(
            *(
                _wait(client, t, j, key="status", done={"complete"})
                for t, j in zip(TOKENS, jobs, strict=False)
            )
        )
        codes: list[int] = []
        accepted: list[tuple[str, str]] = []
        for i in range(50):
            token, job = TOKENS[i % 10], jobs[i % 10]
            resp = await client.post(
                f"{ASR}/asr/jobs/{job}/rediarize",
                headers={"Authorization": f"Bearer {token}"},
                json={"speakers_expected": None},
            )
            codes.append(resp.status_code)
            if resp.status_code == 202:
                accepted.append((token, job))
            await asyncio.sleep(6)  # 50 requests over 5 minutes
        t0 = time.monotonic()
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    _wait(client, t, j, key="diarization_status", done={"complete", "failed"})
                    for t, j in accepted
                )
            ),
            timeout=900,
        )
    print(
        f"\n[load-2] codes={sorted(set(codes))} accepted={len(accepted)} drained_s={time.monotonic() - t0:.0f}"
    )
    assert set(codes) <= {202, 409, 429}
    assert {job for _, job in accepted} == set(jobs), "every tenant got at least one run through"


@pytest.mark.skipif(
    not os.environ.get("SPEAKER_SOAK_HOURS"), reason="set SPEAKER_SOAK_HOURS for the soak"
)
async def test_scenario_5_soak() -> None:
    deadline = time.monotonic() + float(os.environ["SPEAKER_SOAK_HOURS"]) * 3600
    rounds = 0
    while time.monotonic() < deadline:
        await test_scenario_1_concurrent_diarized_jobs()
        rounds += 1
    print(f"\n[load-5] rounds={rounds} — read worker RSS drift on the ASR dashboard")
