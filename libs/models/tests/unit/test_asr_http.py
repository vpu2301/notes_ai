from __future__ import annotations

import asyncio
from typing import Any

import httpx
import numpy as np
import pytest

from models import ErrorKind, HTTPASRProvider, ProviderError, TranscriptionCancelledError
from models.asr_http import _to_output

from .conftest_helpers import cassette, json_response, mock_client


def _provider(handler: Any, **kw: Any) -> HTTPASRProvider:
    return HTTPASRProvider(
        backend="dev_mac_asr",
        base_url="http://test",
        model_id="whisper",
        client=mock_client(handler, "http://test"),
        **kw,
    )


async def test_probe_accepts_server_with_words_and_transcribes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(200, cassette("whispercpp_verbose.json"))

    p = _provider(handler)
    assert p.is_loaded is False
    await p.warm_up()
    assert p.is_loaded is True and p.model_name == "whisper"
    assert seen[0].url.path == "/v1/audio/transcriptions"
    assert (
        b'name="timestamp_granularities[]"' in seen[0].content
        and b"verbose_json" in seen[0].content
    )

    out = await p.transcribe(np.zeros(16_000, dtype=np.float32), language="en", prompt="Phoenix")
    assert out.language == "en" and out.language_detected is False
    assert len(out.segments) == 1
    seg = out.segments[0]
    # Real whisper.cpp reply: punctuation tokens are glued onto the previous
    # word, matching the in-process faster-whisper shape ("1,").
    assert [w.text for w in seg.words][:4] == ["Testing", "1,", "2,", "3."]
    assert seg.words[-1].text == "now."
    assert out.language_probability is not None and out.language_probability > 0.9
    assert (
        seg.words[0].start_ms == 50 and seg.words[0].end_ms == 410 and seg.words[-1].end_ms == 2680
    )
    assert seg.start_ms == 0 and seg.end_ms == 2680
    assert 0.8 < seg.avg_confidence <= 1.0
    assert out.metadata.model == "whisper"
    assert b'name="prompt"' in seen[1].content and b"Phoenix" in seen[1].content


async def test_probe_rejects_server_without_word_timestamps() -> None:
    p = _provider(lambda _r: json_response(200, cassette("nowords_verbose.json")))
    with pytest.raises(ProviderError, match="asr_backend_without_word_timestamps"):
        await p.warm_up()
    assert p.is_loaded is False


def test_top_level_words_are_assigned_to_segments_by_time() -> None:
    out = _to_output(
        cassette("openai_verbose_topwords.json"),
        model="w",
        requested_language="auto",
        audio_seconds=2.77,
        infer_seconds=0.1,
    )
    assert out.language == "en" and out.language_detected is True
    assert [len(s.words) for s in out.segments] == [4, 4]
    assert out.segments[1].words[0].text == "the" and out.segments[1].words[0].start_ms == 1300


def test_words_only_response_without_segments_becomes_one_segment() -> None:
    body = cassette("openai_verbose_topwords.json")
    del body["segments"]
    out = _to_output(
        body, model="w", requested_language="de", audio_seconds=2.77, infer_seconds=0.1
    )
    assert len(out.segments) == 1 and len(out.segments[0].words) == 8
    assert out.language == "en"  # server said "english"; it wins over the request


async def test_language_omitted_for_auto_and_sent_otherwise() -> None:
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return json_response(200, cassette("whispercpp_verbose.json"))

    p = _provider(handler)
    await p.warm_up()
    await p.transcribe(np.zeros(1600, dtype=np.float32), language="auto", prompt=None)
    await p.transcribe(np.zeros(1600, dtype=np.float32), language="de", prompt=None)
    assert b'name="language"' not in seen[1]
    assert b'name="language"\r\n\r\nde' in seen[2]


async def test_status_mapping_for_asr() -> None:
    for status, cold, kind in (
        (503, 240, ErrorKind.WARMING),
        (503, 0, ErrorKind.UNAVAILABLE),
        (401, 0, ErrorKind.AUTH),
        (413, 0, ErrorKind.CONTEXT_EXCEEDED),
        (429, 0, ErrorKind.RATE_LIMITED),
    ):
        p = _provider(lambda _r, s=status: httpx.Response(s, text="err"), cold_start_seconds=cold)
        with pytest.raises(ProviderError) as exc:
            await p.warm_up()
        assert exc.value.kind is kind


async def test_transcribe_before_warm_up_is_a_programming_error() -> None:
    p = _provider(lambda _r: json_response(200, cassette("whispercpp_verbose.json")))
    with pytest.raises(RuntimeError, match="warm_up"):
        await p.transcribe(np.zeros(1600, dtype=np.float32), language="en", prompt=None)


