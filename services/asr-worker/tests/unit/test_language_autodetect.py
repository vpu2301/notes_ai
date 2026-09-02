"""``language="auto"``: the engine identifies the language first, then
decodes every chunk in it. Pinned jobs never touch the detector."""

from __future__ import annotations

import numpy as np
import pytest

from asr_worker import inference as inf
from asr_worker.inference import LanguageGuess, WhisperEngine, _speech_sample
from asr_worker.vad import SpeechSegment


class _FakeModel:
    def __init__(self, answer: tuple[str, float] | Exception) -> None:
        self.answer = answer
        self.calls: list[int] = []

    def detect_language(self, pcm: np.ndarray, *, language_detection_segments: int = 1):  # type: ignore[no-untyped-def]
        self.calls.append(int(pcm.size))
        if isinstance(self.answer, Exception):
            raise self.answer
        code, prob = self.answer
        return code, prob, [(code, prob)]


class _FakeEngine(WhisperEngine):
    def __init__(self, model: _FakeModel) -> None:
        super().__init__()
        self._loaded = True
        self._model = model  # type: ignore[assignment]
        self.languages_run: list[str] = []

    def _run_chunk(self, chunk, language, prompt, offset_ms):  # type: ignore[no-untyped-def]
        self.languages_run.append(language)
        return []


def _speech(monkeypatch: pytest.MonkeyPatch, runs: int) -> None:
    segs = [SpeechSegment(start_ms=i * 1000, end_ms=(i + 1) * 1000) for i in range(runs)]
    monkeypatch.setattr(inf, "detect_speech", lambda _pcm: segs)


async def test_auto_detects_once_then_decodes_every_chunk_in_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeModel(("uk", 0.97))
    engine = _FakeEngine(model)
    _speech(monkeypatch, runs=4)

    out = await engine.transcribe(
        np.zeros(16_000 * 4, dtype=np.float32), language="auto", prompt=None
    )

    assert out.language == "uk"
    assert out.language_detected is True
    assert out.language_probability == pytest.approx(0.97)
    assert len(model.calls) == 1, "one identification for the whole recording"
    assert engine.languages_run == ["uk"] * 4


async def test_pinned_language_skips_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _FakeModel(("uk", 0.97))
    engine = _FakeEngine(model)
    _speech(monkeypatch, runs=2)

    out = await engine.transcribe(
        np.zeros(16_000 * 2, dtype=np.float32), language="en", prompt=None
    )

    assert out.language == "en"
    assert out.language_detected is False
    assert out.language_probability is None
    assert model.calls == []
    assert engine.languages_run == ["en", "en"]


def test_detector_failure_falls_back_instead_of_failing_the_job() -> None:
    engine = _FakeEngine(_FakeModel(RuntimeError("boom")))
    guess = engine.detect_language(np.zeros(16_000, dtype=np.float32))
    assert guess == LanguageGuess(language="en", probability=0.0)


def test_unusable_code_falls_back() -> None:
    engine = _FakeEngine(_FakeModel(("<|nospeech|>", 0.5)))
    assert engine.detect_language(np.zeros(16_000, dtype=np.float32)).language == "en"


def test_speech_sample_concatenates_speech_and_caps_length() -> None:
    pcm = np.arange(16_000 * 10, dtype=np.float32)
    speech = [
        SpeechSegment(start_ms=0, end_ms=1000),
        SpeechSegment(start_ms=5000, end_ms=8000),
    ]
    sample = _speech_sample(pcm, speech, seconds=2)
    assert sample.size == 16_000 * 2
    # Second run starts where the first ended — the silence in between is gone.
    assert sample[16_000] == pytest.approx(5000 * 16)


def test_speech_sample_without_speech_uses_the_head() -> None:
    pcm = np.zeros(16_000 * 10, dtype=np.float32)
    assert _speech_sample(pcm, [], seconds=3).size == 16_000 * 3
