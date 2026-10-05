"""Sprint TQ2 T1/T4 — the worker's plan and the non-speech markers."""

from __future__ import annotations

import numpy as np
import pytest

from asr_worker import chunks
from asr_worker.chunks import LanguageGuess, other_language
from asr_worker.config import settings
from asr_worker.vad import SpeechSegment

SR = 16_000


class _LID:
    source = "local"

    def __init__(self, recording: str, runs: list[LanguageGuess | None]) -> None:
        self._recording = recording
        self._runs = iter(runs)
        self.run_calls = 0

    async def recording_language(self, _sample: np.ndarray) -> LanguageGuess:
        return LanguageGuess(self._recording, 0.93)

    async def run_language(self, _pcm: np.ndarray) -> LanguageGuess | None:
        self.run_calls += 1
        return next(self._runs)


def _runs(*spans: tuple[int, int]) -> list[SpeechSegment]:
    return [SpeechSegment(a, b) for a, b in spans]


@pytest.fixture(autouse=True)
def _lid_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_chunk_language_id", True)


async def test_auto_asks_the_identifier_and_labels_a_sure_other_language_run() -> None:
    pcm = np.zeros(SR * 20, dtype=np.float32)
    lid = _LID(
        "de",
        [
            LanguageGuess("de", 0.9, {"de": 0.9}),
            LanguageGuess("en", 0.95, {"en": 0.95, "de": 0.02}),
        ],
    )
    plan = await chunks.plan(pcm, _runs((0, 5000), (6000, 11_000)), language="auto", lid=lid)
    assert (plan.language, plan.language_detected, plan.language_probability) == ("de", True, 0.93)
    assert [(r.language, r.other_language) for r in plan.runs] == [("de", False), ("en", True)]
    assert plan.other_language_runs == 1 and plan.language_id == "local"


async def test_an_undecided_or_unsure_run_stays_in_the_recording_language() -> None:
    pcm = np.zeros(SR * 20, dtype=np.float32)
    lid = _LID(
        "uk",
        [
            None,  # the identifier could not decide
            LanguageGuess("en", 0.55, {"en": 0.55, "uk": 0.1}),  # not sure enough
            LanguageGuess("en", 0.8, {"en": 0.8, "uk": 0.35}),  # uk not excluded
            LanguageGuess("ru", 0.9, {"ru": 0.9, "uk": 0.05}),  # not a product language
        ],
    )
    spans = _runs((0, 3000), (4000, 7000), (8000, 11_000), (12_000, 15_000))
    plan = await chunks.plan(pcm, spans, language="uk", lid=lid)
    assert [r.language for r in plan.runs] == ["uk"] * 4
    assert plan.language_detected is False


async def test_short_runs_are_not_identified() -> None:
    pcm = np.zeros(SR * 5, dtype=np.float32)
    lid = _LID("de", [])
    plan = await chunks.plan(pcm, _runs((0, 1500), (2000, 3900)), language="de", lid=lid)
    assert lid.run_calls == 0 and [r.language for r in plan.runs] == ["de", "de"]


async def test_no_identifier_means_every_run_in_the_recording_language() -> None:
    lid = _LID("de", [])
    lid.source = "unavailable"
    plan = await chunks.plan(
        np.zeros(SR * 10, dtype=np.float32), _runs((0, 5000)), language="de", lid=lid
    )
    assert lid.run_calls == 0 and plan.language_id == "unavailable"


def test_the_rule_moved_intact() -> None:
    assert other_language(LanguageGuess("en", 0.6, {"en": 0.6, "de": 0.2}), recording="de") == "en"
    assert other_language(LanguageGuess("en", 0.59, {"en": 0.59}), recording="de") is None
    assert other_language(LanguageGuess("en", 0.9, {"en": 0.9, "de": 0.21}), recording="de") is None
    assert other_language(LanguageGuess("cy", 0.9, {"cy": 0.9}), recording="en") is None


# ── Non-speech markers ───────────────────────────────────────────────


def _tone(seconds: float) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (0.1 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 330 * t)) / 2).astype(
        np.float32
    )


def test_music_silence_and_noise_are_told_apart() -> None:
    rng = np.random.default_rng(0)
    speech = np.zeros(SR * 3, dtype=np.float32) + 0.0  # stands for speech; VAD says so below
    pcm = np.concatenate(
        [
            speech,
            _tone(8),
            np.zeros(SR * 7, dtype=np.float32),
            (rng.standard_normal(SR * 6) * 0.1).astype(np.float32),
            speech,
            np.zeros(SR * 2, dtype=np.float32),  # < 5 s: not marked
        ]
    )
    total_ms = len(pcm) * 1000 // SR
    heard = [SpeechSegment(0, 3000), SpeechSegment(24_000, 27_000)]
    marks = chunks.nonspeech_regions(pcm, heard)
    assert [(m.kind, m.start_ms, m.end_ms) for m in marks] == [
        ("music", 3000, 11_000),
        ("silence", 11_000, 18_000),
        ("noise", 18_000, 24_000),
    ]
    assert total_ms - 27_000 < chunks.NONSPEECH_MIN_MS


def test_no_region_shorter_than_five_seconds_is_marked() -> None:
    pcm = np.zeros(SR * 10, dtype=np.float32)
    assert (
        chunks.nonspeech_regions(pcm, [SpeechSegment(0, 3000), SpeechSegment(7000, 10_000)]) == []
    )
