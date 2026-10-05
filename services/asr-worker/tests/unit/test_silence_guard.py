"""A silent recording must come out as `no_speech`, never as a transcript.

Regression for NOTE-2026-00033: VAD hearing nothing handed Whisper the whole file,
and Whisper given silence plus a prompt wrote the prompt back.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from asr_worker import inference as inf
from asr_worker import vad
from asr_worker.inference import WhisperEngine, _is_prompt_echo
from asr_worker.vad import SpeechSegment

PROMPT = "Moderator, Gregor Gysi"


# --- the VAD: nothing heard is an empty answer ------------------------------


def test_silero_hears_nothing_in_silence() -> None:
    pytest.importorskip("silero_vad")
    vad._model = None  # force a real load, whatever an earlier test left
    silence = np.zeros(16_000 * 30, dtype=np.float32)
    assert vad.detect_speech(silence) == [], "silence must not become one 30 s speech run"


def test_stub_vad_still_covers_the_whole_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """The no-Silero dev fallback is unchanged: whole file, one segment."""
    monkeypatch.setattr(vad, "_model", "stub")
    monkeypatch.setattr(vad, "_get_speech_timestamps", "stub")
    assert vad.detect_speech(np.zeros(16_000 * 2, dtype=np.float32)) == [SpeechSegment(0, 2000)]


# --- the engine: no speech → no segments, no decoder call --------------------


class _Model:
    def __init__(self) -> None:
        self.detect_calls = 0
        self.transcribe_calls = 0

    def detect_language(self, pcm, *, language_detection_segments=1):  # type: ignore[no-untyped-def]
        self.detect_calls += 1
        return "de", 0.9, [("de", 0.9)]

    def transcribe(self, chunk, **kwargs):  # type: ignore[no-untyped-def]
        self.transcribe_calls += 1
        # What large-v3 does with a prompt over silence: it writes the prompt.
        seg = SimpleNamespace(
            text=" Gysi, Moderator.",
            start=0.0,
            end=2.0,
            words=None,
            avg_logprob=-0.2,
            no_speech_prob=0.93,
        )
        return iter([seg]), SimpleNamespace(language=kwargs.get("language"))


def _engine() -> tuple[WhisperEngine, _Model]:
    model = _Model()
    engine = WhisperEngine()
    engine._loaded = True
    engine._model = model  # type: ignore[assignment]
    return engine, model


async def test_no_speech_yields_no_segments_and_never_decodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inf, "detect_speech", lambda _pcm: [])
    engine, model = _engine()

    out = await engine.transcribe(
        np.zeros(16_000 * 60, dtype=np.float32), language="auto", prompt=PROMPT
    )

    assert out.segments == []
    assert out.metadata.vad_seconds_speech == 0.0
    assert model.transcribe_calls == 0, "silence must never reach the decoder"
    assert model.detect_calls == 0, "nor the language detector"
    assert out.language_detected is False


# --- the decoder: a prompt echoed over non-speech is dropped -----------------


async def test_prompt_echo_over_non_speech_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inf, "detect_speech", lambda _pcm: [SpeechSegment(0, 2000)])
    engine, model = _engine()

    out = await engine.transcribe(
        np.zeros(16_000 * 2, dtype=np.float32), language="de", prompt=PROMPT
    )

    assert model.transcribe_calls == 1
    assert out.segments == [], "the prompt written back over non-speech is not a transcript"


@pytest.mark.parametrize(
    ("text", "prompt", "no_speech_prob", "echo"),
    [
        ("Gysi, Moderator.", PROMPT, 0.93, True),  # the NOTE-2026-00033 shape
        ("Gysi, Moderator.", PROMPT, 0.10, False),  # said aloud: stays
        ("Moderator: Herr Gysi, bitte.", PROMPT, 0.93, False),  # more than the prompt: stays
        ("You. You. You.", PROMPT, 0.93, False),  # not the prompt; Whisper's own gate owns it
        ("Gysi, Moderator.", None, 0.93, False),  # no prompt, nothing to echo
    ],
)
def test_is_prompt_echo(text: str, prompt: str | None, no_speech_prob: float, echo: bool) -> None:
    assert _is_prompt_echo(text, prompt, no_speech_prob) is echo
