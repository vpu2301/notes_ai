"""Sprint 31: dual-channel captures in the worker.

The channel path is exercised through `_diarize_capture` with a fake
engine; the failure isolation (any channel-path exception → mono on the
mixdown, `mono_fallback`) and the naming rule are held here. The channel
analysis itself is tested in libs/diarization.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import numpy as np
import pytest

from asr_models.output import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker import processor
from asr_worker.processor import _channel_name, _diarization_stats, _diarize_capture
from diarization import (
    DiarizationHints,
    OfflineDiarization,
    OfflineDiarizationConfig,
    SpeakerSegment,
)

from .test_rediarize import _THREE, _World


class _Engine:
    engine = "fake"
    engine_version = "1"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def diarize(self, pcm: np.ndarray, rate: int, *, hints: DiarizationHints) -> OfflineDiarization:
        self.calls.append(len(pcm))
        segs = [SpeakerSegment(0, 1000, "A", 1.0)]
        return OfflineDiarization(
            segments=segs,
            display_names={"A": "SPEAKER_1"},
            duration_ms=1000,
            config=OfflineDiarizationConfig(),
            hints=hints,
        )


def _state(engine: _Engine) -> Any:
    return type("S", (), {"diarizer": engine, "channel_segmenter": object()})()


async def test_a_mono_capture_takes_the_mono_path() -> None:
    engine = _Engine()
    pcm = np.zeros(16_000, dtype=np.float32)

    diar, layout = await _diarize_capture(
        _state(engine), pcm, None, DiarizationHints(), job_id=uuid4()
    )

    assert layout == "mono"
    assert engine.calls == [16_000]


async def test_a_dual_capture_is_diarized_per_side(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_dual(mic: np.ndarray, system: np.ndarray, **kw: Any) -> OfflineDiarization:
        seen["mic"], seen["system"] = mic, system
        diar = _Engine().diarize(mic, 16_000, hints=kw["hints"])
        diar.sides = {"SPEAKER_1": "local"}
        return diar

    monkeypatch.setattr(processor, "diarize_dual", fake_dual)
    stereo = np.stack([np.full(16_000, 100, np.int16), np.full(16_000, -7, np.int16)], axis=1)

    diar, layout = await _diarize_capture(
        _state(_Engine()), np.zeros(16_000, np.float32), stereo, DiarizationHints(), job_id=uuid4()
    )

    assert layout == "mic_system"
    assert (seen["mic"] == 100).all() and (seen["system"] == -7).all(), "ch0 = mic, ch1 = call"
    assert diar.sides == {"SPEAKER_1": "local"}


async def test_any_channel_path_failure_falls_back_to_mono(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance 8: a bug in the channel analysis must not cost the speakers."""

    def broken(*_a: Any, **_kw: Any) -> OfflineDiarization:
        raise RuntimeError("analyse_channels exploded")

    monkeypatch.setattr(processor, "diarize_dual", broken)
    engine = _Engine()
    mixdown = np.zeros(32_000, np.float32)

    diar, layout = await _diarize_capture(
        _state(engine), mixdown, np.zeros((32_000, 2), np.int16), DiarizationHints(), job_id=uuid4()
    )

    assert layout == "mono_fallback"
    assert engine.calls == [32_000], "the mono path ran on the mixdown"
    assert diar.speakers == ["SPEAKER_1"]


def _output(sides: dict[str, str], speech_s: dict[str, int]) -> TranscriptionOutput:
    segments = []
    t = 0
    for label, seconds in speech_s.items():
        words = [
            WordTiming(
                text="w", start_ms=(t + i) * 1000, end_ms=(t + i + 1) * 1000, probability=0.9
            )
            for i in range(seconds)
        ]
        segments.append(
            Segment(
                text="w",
                start_ms=t * 1000,
                end_ms=(t + seconds) * 1000,
                words=words,
                avg_confidence=0.9,
                speaker=label,
            )
        )
        t += seconds
    return TranscriptionOutput(
        language="en",
        segments=segments,
        metadata=TranscriptionMetadata(
            model="m", vad_seconds_speech=1, infer_seconds=1, beam_size=5
        ),
        speakers=list(speech_s),
        speaker_sides=sides,  # type: ignore[arg-type]
    )


def test_the_only_local_speaker_is_named_after_the_account_owner() -> None:
    out = _output({"SPEAKER_1": "local", "SPEAKER_2": "remote"}, {"SPEAKER_1": 12, "SPEAKER_2": 30})

    assert _channel_name(out, "  Volodymyr   P. ") == ("SPEAKER_1", "Volodymyr P.")


@pytest.mark.parametrize(
    ("sides", "speech", "name"),
    [
        ({"SPEAKER_1": "local", "SPEAKER_2": "local"}, {"SPEAKER_1": 20, "SPEAKER_2": 20}, "V"),
        ({"SPEAKER_1": "local"}, {"SPEAKER_1": 9}, "V"),  # under 10 s of speech
        ({"SPEAKER_1": "local"}, {"SPEAKER_1": 20}, None),
        ({"SPEAKER_1": "local"}, {"SPEAKER_1": 20}, "   "),
        ({}, {"SPEAKER_1": 20}, "V"),  # a mono job
    ],
)
def test_no_automatic_name_otherwise(
    sides: dict[str, str], speech: dict[str, int], name: str | None
) -> None:
    assert _channel_name(_output(sides, speech), name) is None


def test_channel_stats_are_numbers_only() -> None:
    out = _output({"SPEAKER_1": "local"}, {"SPEAKER_1": 12})
    diar = _Engine().diarize(np.zeros(1), 16_000, hints=DiarizationHints())
    diar.channel = type(
        "C",
        (),
        {"leak_gain_db": -17.94, "local_speakers": 1, "remote_speakers": 2, "both_share": 0.03},
    )()

    stats = _diarization_stats(out, diar, 1.0, channel_layout="mic_system")

    assert (
        stats.channel_layout,
        stats.leak_gain_db,
        stats.local_speakers,
        stats.remote_speakers,
    ) == (
        "mic_system",
        -17.9,
        1,
        2,
    )


async def test_a_cleared_channel_name_stays_cleared_after_a_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 6: the person removed the channel name; a re-run must
    not put it back — "cleared" follows the speaker."""
    world = _World(_THREE, monkeypatch)
    world.row["speaker_names"] = json.dumps({})
    world.row["speaker_name_sources"] = json.dumps({"SPEAKER_1": "cleared"})

    await processor._rediarize_one(world.state, world.payload())

    assert world.row["speaker_name_sources"] == {"SPEAKER_1": "cleared"}
    assert world.row["speaker_names"] == {}
