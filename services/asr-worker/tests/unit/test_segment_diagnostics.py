"""Sprint TQ1 T5: the decoder's own numbers per segment reach
``diagnostics.segments`` through the job's path, for every backend.

Two replies of the HTTP backend: the recorded whisper.cpp one
(``libs/models/tests/cassettes/whispercpp_verbose.json``: ``no_speech_prob``
and ``avg_logprob``, no ``compression_ratio``) and one in the shape
Speaches / faster-whisper serves (all three). A missing number is ``None``,
never a failure. The in-process engine is covered with a stand-in model
object shaped like faster-whisper's segments.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import numpy as np
import pytest

from asr_worker import processor
from asr_worker.config import settings
from asr_worker.inference import WhisperEngine
from models import HTTPASRProvider


@pytest.fixture(autouse=True)
def _speech_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stand-in audio is zeros but stands for speech: VAD says so, so
    the TQ2 gates (which protect speech VAD heard) leave the text alone."""
    from asr_worker import vad as _vad

    def runs(pcm: np.ndarray, **_kw: Any) -> _vad.SpeechRuns:
        return _vad.SpeechRuns(runs=[_vad.SpeechSegment(0, max(1, int(len(pcm) / 16)))])

    monkeypatch.setattr(_vad, "speech_runs", runs)


CASSETTES = Path(__file__).resolve().parents[4] / "libs" / "models" / "tests" / "cassettes"


def _http(body: dict[str, Any]) -> HTTPASRProvider:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = HTTPASRProvider(
        backend="dev_mac_asr",
        base_url="http://test",
        model_id="whisper",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test"),
    )
    provider._loaded = True  # the startup probe is test_asr_http's concern
    return provider


async def _decode(engine: Any, seconds: float = 3.0) -> Any:
    state = SimpleNamespace(engine=engine)
    pcm = np.zeros(int(16_000 * seconds), dtype=np.float32)
    return await processor.decode_recording(
        state,
        pcm,
        stereo=None,
        language="en",
        prompt=None,
        first_frame_offset_ms=None,
        timeout=60,
        deadline=time.monotonic() + 60,
        should_cancel=None,
        job_id=UUID(int=0),
    )


@pytest.fixture(autouse=True)
def _no_second_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_second_pass_enabled", False)


async def test_whisper_cpp_reply_records_what_it_has_and_null_for_the_rest() -> None:
    body = json.loads((CASSETTES / "whispercpp_verbose.json").read_text("utf-8"))
    out = await _decode(_http(body))
    (d,) = out.diagnostics.segments
    assert (d.start_ms, d.end_ms) == (0, 2680)
    assert d.language == "en"
    assert d.no_speech_prob is not None and 0.0 <= d.no_speech_prob <= 1.0
    assert d.avg_logprob is not None and d.avg_logprob <= 0.0
    assert d.compression_ratio is None
    assert d.second_pass is False


async def test_speaches_shape_records_all_three_numbers_and_the_empty_segment() -> None:
    body = {
        "language": "de",
        "duration": 3.0,
        "text": "Guten Morgen.",
        "segments": [
            {
                "id": 0,
                "start": 0.2,
                "end": 1.4,
                "text": " Guten Morgen.",
                "avg_logprob": -0.21,
                "compression_ratio": 0.9,
                "no_speech_prob": 0.02,
            },
            # A decoded segment with no text: dropped from the transcript,
            # still recorded — it is the decoder saying "non-speech here".
            {
                "id": 1,
                "start": 1.6,
                "end": 3.0,
                "text": " ",
                "avg_logprob": -1.3,
                "compression_ratio": 2.8,
                "no_speech_prob": 0.91,
            },
        ],
        "words": [
            {"word": "Guten", "start": 0.2, "end": 0.7, "probability": 0.98},
            {"word": "Morgen.", "start": 0.7, "end": 1.4, "probability": 0.97},
        ],
    }
    out = await _decode(_http(body))
    assert [s.text for s in out.segments] == ["Guten Morgen."]
    first, empty = out.diagnostics.segments
    assert (first.no_speech_prob, first.avg_logprob, first.compression_ratio) == (0.02, -0.21, 0.9)
    assert (empty.start_ms, empty.end_ms, empty.no_speech_prob) == (1600, 3000, 0.91)
    # TQ2: runs are sent with the language the worker planned (the job pins
    # "en" here); the diagnostics carry that, not the server's echo.
    assert {first.language, empty.language} == {"en"}


async def test_diagnostics_carry_numbers_and_times_never_text() -> None:
    body = json.loads((CASSETTES / "whispercpp_verbose.json").read_text("utf-8"))
    out = await _decode(_http(body))
    dumped = json.dumps([d.model_dump() for d in out.diagnostics.segments])
    assert "meeting" not in dumped.lower() and "testing" not in dumped.lower()


def _fw_segment(start: float, end: float, text: str, **numbers: float) -> SimpleNamespace:
    return SimpleNamespace(start=start, end=end, text=text, words=[], **numbers)


async def test_inproc_engine_records_each_decoded_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = WhisperEngine()
    engine._loaded = True
    engine._model = SimpleNamespace(
        transcribe=lambda *_a, **_k: (
            [
                _fw_segment(
                    0.0, 1.0, " Hallo.", no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.1
                ),
                _fw_segment(
                    1.0,
                    2.0,
                    " Vielen Dank.",
                    no_speech_prob=0.8,
                    avg_logprob=-1.1,
                    compression_ratio=float("nan"),
                ),
            ],
            None,
        )
    )
    monkeypatch.setattr(
        "asr_worker.inference.detect_speech",
        lambda _pcm: [SimpleNamespace(start_ms=500, end_ms=2500)],
    )
    monkeypatch.setattr(settings, "asr_chunk_language_id", False)
    out = await engine.transcribe(np.zeros(48_000, dtype=np.float32), language="de", prompt=None)
    a, b = out.diagnostics.segments
    assert (a.start_ms, a.end_ms, a.language) == (500, 1500, "de")
    assert (a.no_speech_prob, a.avg_logprob, a.compression_ratio) == (0.1, -0.3, 1.1)
    assert (b.start_ms, b.no_speech_prob) == (1500, 0.8)
    assert b.compression_ratio is None  # NaN is not stored
