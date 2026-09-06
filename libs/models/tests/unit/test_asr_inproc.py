"""Parity: routing the worker's engine through the seam changes nothing.

Three deterministic fixtures go through the raw engine and through
``InProcASRProvider``; the serialised ``TranscriptionOutput`` must be
byte-identical.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from asr_models import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from models import InProcASRProvider, TranscriptionCancelledError, UsageRecord, set_usage_sink


class _FakeEngine:
    def __init__(self) -> None:
        self.loaded = False
        self.calls: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return "tiny"

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    @property
    def warmup_seconds(self) -> float:
        return 0.25

    def load(self) -> None:
        self.loaded = True

    async def transcribe(
        self, audio_pcm: np.ndarray, *, language: str, prompt: str | None, should_cancel: Any = None
    ) -> TranscriptionOutput:
        self.calls.append({"n": len(audio_pcm), "language": language, "prompt": prompt})
        if should_cancel is not None and await should_cancel():
            raise TranscriptionCancelledError("cancelled")
        n = len(audio_pcm)
        words = [
            WordTiming(text=f"w{i}", start_ms=i * 100, end_ms=i * 100 + 90, probability=0.9)
            for i in range(n // 16_000 + 1)
        ]
        seg = Segment(
            text=" ".join(w.text for w in words),
            start_ms=0,
            end_ms=words[-1].end_ms,
            words=words,
            avg_confidence=0.9,
        )
        return TranscriptionOutput(
            language=language if language != "auto" else "en",
            language_detected=language == "auto",
            segments=[seg],
            metadata=TranscriptionMetadata(
                model="tiny", vad_seconds_speech=n / 16_000, infer_seconds=0.01, beam_size=5
            ),
        )


FIXTURES = [
    (np.zeros(16_000, dtype=np.float32), "en", None),
    (np.zeros(48_000, dtype=np.float32), "de", "Phoenix"),
    (np.zeros(3 * 16_000 + 7, dtype=np.float32), "auto", None),
]


@pytest.mark.parametrize(("pcm", "language", "prompt"), FIXTURES)
async def test_provider_output_is_byte_identical_to_engine(
    pcm: np.ndarray, language: str, prompt: str | None
) -> None:
    engine = _FakeEngine()
    direct = await engine.transcribe(pcm, language=language, prompt=prompt)
    provider = InProcASRProvider(_FakeEngine())
    await provider.warm_up()
    via_seam = await provider.transcribe(pcm, language=language, prompt=prompt)
    assert via_seam.model_dump_json().encode() == direct.model_dump_json().encode()


async def test_warm_up_loads_and_properties_delegate() -> None:
    engine = _FakeEngine()
    provider = InProcASRProvider(engine, backend="inproc_cpu_asr")
    assert provider.is_loaded is False
    await provider.warm_up()
    assert (
        provider.is_loaded is True
        and provider.model_name == "tiny"
        and provider.warmup_seconds == 0.25
    )
    assert provider.backend == "inproc_cpu_asr"


async def test_cancel_propagates_and_usage_records_failure() -> None:
    records: list[UsageRecord] = []
    set_usage_sink(records.append)
    try:
        provider = InProcASRProvider(_FakeEngine())

        async def yes() -> bool:
            return True

        with pytest.raises(TranscriptionCancelledError):
            await provider.transcribe(
                np.zeros(16_000, dtype=np.float32), language="en", prompt=None, should_cancel=yes
            )
        await provider.transcribe(np.zeros(16_000, dtype=np.float32), language="en", prompt=None)
    finally:
        set_usage_sink(None)
    assert [r.ok for r in records] == [False, True]
    assert records[0].error_kind == "TranscriptionCancelledError"
    assert records[1].audio_seconds == 1.0 and records[1].operation == "asr.transcribe"
