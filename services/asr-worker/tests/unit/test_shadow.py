"""The shadow ASR engine: numbers only, primary untouched, bounded, within budget."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from asr_models import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker import shadow
from asr_worker.config import settings


def _out(text: str) -> TranscriptionOutput:
    words = [
        WordTiming(text=w, start_ms=k * 300, end_ms=k * 300 + 250, probability=0.9)
        for k, w in enumerate(text.split())
    ]
    return TranscriptionOutput(
        language="de",
        segments=[
            Segment(text=text, start_ms=0, end_ms=len(words) * 300, words=words, avg_confidence=0.9)
        ],
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
    )


class _Redis:
    def __init__(self) -> None:
        self.used = 0.0

    async def incrbyfloat(self, _key: str, amount: float) -> float:
        self.used += amount
        return self.used

    async def expire(self, *_a: Any) -> None:
        return None


class _Engine:
    is_loaded = True


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_shadow_backend", "cand_parakeet_asr")
    monkeypatch.setattr(settings, "asr_shadow_budget_hours", 1.0)


def test_compare_keeps_numbers_and_never_text() -> None:
    primary = _out("Wir sprechen heute über Handala und Welchering")
    cand = _out("Wir sprechen heute über Handela und Welchering")
    diag = shadow.compare(primary, cand, backend="cand_parakeet_asr", rtf=0.05)
    assert (diag.words_primary, diag.words_shadow, diag.word_disagreement) == (
        7,
        7,
        round(1 / 7, 4),
    )
    assert (diag.name_forms_primary, diag.name_forms_shadow) == (2, 2)
    dumped = json.dumps(diag.model_dump())
    for word in ("Handala", "Handela", "Welchering", "sprechen"):
        assert word not in dumped
    assert all(len(v) <= 32 for v in diag.model_dump().values() if isinstance(v, str))


async def test_a_sampled_job_is_compared_and_the_primary_is_untouched() -> None:
    primary = _out("eins zwei drei")
    before = primary.model_dump_json()

    async def decode(_state: Any, **_kw: Any) -> TranscriptionOutput:
        return _out("eins zwei vier")

    diag = await shadow.run(
        _Engine(),
        redis=_Redis(),
        decode=decode,
        primary=primary,
        audio_seconds=60.0,
        decode_kwargs={},
    )
    assert diag is not None and diag.skipped is None and diag.word_disagreement == round(1 / 3, 4)
    assert primary.model_dump_json() == before


async def test_over_budget_the_shadow_does_not_run() -> None:
    redis = _Redis()
    redis.used = 3600.0  # the day's hour is spent
    calls: list[int] = []

    async def decode(_state: Any, **_kw: Any) -> TranscriptionOutput:
        calls.append(1)
        return _out("x")

    diag = await shadow.run(
        _Engine(),
        redis=redis,
        decode=decode,
        primary=_out("x"),
        audio_seconds=60.0,
        decode_kwargs={},
    )
    assert diag is not None and diag.skipped == "budget" and calls == []


async def test_a_failing_or_slow_shadow_is_counted_and_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(_state: Any, **_kw: Any) -> TranscriptionOutput:
        raise RuntimeError("endpoint down")

    diag = await shadow.run(
        _Engine(),
        redis=_Redis(),
        decode=broken,
        primary=_out("x"),
        audio_seconds=10.0,
        decode_kwargs={},
    )
    assert diag is not None and diag.skipped == "error"

    monkeypatch.setattr(settings, "asr_shadow_max_wait_seconds", 0.05)

    async def slow() -> None:
        await asyncio.sleep(1)

    late = await shadow.bounded(asyncio.create_task(slow()))
    assert late is not None and late.skipped == "timeout"


def test_sampling_follows_the_rate_and_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_shadow_rate", 0.2)
    assert shadow.sampled(lambda: 0.1) and not shadow.sampled(lambda: 0.3)
    monkeypatch.setattr(settings, "asr_shadow_backend", "")
    assert not shadow.sampled(lambda: 0.0)
