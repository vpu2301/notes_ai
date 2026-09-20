"""The remote engine (Sprint 29 B-9, shape B): what it sends, what it
accepts, and what it does when the endpoint misbehaves.

No network and no model: an ``httpx.MockTransport`` plays the endpoint,
and the payloads are built with the same ``wire`` module the real server
uses — which is the point of having one.
"""

from __future__ import annotations

from typing import Any

import httpx
import numpy as np
import pytest

from diarization import (
    DiarizationHints,
    DiarizationUnavailableError,
    HttpDiarizer,
    OfflineDiarizationConfig,
    RosterGuardConfig,
    SpeakerSegment,
    WirePayloadError,
    decode_audio,
    encode_audio,
)
from diarization.http_engine import DiarizationRequestError
from diarization.wire import WIRE_VERSION

TWO_SPEAKERS: dict[str, Any] = {
    "wire_version": WIRE_VERSION,
    "model_id": "pyannote-community-1",
    "engine": "pyannote-community-1",
    "engine_version": "community-1@abc+pyannote.audio-4.0.7",
    "seconds": 3.5,
    "duration_ms": 20_000,
    "segments": [
        {"start_ms": 0, "end_ms": 8_000, "speaker": "SPEAKER_1", "confidence": 1.0},
        {"start_ms": 8_000, "end_ms": 20_000, "speaker": "SPEAKER_2", "confidence": 0.5},
    ],
    "display_names": {"SPEAKER_1": "SPEAKER_1", "SPEAKER_2": "SPEAKER_2"},
    "overlap_ms": [[7_900, 8_100]],
    "stats": {"chunks": 2, "clusters_raw": 2, "clusters_after_merge": 2, "clusters_dropped": 1},
    "roster": {
        "speakers_kept": 2,
        "speakers_dissolved": 1,
        "count_confidence": "low",
        "overlap_share": 0.01,
        "reasons": ["dissolved_speaker"],
    },
}


def _pcm(seconds: float = 20.0) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.standard_normal(int(16_000 * seconds)).astype(np.float32) * 0.01


def _engine(handler: Any, **kwargs: Any) -> HttpDiarizer:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://diar.test")
    return HttpDiarizer(
        backend="hf_eu_diar",
        base_url="http://diar.test",
        model_id="pyannote-community-1",
        client=client,
        sleep=lambda _seconds: None,
        **kwargs,
    )


def test_the_reply_becomes_the_structure_word_attribution_reads() -> None:
    engine = _engine(lambda request: httpx.Response(200, json=TWO_SPEAKERS))

    diar = engine.diarize(_pcm(), 16_000, hints=DiarizationHints())

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.attribute(1_000, 2_000) == "SPEAKER_1"
    assert diar.attribute(10_000, 11_000) == "SPEAKER_2"
    assert diar.overlap_ms == [(7_900, 8_100)]
    assert diar.count_confidence == "low"
    assert diar.stats.clusters_dropped == 1
    assert diar.engine == "pyannote-community-1", "the engine that made it, not the transport"
    assert engine.engine == "http:hf_eu_diar", "the transport, for DiarizationStats"


def test_the_request_carries_audio_hints_and_the_roster_policy_and_nothing_else() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["type"] = request.headers["content-type"]
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=TWO_SPEAKERS)

    engine = _engine(handler, roster=RosterGuardConfig(min_speaker_speech_ms=8_000))
    engine._client.headers["Authorization"] = "Bearer secret-token"  # noqa: SLF001

    engine.diarize(_pcm(), 16_000, hints=DiarizationHints(num_speakers=2))

    body = seen["body"].decode("latin-1")
    assert 'name="num_speakers"' in body and "\r\n2\r\n" in body
    assert 'name="min_speaker_speech_ms"' in body and "8000" in body
    assert seen["auth"] == "Bearer secret-token"
    for forbidden in ("tenant", "job_id", "user", "audio_id"):
        assert forbidden not in body.lower(), "the endpoint gets audio, not who it belongs to"


def test_audio_survives_the_round_trip_losslessly() -> None:
    pcm = _pcm(1.0)

    name, encoded = encode_audio(pcm)
    decoded = decode_audio(encoded)

    assert name.endswith((".flac", ".wav"))
    assert decoded.shape == pcm.shape
    assert np.max(np.abs(decoded - pcm)) < 1e-3


