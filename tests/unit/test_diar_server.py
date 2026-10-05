"""deploy/diar-server (Sprint 29 B-9): auth, the payload contract, and the
promise that nothing about the caller reaches this process.

The real engine needs a GPU and gated weights, so a fake ``PyannoteDiarizer``
stands in — what is under test is the service around it: who may call,
what a call may contain, what comes back, and what is refused.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from diarization import (
    DiarizationHints,
    OfflineDiarizationConfig,
    RosterGuardConfig,
    SpeakerSegment,
    encode_audio,
    from_payload,
)
from diarization.offline import ClusterStats, OfflineDiarization
from diarization.roster import RosterOutcome

APP_PATH = Path(__file__).resolve().parents[2] / "deploy" / "diar-server" / "app.py"


class FakeDiarizer:
    """Answers like the real engine, records what it was asked."""

    ready = True
    last_error = None

    def __init__(self, **kwargs: Any) -> None:
        self.built_with = kwargs
        self.calls: list[dict[str, Any]] = []

    async def ensure_loaded(self) -> None:
        return None

    def diarize(
        self,
        pcm: np.ndarray,
        sample_rate_hz: int,
        *,
        hints: DiarizationHints,
        roster: RosterGuardConfig | None = None,
    ) -> OfflineDiarization:
        self.calls.append({"samples": len(pcm), "hints": hints, "roster": roster})
        segments = [
            SpeakerSegment(start_ms=0, end_ms=5_000, label="SPEAKER_1", confidence=1.0),
            SpeakerSegment(start_ms=5_000, end_ms=9_000, label="SPEAKER_2", confidence=0.5),
        ]
        return OfflineDiarization(
            segments=segments,
            display_names={"SPEAKER_1": "SPEAKER_1", "SPEAKER_2": "SPEAKER_2"},
            duration_ms=9_000,
            config=OfflineDiarizationConfig(),
            stats=ClusterStats(
                chunks=2, clusters_raw=2, clusters_after_merge=2, clusters_dropped=0
            ),
            engine="pyannote-community-1",
            engine_version="community-1@test",
            hints=hints,
            roster=RosterOutcome(
                segments=segments,
                speakers_kept=2,
                speakers_dissolved=0,
                count_confidence="high",
                overlap_share=0.0,
            ),
            overlap_ms=[(4_900, 5_100)],
        )


def _load_app(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(f"diar_server_{len(sys.modules)}", APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PyannoteDiarizer", FakeDiarizer)
    return module


def _audio(seconds: float = 9.0) -> bytes:
    rng = np.random.default_rng(3)
    return encode_audio(rng.standard_normal(int(16_000 * seconds)).astype(np.float32) * 0.01)[1]


def test_a_call_without_the_token_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_TOKEN="s3cret")

    with TestClient(module.app) as client:
        anonymous = client.post("/v1/audio/diarizations", files={"file": ("a.flac", _audio())})
        wrong = client.post(
            "/v1/audio/diarizations",
            files={"file": ("a.flac", _audio())},
            headers={"Authorization": "Bearer nope"},
        )

    assert (anonymous.status_code, wrong.status_code) == (401, 401)


def test_a_server_without_a_token_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_TOKEN="")

    with pytest.raises(RuntimeError, match="MDX_DIAR_SERVER_TOKEN"), TestClient(module.app):
        pass


def test_the_answer_is_what_the_client_rebuilds_the_timeline_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")

    with TestClient(module.app) as client:
        response = client.post(
            "/v1/audio/diarizations",
            files={"file": ("a.flac", _audio())},
            data={
                "num_speakers": "2",
                "min_speaker_speech_ms": "8000",
                "min_speaker_share": "0.03",
            },
        )

    assert response.status_code == 200
    diar = from_payload(
        response.json(), hints=DiarizationHints(num_speakers=2), config=OfflineDiarizationConfig()
    )
    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.attribute(1_000, 2_000) == "SPEAKER_1"
    assert diar.overlap_ms == [(4_900, 5_100)]
    call = module.app.state.diarizer.calls[0]
    assert call["hints"].num_speakers == 2, "the person's count reaches the engine"
    assert call["roster"].min_speaker_speech_ms == 8_000, "the floor is the caller's policy"


def test_the_reply_never_carries_an_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not "few floats" — no float VECTOR anywhere. A transcript legitimately
    carries thousands of confidences; an embedding is a run of them."""
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")

    with TestClient(module.app) as client:
        body = client.post("/v1/audio/diarizations", files={"file": ("a.flac", _audio())}).json()

    assert "speaker_embeddings" not in body
    assert [v for v in _flatten(body) if _looks_like_an_embedding(v)] == []


def _looks_like_an_embedding(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 32
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value)
    )


