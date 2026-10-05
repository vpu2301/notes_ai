"""The three backends get the same plan and the same guards.

The cassette is a mixed German / English recording; through ``decode_recording`` on
``dev_mac_asr``, ``hf_eu_asr`` and ``inproc_cpu_asr`` the runs, languages, labels and
markers must be identical, and ``guards.apply`` must run once per decode.
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

from asr_worker import chunks, guards, processor, vad
from asr_worker.chunks import LanguageGuess
from asr_worker.config import settings
from asr_worker.inference import WhisperEngine
from models import HTTPASRProvider, InProcASRProvider

REPO = Path(__file__).resolve().parents[4]
CASSETTE = json.loads(
    (REPO / "tests/fixtures/eval/asr/cassettes/mixed_de_en_whispercpp.json").read_text("utf-8")
)
RUNS = [vad.SpeechSegment(a, b) for a, b in CASSETTE["runs"]]
RUN_LANGUAGES = CASSETTE["run_languages"]


class _LID:
    """One identifier for all three backends: what the planner decides must
    not depend on who decodes."""

    source = "local"

    async def recording_language(self, _sample: np.ndarray) -> LanguageGuess:
        return LanguageGuess(CASSETTE["recording_language"], 0.9, {})

    async def run_language(self, pcm: np.ndarray) -> LanguageGuess:
        # Runs are identified in order; the stand-in knows the answers.
        k = self.calls
        self.calls += 1
        lang = RUN_LANGUAGES[k]
        return LanguageGuess(lang, 0.95, {lang: 0.95, CASSETTE["recording_language"]: 0.02})

    def __init__(self) -> None:
        self.calls = 0


def _speaches(reply: dict[str, Any]) -> dict[str, Any]:
    """The whisper.cpp reply as Speaches (faster-whisper) shapes it."""
    words = []
    segments = []
    for seg in reply["segments"]:
        words.extend(
            {
                "word": w["word"].strip(),
                "start": w["start"],
                "end": w["end"],
                "probability": w["probability"],
            }
            for w in seg.get("words", [])
        )
        segments.append(
            {
                "id": seg["id"],
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "avg_logprob": seg.get("avg_logprob", -0.1),
                "no_speech_prob": seg.get("no_speech_prob", 0.01),
                "compression_ratio": 1.2,
            }
        )
    return {
        "language": reply["language"],
        "duration": reply["duration"],
        "segments": segments,
        "words": words,
    }


def _http(shape: str) -> HTTPASRProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        lang = body.split(b'name="language"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode()
        reply = CASSETTE["groups"][lang]
        return httpx.Response(200, json=reply if shape == "whispercpp" else _speaches(reply))

    provider = HTTPASRProvider(
        backend="dev_mac_asr" if shape == "whispercpp" else "hf_eu_asr",
        base_url="http://test",
        model_id="whisper",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test"),
    )
    provider._loaded = True
    return provider


def _fw(seg: Any, offset_ms: int) -> SimpleNamespace:
    return SimpleNamespace(
        start=(seg.start_ms - offset_ms) / 1000,
        end=(seg.end_ms - offset_ms) / 1000,
        text=" " + seg.text,
        no_speech_prob=0.01,
        avg_logprob=-0.1,
        compression_ratio=1.2,
        words=[
            SimpleNamespace(
                word=" " + w.text,
                start=(w.start_ms - offset_ms) / 1000,
                end=(w.end_ms - offset_ms) / 1000,
                probability=w.probability,
            )
            for w in seg.words
        ],
    )


def _inproc(reference: Any) -> InProcASRProvider:
    """The engine, its model replaced by one that returns what the HTTP
    decode found inside the run it is given."""
    engine = WhisperEngine()
    engine._loaded = True
    runs = iter(RUNS)

    def transcribe(_chunk: np.ndarray, **_kw: Any) -> tuple[list[SimpleNamespace], None]:
        run = next(runs)
        inside = [s for s in reference.segments if run.start_ms <= s.start_ms < run.end_ms]
        return [_fw(s, run.start_ms) for s in inside], None

    engine._model = SimpleNamespace(transcribe=transcribe)
    return InProcASRProvider(engine)


@pytest.fixture(autouse=True)
def _plan_inputs(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    monkeypatch.setattr(vad, "speech_runs", lambda _pcm, **_kw: vad.SpeechRuns(runs=list(RUNS)))

    async def identifier(_provider: Any) -> _LID:
        return _LID()

    monkeypatch.setattr(chunks, "identifier_for", identifier)
    monkeypatch.setattr(settings, "asr_second_pass_enabled", False)
    calls: list[int] = []
    real = guards.apply

    def spy(output: Any, speech: Any) -> Any:
        calls.append(1)
        return real(output, speech)

    monkeypatch.setattr(guards, "apply", spy)
    return calls


async def _decode(provider: Any) -> Any:
    pcm = np.zeros(CASSETTE["audio_ms"] * 16, dtype=np.float32)
    return await processor.decode_recording(
        SimpleNamespace(engine=provider),
        pcm,
        stereo=None,
        language="auto",
        prompt=None,
        first_frame_offset_ms=None,
        timeout=60,
        deadline=time.monotonic() + 60,
        should_cancel=None,
        job_id=UUID(int=0),
    )


def _fingerprint(output: Any) -> list[tuple[int, str | None]]:
    """Per segment: which run it lies in, and its language label."""
    out = []
    for seg in output.segments:
        k = next(i for i, r in enumerate(RUNS) if r.start_ms <= seg.start_ms < r.end_ms)
        out.append((k, seg.language))
    return out


async def test_the_three_backends_share_runs_languages_and_guards(_plan_inputs: list[int]) -> None:
    mac = await _decode(_http("whispercpp"))
    hf = await _decode(_http("speaches"))
    inproc = await _decode(_inproc(mac))
    assert len(_plan_inputs) == 3, "guards.apply ran once per decode, for every backend"
    assert _fingerprint(mac) == _fingerprint(hf) == _fingerprint(inproc)
    # The English run is labelled English, the German ones carry no label.
    assert {lang for _k, lang in _fingerprint(mac)} == {None, "en"}
    assert {k for k, lang in _fingerprint(mac) if lang == "en"} == {1}
    for out in (mac, hf, inproc):
        assert out.language == "de"
        assert out.diagnostics.other_language_chunks == 1
        assert out.noise == mac.noise
    assert [s.text for s in mac.segments] == [s.text for s in hf.segments]


async def test_whisper_cpp_reports_no_compression_ratio_and_says_so(
    _plan_inputs: list[int],
) -> None:
    mac = await _decode(_http("whispercpp"))
    hf = await _decode(_http("speaches"))
    assert mac.diagnostics.gate_unavailable.get("compression_ratio", 0) == len(mac.segments)
    assert "compression_ratio" not in hf.diagnostics.gate_unavailable


async def test_a_failed_group_is_a_backend_error_gap_not_an_empty_transcript(
    _plan_inputs: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        lang = body.split(b'name="language"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode()
        if lang == "en":
            return httpx.Response(400, json={"error": "bad audio"})
        return httpx.Response(200, json=CASSETTE["groups"][lang])

    provider = HTTPASRProvider(
        backend="dev_mac_asr",
        base_url="http://test",
        model_id="whisper",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test"),
    )
    provider._loaded = True
    monkeypatch.setattr(settings, "asr_second_pass_enabled", True)
    out = await _decode(provider)
    assert [e.start_ms for e in out.diagnostics.backend_errors] == [RUNS[1].start_ms]
    assert out.segments, "the German groups still reach the transcript"
    causes = {g.cause for g in out.diagnostics.coverage.gaps}
    assert causes == {"backend_error"}