def test_a_server_error_is_retried_then_reported_as_unavailable() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="scaling up")

    engine = _engine(handler)

    with pytest.raises(DiarizationUnavailableError):
        engine.diarize(_pcm(), 16_000, hints=DiarizationHints())

    assert len(calls) == 3, "two retries, then give up (no cold start declared)"
    assert engine.ready is False, "the next job re-checks the endpoint"


def test_retries_cover_the_cold_start_the_backend_declares() -> None:
    """`min_replica: 0` means the first job after an idle spell is
    answered 503 while the endpoint wakes. Giving up in six seconds
    against a four-minute wake-up loses that job's speakers."""
    slept: list[float] = []
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        # Answers only once the endpoint has had its declared wake-up.
        if sum(slept) < 200:
            return httpx.Response(503, text="scaling up")
        return httpx.Response(200, json=TWO_SPEAKERS)

    engine = _engine(handler, cold_start_seconds=240)
    engine._sleep = slept.append  # noqa: SLF001

    diar = engine.diarize(_pcm(), 16_000, hints=DiarizationHints())

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert sum(slept) >= 200, f"gave up after {sum(slept)}s of a 240s cold start"
    assert len(calls) > 3


def test_a_rejected_request_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(422, text="num_speakers=9 is outside 1..8")

    engine = _engine(handler)

    with pytest.raises(DiarizationRequestError):
        engine.diarize(_pcm(), 16_000, hints=DiarizationHints())

    assert len(calls) == 1, "4xx is our request; retrying only costs GPU minutes"


def test_a_reply_this_client_cannot_read_is_refused_not_guessed() -> None:
    older = dict(TWO_SPEAKERS, wire_version=WIRE_VERSION + 1)
    engine = _engine(lambda request: httpx.Response(200, json=older))

    with pytest.raises(WirePayloadError):
        engine.diarize(_pcm(), 16_000, hints=DiarizationHints())


def test_no_float_vector_can_reach_the_worker_through_this_engine() -> None:
    """A server that smuggles embeddings must not get them onto the
    object the worker holds — not in a field, not stashed whole."""
    smuggled = dict(TWO_SPEAKERS, speaker_embeddings=[[0.1] * 192])
    engine = _engine(lambda request: httpx.Response(200, json=smuggled))

    diar = engine.diarize(_pcm(), 16_000, hints=DiarizationHints())

    vectors = [v for v in _every_value(diar) if _looks_like_an_embedding(v)]
    assert vectors == [], "a float vector reached the worker"
    assert not any("embedding" in name for name in _every_name(diar))


def _every_value(root: Any, depth: int = 0) -> list[Any]:
    """Every value reachable from an object, attributes included."""
    if depth > 6:
        return []
    out = [root]
    children: list[Any] = []
    if isinstance(root, dict):
        children = list(root.keys()) + list(root.values())
    elif isinstance(root, (list, tuple, set)):
        children = list(root)
    elif hasattr(root, "__dict__"):
        children = list(vars(root).values())
    for child in children:
        out.extend(_every_value(child, depth + 1))
    return out


def _every_name(root: Any, depth: int = 0) -> list[str]:
    if depth > 6 or not hasattr(root, "__dict__"):
        return []
    names = list(vars(root))
    for value in vars(root).values():
        names.extend(_every_name(value, depth + 1))
    return names


def _looks_like_an_embedding(value: Any) -> bool:
    if isinstance(value, np.ndarray):
        return bool(value.size >= 32)
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 32
        and all(isinstance(x, float) for x in value)
    )


def test_the_remote_path_produces_the_same_labels_as_the_in_process_one() -> None:
    """The endpoint runs the same engine, so the worker must end up with
    the same timeline it would have built in-process — including the
    fact that unattributed evidence is NOT a speaker."""
    from diarization.attribution import UNKNOWN
    from diarization.offline import OfflineDiarization, _assign_display_names
    from diarization.wire import to_payload

    segments = [
        SpeakerSegment(start_ms=0, end_ms=5_000, label="A", confidence=1.0),
        SpeakerSegment(start_ms=5_000, end_ms=6_000, label=UNKNOWN, confidence=0.0),
        SpeakerSegment(start_ms=6_000, end_ms=12_000, label="B", confidence=1.0),
    ]
    in_process = OfflineDiarization(
        segments=segments,
        display_names=_assign_display_names(segments),
        duration_ms=12_000,
        config=OfflineDiarizationConfig(),
    )
    payload = to_payload(in_process, model_id="m", seconds=1.0)
    engine = _engine(lambda request: httpx.Response(200, json=payload))

    remote = engine.diarize(_pcm(12.0), 16_000, hints=DiarizationHints())

    assert remote.speakers == in_process.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert [(t.start_ms, t.end_ms, t.speaker) for t in remote.turns] == [
        (t.start_ms, t.end_ms, t.speaker) for t in in_process.turns
    ]
    assert remote.attribute(5_200, 5_800) == in_process.attribute(5_200, 5_800)


