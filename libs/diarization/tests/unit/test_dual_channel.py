"""Channel analysis + dual-channel diarization (Sprint 31) on synthetic signals.

"Speech" is noise modulated at a syllable rate (so envelopes correlate the
way voices do); the segmenter is an energy VAD; the engine is a fake that
labels speech by a fixed timeline. No models, no audio files.
"""

from __future__ import annotations

import numpy as np
import pytest

from diarization import (
    UNKNOWN,
    DiarizationHints,
    OfflineDiarization,
    OfflineDiarizationConfig,
    SpeakerSegment,
    analyse_channels,
    diarize_dual,
    side_for_span,
)
from diarization.channels import BOTH, LOCAL, REMOTE

SR = 16_000


def _speech(seconds: float, *, level_db: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    syllables = 0.55 + 0.45 * np.sin(2 * np.pi * (3.0 + seed % 3) * t + seed)
    return (rng.normal(size=t.shape) * syllables * 10 ** (level_db / 20)).astype(np.float32)


def _place(total_s: float, *parts: tuple[float, np.ndarray]) -> np.ndarray:
    out = np.zeros(int(total_s * SR), dtype=np.float32)
    for start_s, signal in parts:
        lo = int(start_s * SR)
        out[lo : lo + len(signal)] += signal[: len(out) - lo]
    return out


def _delayed(signal: np.ndarray, ms: int, gain_db: float) -> np.ndarray:
    shift = ms * SR // 1000
    out = np.zeros_like(signal)
    out[shift:] = signal[:-shift] * 10 ** (gain_db / 20)
    return out


class EnergyVad:
    """Speech = 20 ms frames above −50 dBFS, merged into regions."""

    def speech_regions(self, pcm: np.ndarray) -> list[tuple[int, int]]:
        frame = SR // 50
        n = len(pcm) // frame
        rms = np.sqrt(np.mean(pcm[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
        active = 20 * np.log10(rms) > -50
        regions: list[tuple[int, int]] = []
        t = 0
        while t < n:
            if not active[t]:
                t += 1
                continue
            j = t
            while j < n and active[j]:
                j += 1
            regions.append((t * 20, j * 20))
            t = j
        return regions


class TimelineDiarizer:
    """Labels speech per call from a fixed timeline: calls come local first,
    then remote. Records the hints each pass was given."""

    engine = "fake"
    engine_version = "1"

    def __init__(self, *timelines: list[tuple[float, float, str]]) -> None:
        self._timelines = list(timelines)
        self.calls: list[DiarizationHints] = []

    @property
    def ready(self) -> bool:
        return True

    @property
    def last_error(self) -> str | None:
        return None

    async def ensure_loaded(self) -> None:
        return None

    def diarize(self, pcm: np.ndarray, rate: int, *, hints: DiarizationHints) -> OfflineDiarization:
        self.calls.append(hints)
        timeline = self._timelines.pop(0)
        segs = [
            SpeakerSegment(int(a * 1000), int(b * 1000), label, 1.0)
            for a, b, label in timeline
            if np.abs(pcm[int(a * SR) : int(b * SR)]).max(initial=0) > 1e-3
        ]
        names: dict[str, str] = {}
        for s in segs:
            names.setdefault(s.label, f"SPEAKER_{len(names) + 1}")
        return OfflineDiarization(
            segments=segs,
            display_names=names,
            duration_ms=len(pcm) * 1000 // SR,
            config=OfflineDiarizationConfig(),
            hints=hints,
        )


def _frames(activity, a: float, b: float) -> np.ndarray:  # noqa: ANN001
    return activity.side[int(a * 50) : int(b * 50)]


# ── analyse_channels ─────────────────────────────────────────────────


def test_headphones_no_leak_sides_follow_vad() -> None:
    mic = _place(20, (1, _speech(4, level_db=-20, seed=1)))
    system = _place(20, (8, _speech(5, level_db=-22, seed=2)))

    activity = analyse_channels(mic, system, segmenter=EnergyVad())

    assert activity.leak_gain_db is None
    assert (_frames(activity, 1.5, 4.5) == LOCAL).all()
    assert (_frames(activity, 8.5, 12.5) == REMOTE).all()
    assert activity.remote_speech_s == pytest.approx(5.1, abs=0.3)


def test_loudspeaker_leak_is_found_and_leaked_frames_are_remote() -> None:
    remote = _place(20, (2, _speech(12, level_db=-20, seed=3)))
    mic = _delayed(remote, 40, -18)  # the call, heard through the room

    activity = analyse_channels(mic, remote, segmenter=EnergyVad())

    assert activity.leak_delay_ms == pytest.approx(40, abs=20)
    assert activity.leak_gain_db == pytest.approx(-18, abs=3)
    inside = _frames(activity, 3, 13)
    assert (inside == REMOTE).all(), "the leak must not look like a local talker"


def test_a_local_talker_over_the_leak_is_heard() -> None:
    remote = _place(20, (2, _speech(12, level_db=-20, seed=4)))
    local = _place(20, (6, _speech(3, level_db=-28, seed=5)))  # ≈ +10 dB over the leak
    mic = _delayed(remote, 40, -18) + local

    activity = analyse_channels(mic, remote, segmenter=EnergyVad())

    talk = _frames(activity, 6.3, 8.7)
    assert np.isin(talk, (LOCAL, BOTH)).mean() > 0.8
    assert side_for_span(activity, 6500, 8500) in ("both", "local")
    assert side_for_span(activity, 3000, 5000) == "remote"


# ── diarize_dual ─────────────────────────────────────────────────────


def _call() -> tuple[np.ndarray, np.ndarray]:
    """One local person (1–4 s), two remote people (6–9 s, 11–14 s)."""
    mic = _place(20, (1, _speech(3, level_db=-20, seed=6)))
    system = _place(
        20, (6, _speech(3, level_db=-22, seed=7)), (11, _speech(3, level_db=-22, seed=8))
    )
    return mic, system


def test_dual_labels_both_sides_and_never_crosses_them() -> None:
    mic, system = _call()
    engine = TimelineDiarizer([(1, 4, "A")], [(6, 9, "X"), (11, 14, "Y")])

    diar = diarize_dual(
        mic, system, diarizer=engine, hints=DiarizationHints(), segmenter=EnergyVad()
    )

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"]
    assert diar.sides == {"SPEAKER_1": "local", "SPEAKER_2": "remote", "SPEAKER_3": "remote"}
    assert diar.attribute(2000, 2500) == "SPEAKER_1"
    assert diar.attribute(7000, 7500) == "SPEAKER_2"
    assert diar.attribute(12000, 12500) == "SPEAKER_3"
    assert (diar.channel.local_speakers, diar.channel.remote_speakers) == (1, 2)


def test_a_silent_call_channel_is_the_mono_answer_on_the_mic() -> None:
    mic = _place(20, (1, _speech(3, level_db=-20, seed=6)), (6, _speech(3, level_db=-20, seed=9)))
    system = np.zeros_like(mic)
    engine = TimelineDiarizer([(1, 4, "A"), (6, 9, "B")])

    diar = diarize_dual(
        mic, system, diarizer=engine, hints=DiarizationHints(), segmenter=EnergyVad()
    )

    assert len(engine.calls) == 1, "no remote pass on a silent call channel"
    assert diar.sides == {"SPEAKER_1": "local", "SPEAKER_2": "local"}


def test_a_stated_count_splits_one_local_and_the_rest_remote_with_headphones() -> None:
    mic, system = _call()
    engine = TimelineDiarizer([(1, 4, "A")], [(6, 9, "X"), (11, 14, "Y")])

    diarize_dual(
        mic, system, diarizer=engine, hints=DiarizationHints(num_speakers=3), segmenter=EnergyVad()
    )

    assert engine.calls == [DiarizationHints(max_speakers=3), DiarizationHints(num_speakers=2)]


def test_a_stated_count_trims_the_merged_roster_by_speech_time() -> None:
    mic, system = _call()
    engine = TimelineDiarizer([(1, 4, "A")], [(6, 9, "X"), (11, 12, "Y")])

    diar = diarize_dual(
        mic, system, diarizer=engine, hints=DiarizationHints(num_speakers=2), segmenter=EnergyVad()
    )

    assert len(diar.speakers) == 2
    assert all(s.label != "R:Y" for s in diar.segments)
    assert any(s.label == UNKNOWN for s in diar.segments) or len(diar.speakers) == 2


def test_an_analysis_failure_propagates_for_the_worker_to_fall_back() -> None:
    mic, system = _call()

    def broken(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("channel analysis bug")

    with pytest.raises(RuntimeError):
        diarize_dual(
            mic,
            system,
            diarizer=TimelineDiarizer(),
            hints=DiarizationHints(),
            segmenter=EnergyVad(),
            analyse=broken,
        )