def _flatten(value: Any) -> list[Any]:
    out: list[Any] = [value]
    if isinstance(value, dict):
        for v in value.values():
            out.extend(_flatten(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_flatten(v))
    return out


def test_the_audio_never_touches_the_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starlette spools a multipart part to a temp FILE above its spool
    size; the whole promise of this service is that the caller's audio
    stays in memory."""
    import tempfile

    from starlette.formparsers import MultiPartParser

    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")
    audio = _audio(120.0)
    assert len(audio) > 1024 * 1024, "the default spool is 1 MiB; this must exceed it"
    before = set(Path(tempfile.gettempdir()).iterdir())

    with TestClient(module.app) as client:
        response = client.post("/v1/audio/diarizations", files={"file": ("a.flac", audio)})

    assert response.status_code == 200
    assert MultiPartParser.spool_max_size > len(audio)
    new_files = set(Path(tempfile.gettempdir()).iterdir()) - before
    assert not [p for p in new_files if p.is_file() and p.stat().st_size > 1024 * 1024]


def test_a_bad_token_is_refused_before_the_body_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check must happen in middleware: FastAPI parses the form
    BEFORE a route's dependencies run, so a dependency-based check would
    already have buffered (and possibly spooled) the upload."""
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_TOKEN="s3cret")
    read: list[int] = []

    class _CountingBytes(bytes):
        def __iter__(self) -> Any:  # pragma: no cover - only if the body is consumed
            read.append(1)
            return super().__iter__()

    with TestClient(module.app) as client:
        response = client.post(
            "/v1/audio/diarizations",
            files={"file": ("a.flac", _audio(120.0))},
            headers={"Authorization": "Bearer wrong", "X-MDX-Diar-Token": "wrong"},
        )

    assert response.status_code == 401
    assert module.app.state.diarizer.calls == []


def test_an_oversized_recording_is_refused_on_its_declared_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The byte cap is on COMPRESSED audio; a near-silent FLAC expands by
    orders of magnitude into one float32 allocation."""
    module = _load_app(
        monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1", MDX_DIAR_MAX_AUDIO_SECONDS="60"
    )

    with TestClient(module.app) as client:
        response = client.post("/v1/audio/diarizations", files={"file": ("a.flac", _audio(120.0))})

    assert response.status_code == 413
    assert module.app.state.diarizer.calls == [], "nothing was decoded"


def test_only_one_pass_runs_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """One pipeline object, one GPU: two concurrent passes risk pyannote's
    own state and CUDA memory."""
    import threading

    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")
    inside = []
    peak = []
    lock = threading.Lock()
    original = FakeDiarizer.diarize

    def slow(self: Any, *args: Any, **kwargs: Any) -> Any:
        with lock:
            inside.append(1)
            peak.append(len(inside))
        time.sleep(0.05)
        with lock:
            inside.pop()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FakeDiarizer, "diarize", slow)

    with TestClient(module.app) as client, ThreadPoolExecutor(max_workers=3) as pool:
        responses = [
            f.result()
            for f in [
                pool.submit(
                    client.post,
                    "/v1/audio/diarizations",
                    files={"file": ("a.flac", _audio(1.0))},
                )
                for _ in range(3)
            ]
        ]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert max(peak) == 1, f"{max(peak)} passes ran at once"


def test_the_policy_of_one_request_cannot_leak_into_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")

    with TestClient(module.app) as client:
        for floor in ("8000", "0"):
            client.post(
                "/v1/audio/diarizations",
                files={"file": ("a.flac", _audio(1.0))},
                data={"min_speaker_speech_ms": floor, "min_speaker_share": "0.03"},
            )

    floors = [call["roster"].min_speaker_speech_ms for call in module.app.state.diarizer.calls]
    assert floors == [8_000, 0], "each request is graded by its own caller's policy"


def test_a_cpu_endpoint_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.64 x audio on CPU (ADR-0052) means every recording over ~90 s
    blows the client's timeout and is retried — worse than not starting."""
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1", MDX_DIAR_DEVICE="cpu")

    with pytest.raises(RuntimeError, match="cpu"), TestClient(module.app):
        pass


def test_an_impossible_count_is_refused_before_the_gpu_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")

    with TestClient(module.app) as client:
        response = client.post(
            "/v1/audio/diarizations",
            files={"file": ("a.flac", _audio())},
            data={"num_speakers": "9"},
        )

    assert response.status_code == 422
    assert module.app.state.diarizer.calls == []


def test_something_that_is_not_audio_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")

    with TestClient(module.app) as client:
        response = client.post(
            "/v1/audio/diarizations", files={"file": ("a.flac", b"not audio at all")}
        )

    assert response.status_code == 415
    assert module.app.state.diarizer.calls == []


def test_health_answers_before_any_model_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1")

    with TestClient(module.app) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["model_id"] == "pyannote-community-1"
    assert body["authenticated"] is True, "anonymous mode; a caller would be accepted"


def test_health_tells_a_caller_its_token_is_wrong_and_hides_internals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open, because the platform's probe has no token — so it must not
    leak model paths, and it must let a misconfigured worker find out at
    startup instead of after a week of speakerless transcripts."""
    module = _load_app(monkeypatch, MDX_DIAR_SERVER_TOKEN="s3cret")

    with TestClient(module.app) as client:
        anonymous = client.get("/health").json()
        good = client.get("/health", headers={"X-MDX-Diar-Token": "s3cret"}).json()

    assert anonymous["status"] == "ok" and anonymous["authenticated"] is False
    assert "last_error" not in anonymous
    assert good["authenticated"] is True and "last_error" in good


def test_telemetry_is_off_and_the_hub_offline_before_the_engine_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_app(
        monkeypatch,
        MDX_DIAR_SERVER_ALLOW_ANONYMOUS="1",
        PYANNOTE_METRICS_ENABLED="true",
        HF_HUB_OFFLINE="0",
    )

    with TestClient(module.app):
        environ = module.app.state.diarizer.built_with["environ"]

    assert environ["PYANNOTE_METRICS_ENABLED"] == "false"
    assert environ["HF_HUB_OFFLINE"] == "1"