async def test_cancel_request_aborts_in_flight_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import models.asr_http as mod

    monkeypatch.setattr(mod, "CANCEL_POLL_S", 0.01)

    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return json_response(200, cassette("whispercpp_verbose.json"))

    p = HTTPASRProvider(
        backend="b",
        base_url="http://test",
        model_id="w",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test"),
    )
    p._loaded = True

    async def cancel() -> bool:
        return True

    with pytest.raises(TranscriptionCancelledError):
        await p.transcribe(
            np.zeros(1600, dtype=np.float32), language="en", prompt=None, should_cancel=cancel
        )


async def test_warming_is_absorbed_within_cold_start_budget() -> None:
    calls = 0
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, text="scaling to 1 replica", headers={"retry-after": "20"})
        return json_response(200, cassette("whispercpp_verbose.json"))

    p = HTTPASRProvider(
        backend="hf_eu_asr",
        base_url="http://test",
        model_id="w",
        cold_start_seconds=240,
        client=mock_client(handler, "http://test"),
        sleep=sleep,
    )
    p._loaded = True
    out = await p.transcribe(np.zeros(1600, dtype=np.float32), language="en", prompt=None)
    assert out.segments and calls == 3 and slept == [20.0, 20.0]


async def test_warming_beyond_budget_surfaces_as_warming() -> None:
    async def sleep(_s: float) -> None:
        return None

    p = HTTPASRProvider(
        backend="hf_eu_asr",
        base_url="http://test",
        model_id="w",
        cold_start_seconds=60,
        client=mock_client(lambda _r: httpx.Response(503, text="scaling"), "http://test"),
        sleep=sleep,
    )
    p._loaded = True
    with pytest.raises(ProviderError) as exc:
        await p.transcribe(np.zeros(1600, dtype=np.float32), language="en", prompt=None)
    assert exc.value.kind is ErrorKind.WARMING and exc.value.retryable


def test_whisper_cpp_subword_tokens_become_words() -> None:
    """Sprint TQ2: whisper.cpp's word list is decoder tokens; a token with
    no leading space continues the word before it."""
    body = {
        "language": "de",
        "segments": [
            {
                "text": " im Nahen Osten.",
                "start": 0.0,
                "end": 1.2,
                "words": [
                    {"word": " im", "start": 0.0, "end": 0.2, "probability": 0.9},
                    {"word": " Nah", "start": 0.2, "end": 0.4, "probability": 0.8},
                    {"word": "en", "start": 0.4, "end": 0.5, "probability": 0.95},
                    {"word": " O", "start": 0.6, "end": 0.7, "probability": 0.7},
                    {"word": "sten", "start": 0.7, "end": 1.0, "probability": 0.9},
                    {"word": ".", "start": 1.0, "end": 1.1, "probability": 0.99},
                ],
            }
        ],
    }
    (seg,) = _to_output(
        body, model="w", requested_language="de", audio_seconds=1.2, infer_seconds=0.1
    ).segments
    assert [w.text for w in seg.words] == ["im", "Nahen", "Osten."]
    assert (seg.words[1].start_ms, seg.words[1].end_ms, seg.words[1].probability) == (200, 500, 0.8)


def test_speaches_words_without_spaces_stay_words() -> None:
    body = {
        "language": "en",
        "segments": [{"text": "one two", "start": 0.0, "end": 1.0}],
        "words": [
            {"word": "one", "start": 0.0, "end": 0.4, "probability": 0.9},
            {"word": "two", "start": 0.5, "end": 1.0, "probability": 0.9},
        ],
    }
    (seg,) = _to_output(
        body, model="w", requested_language="en", audio_seconds=1.0, infer_seconds=0.1
    ).segments
    assert [w.text for w in seg.words] == ["one", "two"]


def test_a_transducer_reply_is_read_without_its_missing_fields() -> None:
    """Sprint TQ4: Parakeet (deploy/asr-server) names no language and sends
    no segment-quality numbers. Recorded from the server, 2026-10-01."""
    body = cassette("parakeet_verbose.json")
    out = _to_output(
        body, model="parakeet", requested_language="auto", audio_seconds=30.0, infer_seconds=1.0
    )
    assert out.language_detected is False, "a fallback language is not a detected one"
    assert out.segments and all(seg.words for seg in out.segments)
    words = [w for seg in out.segments for w in seg.words]
    assert all(a.start_ms <= b.start_ms for a, b in zip(words, words[1:], strict=False))
    assert all(
        (d.no_speech_prob, d.avg_logprob, d.compression_ratio) == (None, None, None)
        for d in out.diagnostics.segments
    )
    assert "word_probability" not in out.diagnostics.gate_unavailable


def test_words_without_probabilities_are_counted_for_the_gates() -> None:
    body = cassette("parakeet_verbose.json")
    for w in body["words"]:
        w.pop("probability", None)
    out = _to_output(
        body, model="parakeet", requested_language="en", audio_seconds=30.0, infer_seconds=1.0
    )
    assert out.diagnostics.gate_unavailable["word_probability"] == len(body["words"])
    assert out.language_detected is False and out.language == "en"
