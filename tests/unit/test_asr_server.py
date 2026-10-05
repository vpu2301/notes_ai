"""Sprint TQ4 T1 — deploy/asr-server: the Parakeet reply format and the
server's contract, with a stand-in engine (no model, no GPU)."""

from __future__ import annotations

import importlib
import io
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

SERVER = Path(__file__).resolve().parents[2] / "deploy" / "asr-server"
sys.path.insert(0, str(SERVER))

import parakeet_format as pf  # noqa: E402


def test_tokens_join_into_words_at_their_leading_space() -> None:
    # The real shape onnx-asr returns for "Heute … Handala." (recorded 2026-10-01).
    tokens = [" He", "ute", " spre", "chen", " wir", " über", " H", "and", "ala", "."]
    starts = [0.0, 0.16, 0.4, 0.64, 0.8, 0.96, 1.12, 1.36, 1.6, 1.76]
    logprobs = [-0.01, -0.02, -0.01, -0.01, -0.3, -0.01, -0.7, -0.05, -0.1, -0.01]
    words = pf.words_from_tokens(tokens, starts, logprobs, duration=2.0)
    assert [w.word for w in words] == ["Heute", "sprechen", "wir", "über", "Handala."]
    assert [(w.start, w.end) for w in words] == [
        (0.0, 0.4),
        (0.4, 0.8),
        (0.8, 0.96),
        (0.96, 1.12),
        (1.12, 1.84),
    ]
    # A pause after a word does not stretch it to the next one.
    paused = pf.words_from_tokens([" Ja", " gut"], [0.0, 3.0], None)
    assert paused[0].end == pf.LAST_TOKEN_MAX_S
    handala = words[-1]
    assert handala.probability == pytest.approx(np.exp(-0.7)), "the least sure piece decides"


def test_the_last_word_never_ends_past_the_audio() -> None:
    (w,) = pf.words_from_tokens([" Ja"], [1.98], None, duration=2.0)
    assert (w.start, w.end, w.probability) == (1.98, 2.0, None)


def test_segments_cut_at_sentence_ends_pauses_and_thirty_seconds() -> None:
    words = [
        pf.Word("Guten", 0.0, 0.3),
        pf.Word("Morgen.", 0.3, 0.7),
        pf.Word("Wir", 0.8, 1.0),
        pf.Word("beginnen", 1.0, 1.4),
        pf.Word("jetzt", 3.0, 3.3),  # 1.6 s pause
    ]
    segs = pf.segments_from_words(words)
    assert [(s["start"], s["end"], s["text"]) for s in segs] == [
        (0.0, 0.7, " Guten Morgen."),
        (0.8, 1.4, " Wir beginnen"),
        (3.0, 3.3, " jetzt"),
    ]
    long = [pf.Word(f"w{k}", k * 0.5, k * 0.5 + 0.4) for k in range(80)]
    assert all(s["end"] - s["start"] <= pf.SEGMENT_MAX_S for s in pf.segments_from_words(long))


def test_language_is_echoed_only_when_pinned_and_no_quality_fields_are_sent() -> None:
    words = [pf.Word("Hallo.", 0.0, 0.5, 0.9)]
    auto = pf.verbose_json(words, duration=1.0, language="auto")
    pinned = pf.verbose_json(words, duration=1.0, language="de")
    assert "language" not in auto and pinned["language"] == "de"
    seg = auto["segments"][0]
    assert not {"no_speech_prob", "avg_logprob", "compression_ratio"} & set(seg)
    assert auto["words"] == [{"word": "Hallo.", "start": 0.0, "end": 0.5, "probability": 0.9}]


# ── The app, with a stand-in engine ──────────────────────────────────


class _Engine:
    model_id = "stand-in"

    def __init__(self) -> None:
        self.loaded = 0
        self.seen: list[int] = []

    def load(self) -> None:
        self.loaded += 1

    def transcribe(self, pcm: np.ndarray) -> list[Any]:
        self.seen.append(len(pcm))
        return [pf.Word("Hallo", 0.1, 0.4, 0.95), pf.Word("Welt.", 0.4, 0.8, 0.9)]


def _wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buf.getvalue()


def _client(monkeypatch: pytest.MonkeyPatch, **env: str) -> tuple[TestClient, _Engine]:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    engine = _Engine()
    monkeypatch.setattr(app_mod, "build", lambda _runtime: engine)
    return TestClient(app_mod.app), engine


def test_the_route_answers_verbose_json_and_pins_the_hub_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = _client(monkeypatch, MDX_ASR_SERVER_TOKEN="t0k")
    import os

    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"
    with client:
        r = client.post(
            "/v1/audio/transcriptions",
            headers={"x-mdx-asr-token": "t0k"},
            files={"file": ("a.wav", _wav(), "audio/wav")},
            data={"language": "de", "response_format": "verbose_json", "prompt": "ignored"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["text"], body["language"], len(body["words"])) == ("Hallo Welt.", "de", 2)
    assert engine.loaded == 1 and engine.seen == [16_000]


def test_without_the_token_nothing_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    client, engine = _client(monkeypatch, MDX_ASR_SERVER_TOKEN="t0k")
    with client:
        r = client.post("/v1/audio/transcriptions", files={"file": ("a.wav", _wav(), "audio/wav")})
        health = client.get("/health")
    assert r.status_code == 401 and engine.seen == []
    assert health.status_code == 200 and health.json()["loaded"] is False


def test_the_server_refuses_to_start_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MDX_ASR_SERVER_TOKEN", raising=False)
    monkeypatch.delenv("MDX_ASR_SERVER_ALLOW_ANONYMOUS", raising=False)
    client, _engine = _client(monkeypatch)
    with pytest.raises(RuntimeError, match="MDX_ASR_SERVER_TOKEN"), client:
        pass
