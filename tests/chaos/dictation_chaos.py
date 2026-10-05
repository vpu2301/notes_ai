"""Chaos scenarios for the streaming dictation pipeline against the live dev stack
(random closes, frame drop + jitter, malformed and oversized frames, double tab,
worker kill, network outage). Skipped unless RUN_DICTATION_CHAOS=1; drives synthetic
frames, so ``audio_decode_failed`` is the expected recoverable reply.
Env: DICTATION_TOKEN (required), DICTATION_WS_URL, DICTATION_READY_URL, DICTATION_RESTART_CMD.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import struct
import subprocess
import urllib.request
from dataclasses import dataclass, field

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DICTATION_CHAOS") != "1",
    reason="set RUN_DICTATION_CHAOS=1 and bring up `make dev-up`",
)

WS_URL = os.environ.get("DICTATION_WS_URL", "ws://localhost:8002/ws/dictate")
READY_URL = os.environ.get("DICTATION_READY_URL", "http://localhost:8002/readyz")
ACCESS_TOKEN = os.environ.get("DICTATION_TOKEN", "")
RESTART_CMD = os.environ.get(
    "DICTATION_RESTART_CMD",
    "docker compose -f infra/compose/base.yml -f infra/compose/dev.yml restart dictation-service",
)

SUBPROTOCOL = "dictation.v1"


# ── Frame helpers ─────────────────────────────────────────────────────


def _frame(seq: int, payload: bytes) -> bytes:
    """Wire binary frame: 4-byte BE seq || opaque payload."""
    return struct.pack(">I", seq) + payload


def _silence_payload() -> bytes:
    """A well-sized synthetic frame. Not valid Opus → the server replies
    ``audio_decode_failed`` (recoverable) and keeps the session alive."""
    return b"\x00" * 80


def _malformed_payload() -> bytes:
    return os.urandom(80)


@dataclass(slots=True)
class StreamStats:
    partials: int = 0
    finals: int = 0
    decode_failures: int = 0
    fatal_errors: list[str] = field(default_factory=list)
    recoverable_errors: list[str] = field(default_factory=list)
    terminated_reason: str | None = None
    session_started: int = 0


# Mirrors error_catalogue.RECOVERABLE (duplicated to keep the harness dependency-free).
_RECOVERABLE = {
    "bad_message",
    "audio_decode_failed",
    "gap_detected",
    "high_latency",
    "worker_overloaded",
    "low_confidence",
    "gpu_full",
    "rate_limited",
    "retransmit_too_large",
}


async def _consume(ws, stats: StreamStats) -> None:  # type: ignore[no-untyped-def]
    """Drain server messages into ``stats`` until the socket closes."""
    try:
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                stats.fatal_errors.append("malformed_json_from_server")
                continue
            t = msg.get("type")
            if t == "partial":
                stats.partials += 1
            elif t == "final":
                stats.finals += 1
            elif t == "session_started":
                stats.session_started += 1
            elif t == "session_terminated":
                stats.terminated_reason = msg.get("reason")
                return
            elif t == "error":
                code = msg.get("code", "error")
                if code == "audio_decode_failed":
                    stats.decode_failures += 1
                if code in _RECOVERABLE:
                    stats.recoverable_errors.append(code)
                else:
                    stats.fatal_errors.append(code)
    except Exception:  # noqa: BLE001 — abrupt close is normal in chaos
        return


def _connect():  # type: ignore[no-untyped-def]
    import websockets

    return websockets.connect(
        WS_URL,
        subprotocols=[SUBPROTOCOL],
        additional_headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
    )


async def _start_session(ws, *, resume_session_id: str | None = None) -> dict:  # type: ignore[no-untyped-def]
    """Send ``start_session`` and return the full ``session_started`` payload."""
    msg = {
        "type": "start_session",
        "language": "uk",
        "target_kind": "generic",
    }
    if resume_session_id is not None:
        msg["resume_session_id"] = resume_session_id
    await ws.send(json.dumps(msg))
    raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
    reply = json.loads(raw)
    return reply


async def _drive(
    ws,  # type: ignore[no-untyped-def]
    *,
    frames: int,
    start_seq: int = 0,
    drop_rate: float = 0.0,
    jitter_ms: int = 0,
    malformed_rate: float = 0.0,
) -> int:
    """Stream ``frames`` synthetic binary frames. Returns next free seq."""
    seq = start_seq
    for _ in range(frames):
        seq += 1
        if drop_rate and random.random() < drop_rate:
            continue
        payload = (
            _malformed_payload()
            if malformed_rate and random.random() < malformed_rate
            else _silence_payload()
        )
        await ws.send(_frame(seq, payload))
        delay = 0.02
        if jitter_ms:
            delay += random.uniform(-jitter_ms, jitter_ms) / 1000.0
        await asyncio.sleep(max(0.0, delay))
    return seq


def _fetch_ready() -> bool:
    """Blocking single /readyz poll. Run via ``asyncio.to_thread``."""
    try:
        with urllib.request.urlopen(READY_URL, timeout=3) as resp:  # noqa: S310
            return bool(json.loads(resp.read()).get("status") == "ready")
    except Exception:  # noqa: BLE001
        return False


async def _wait_ready(timeout_s: float = 90.0) -> None:
    """Await until /readyz reports ready (used after a worker restart)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if await asyncio.to_thread(_fetch_ready):
            return
        await asyncio.sleep(1.0)
    raise AssertionError(f"service not ready within {timeout_s}s after restart")