async def test_health_decides_whether_the_backend_is_usable_at_all() -> None:
    engine = _engine(
        lambda request: httpx.Response(200, json={"status": "ok", "authenticated": True})
    )
    await engine.ensure_loaded()
    assert engine.ready is True

    refused = _engine(lambda request: httpx.Response(401, text="bad token"))
    with pytest.raises(DiarizationUnavailableError):
        await refused.ensure_loaded()
    assert refused.last_error == "auth"


async def test_a_wrong_token_is_a_startup_error_not_a_week_of_missing_speakers() -> None:
    """The endpoint's health is open (the platform probe has no token),
    so it reports whether it WOULD accept us. Without this check a wrong
    token means every job quietly completes with no speakers."""
    engine = _engine(
        lambda request: httpx.Response(
            200, json={"status": "ok", "loaded": True, "authenticated": False}
        )
    )

    with pytest.raises(DiarizationUnavailableError, match="token"):
        await engine.ensure_loaded()

    assert engine.ready is False and engine.last_error == "auth"


def test_our_token_travels_in_its_own_header_as_well_as_the_bearer() -> None:
    """A managed endpoint's gateway consumes `Authorization` for its own
    check, so the container reads our token from its own header."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=TWO_SPEAKERS)

    engine = HttpDiarizer(
        backend="hf_eu_diar",
        base_url="http://diar.test",
        model_id="m",
        auth_token="hf-token",
        server_token="server-token",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )

    engine.diarize(_pcm(1.0), 16_000, hints=DiarizationHints())

    assert seen["authorization"] == "Bearer hf-token"
    assert seen["x-mdx-diar-token"] == "server-token"


def test_one_token_is_sent_in_both_places_when_there_is_only_one() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=TWO_SPEAKERS)

    engine = HttpDiarizer(
        backend="dev_mac_diar",
        base_url="http://diar.test",
        model_id="m",
        auth_token="only-token",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )

    engine.diarize(_pcm(1.0), 16_000, hints=DiarizationHints())

    assert seen["authorization"] == "Bearer only-token"
    assert seen["x-mdx-diar-token"] == "only-token", "a bare container reads the same value"


def test_tracing_headers_never_reach_the_endpoint() -> None:
    """httpx is instrumented globally and the worker's spans carry job
    and tenant ids; the endpoint is told nothing about whose audio it is."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=TWO_SPEAKERS)

    engine = HttpDiarizer(
        backend="hf_eu_diar",
        base_url="http://diar.test",
        model_id="m",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    # What the OTel httpx instrumentation would have injected.
    engine._client.headers.update(  # noqa: SLF001
        {"traceparent": "00-4bf92f-00f067aa-01", "tracestate": "mdx=1", "baggage": "job=42"}
    )

    engine.diarize(_pcm(1.0), 16_000, hints=DiarizationHints())

    assert not {"traceparent", "tracestate", "baggage"} & set(seen)


def test_the_call_budget_grows_with_the_recording_and_the_cold_start() -> None:
    seen: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout", {}).get("read"))
        return httpx.Response(200, json=TWO_SPEAKERS)

    engine = _engine(handler, cold_start_seconds=240, timeout_seconds=1800)
    engine.diarize(_pcm(600.0), 16_000, hints=DiarizationHints())

    assert seen == [600.0 * 0.5 + 240]


def test_a_recording_that_is_not_16_khz_never_leaves_the_worker() -> None:
    engine = _engine(lambda request: httpx.Response(200, json=TWO_SPEAKERS))

    with pytest.raises(ValueError, match="16000"):
        engine.diarize(_pcm(), 8_000, hints=DiarizationHints())