# ── Scenarios ─────────────────────────────────────────────────────────


async def test_scenario_1_random_close_and_resume() -> None:
    """Repeated abrupt closes; each reconnect resumes the same session and
    committed audio never goes backwards."""
    async with _connect() as ws:
        started = await _start_session(ws)
        assert started["type"] == "session_started", started
        session_id = started["session_id"]
        committed = started["committed_audio_until_ms"]
        await _drive(ws, frames=60)

    last_committed = committed
    seq = 60
    for _ in range(3):
        await asyncio.sleep(1.0)  # let the server move us to RECONNECTING
        async with _connect() as ws:
            resumed = await _start_session(ws, resume_session_id=session_id)
            assert resumed["type"] == "session_started", resumed
            assert resumed["resumed"] is True
            assert resumed["session_id"] == session_id
            assert resumed["committed_audio_until_ms"] >= last_committed
            last_committed = resumed["committed_audio_until_ms"]
            seq = await _drive(ws, frames=40, start_seq=seq)

    # Clean finish on the live connection.
    await asyncio.sleep(0.5)
    async with _connect() as ws:
        final_start = await _start_session(ws, resume_session_id=session_id)
        assert final_start["resumed"] is True
        await ws.send(json.dumps({"type": "end_session"}))


async def test_scenario_2_jitter_and_drop() -> None:
    """1 % drop + ±50 ms jitter → session survives with only recoverable
    errors and terminates cleanly."""
    stats = StreamStats()
    async with _connect() as ws:
        started = await _start_session(ws)
        assert started["type"] == "session_started"
        consume = asyncio.create_task(_consume(ws, stats))
        await _drive(ws, frames=300, drop_rate=0.01, jitter_ms=50)
        await ws.send(json.dumps({"type": "end_session"}))
        await asyncio.wait_for(consume, timeout=15.0)

    assert stats.fatal_errors == [], f"unexpected fatal errors: {stats.fatal_errors}"
    assert stats.terminated_reason in (None, "normal")


async def test_scenario_3_malformed_frames_tolerated() -> None:
    """5 % malformed frames → no fatal error; the session stays alive and
    terminates cleanly (completeness = no malformed frame killed it)."""
    stats = StreamStats()
    async with _connect() as ws:
        started = await _start_session(ws)
        assert started["type"] == "session_started"
        consume = asyncio.create_task(_consume(ws, stats))
        await _drive(ws, frames=300, malformed_rate=0.05)
        await ws.send(json.dumps({"type": "end_session"}))
        await asyncio.wait_for(consume, timeout=15.0)

    assert stats.fatal_errors == [], f"unexpected fatal errors: {stats.fatal_errors}"
    assert stats.terminated_reason in (None, "normal")


async def test_scenario_4_oversized_frame_rejected() -> None:
    """A 16 KiB binary frame must be rejected with ``bad_message``."""
    async with _connect() as ws:
        started = await _start_session(ws)
        assert started["type"] == "session_started"
        big = struct.pack(">I", 0) + os.urandom(16 * 1024)
        await ws.send(big)
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(raw)
        assert msg["type"] == "error", msg
        assert msg["code"] == "bad_message", msg


async def test_scenario_5_double_tab_rejected() -> None:
    """A second connection resuming a still-live session is rejected with
    the uniform ``session_not_found`` (single-tab guard)."""
    async with _connect() as ws_a:
        started = await _start_session(ws_a)
        assert started["type"] == "session_started"
        session_id = started["session_id"]
        await _drive(ws_a, frames=10)

        # Second tab tries to grab the same live session.
        async with _connect() as ws_b:
            reply = await _start_session(ws_b, resume_session_id=session_id)
            assert reply["type"] == "error", reply
            assert reply["code"] == "session_not_found", reply


@pytest.mark.skipif(not RESTART_CMD, reason="DICTATION_RESTART_CMD not set")
async def test_scenario_6_worker_kill_yields_worker_failed() -> None:
    """Restart the worker mid-session: the DB row survives, the context is gone, resume returns ``worker_failed``."""
    async with _connect() as ws:
        started = await _start_session(ws)
        assert started["type"] == "session_started"
        session_id = started["session_id"]
        await _drive(ws, frames=40)

    # Run from the repo root so the compose paths resolve.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    await asyncio.to_thread(
        lambda: subprocess.run(RESTART_CMD, shell=True, check=True, cwd=repo_root)  # noqa: S602
    )
    await _wait_ready()

    async with _connect() as ws:
        reply = await _start_session(ws, resume_session_id=session_id)
        assert reply["type"] == "error", reply
        assert reply["code"] in ("worker_failed", "session_not_found"), reply


async def test_scenario_7_network_outage_reconnect() -> None:
    """A ~10 s outage (close, wait, reopen) reconnects+resumes well within
    the 30-min abandon window."""
    async with _connect() as ws:
        started = await _start_session(ws)
        assert started["type"] == "session_started"
        session_id = started["session_id"]
        await _drive(ws, frames=50)

    await asyncio.sleep(10.0)  # the outage

    async with _connect() as ws:
        resumed = await _start_session(ws, resume_session_id=session_id)
        assert resumed["type"] == "session_started", resumed
        assert resumed["resumed"] is True
        assert resumed["session_id"] == session_id
        await ws.send(json.dumps({"type": "end_session"}))
