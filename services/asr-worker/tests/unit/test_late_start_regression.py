"""The late-start fixture (``m12_en_late_start``): synthesised audio, real Silero,
scripted decoder; the processor's echo guard and coverage step are the real ones."""

from __future__ import annotations

import importlib.util
import time
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest

from asr_models import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker import processor
from asr_worker.audio_io import mixdown

_REPO = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "coverage_assert", _REPO / "scripts" / "eval" / "coverage_assert.py"
)
assert _spec and _spec.loader
coverage_assert = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coverage_assert)

SR = 16_000


def _db(x: np.ndarray, dbfs: float) -> np.ndarray:
    return (x * (10 ** (dbfs / 20) / np.sqrt(np.mean(x**2)))).astype(np.float32)


def _speech(n: int, clip: np.ndarray) -> np.ndarray:
    gap = np.zeros(int(0.4 * SR), dtype=np.float32)
    reps = n // (len(clip) + len(gap)) + 1
    return np.concatenate([np.concatenate([clip, gap])] * reps)[:n]


def synthesise(fixture: dict[str, Any]) -> np.ndarray:
    """(n, 2) int16: ch0 microphone, ch1 call audio."""
    with wave.open(str(_REPO / "libs/models/src/models/probe_clip.wav")) as w:
        clip = (
            np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        )
    n = fixture["duration_ms"] * SR // 1000
    rng = np.random.default_rng(12)
    mic = np.zeros(n, dtype=np.float32)
    call = np.zeros(n, dtype=np.float32)
    for part in fixture["audio"]["mic"]:
        a, b = part["start_ms"] * SR // 1000, part["end_ms"] * SR // 1000
        mic[a:b] = _db(rng.standard_normal(b - a).astype(np.float32), part["noise_dbfs"])
    for part in fixture["audio"]["system"]:
        a, b = part["start_ms"] * SR // 1000, part["end_ms"] * SR // 1000
        call[a:b] = _db(_speech(b - a, clip), part["speech_dbfs"])
    return (np.stack([mic, call], axis=1) * 32767).clip(-32768, 32767).astype(np.int16)


def _utterance(text: str, start_ms: int, end_ms: int) -> Segment:
    tokens = text.split()
    step = (end_ms - start_ms) / len(tokens)
    words = [
        WordTiming(
            text=t,
            start_ms=int(start_ms + k * step),
            end_ms=int(start_ms + (k + 0.8) * step),
            probability=0.9,
        )
        for k, t in enumerate(tokens)
    ]
    return Segment(text=text, start_ms=start_ms, end_ms=end_ms, words=words, avg_confidence=0.9)


def _output(segments: list[Segment]) -> TranscriptionOutput:
    return TranscriptionOutput(
        language="en",
        segments=segments,
        metadata=TranscriptionMetadata(
            model="scripted", vad_seconds_speech=0, infer_seconds=0, beam_size=5
        ),
    )


class _ScriptedDecoder:
    """Second decodes: the truth words inside the slice, slice-relative."""

    def __init__(self, truth: list[Segment]) -> None:
        self.truth = truth
        self.pcm_len = 0
        self.slices: list[int] = []

    def locate(self, full: np.ndarray, chunk: np.ndarray) -> int:
        # The processor slices the recording; find where this slice starts.
        for start in range(0, len(full) - len(chunk) + 1, SR // 1000):
            if np.array_equal(full[start : start + 64], chunk[:64]) and np.array_equal(
                full[start + len(chunk) - 64 : start + len(chunk)], chunk[-64:]
            ):
                return start * 1000 // SR
        raise AssertionError("slice not found in the recording")

    async def transcribe(self, pcm: np.ndarray, **kw: Any) -> TranscriptionOutput:
        assert kw["second_pass"] is True and kw["prompt"] is None
        start = self.locate(self.full, pcm)
        end = start + len(pcm) * 1000 // SR
        self.slices.append(start)
        segs: list[Segment] = []
        for seg in self.truth:
            words = [w for w in seg.words if start <= w.start_ms and w.end_ms <= end]
            if words:
                segs.append(
                    Segment(
                        text=" ".join(w.text for w in words),
                        start_ms=words[0].start_ms - start,
                        end_ms=words[-1].end_ms - start,
                        words=[
                            w.model_copy(
                                update={"start_ms": w.start_ms - start, "end_ms": w.end_ms - start}
                            )
                            for w in words
                        ],
                        avg_confidence=0.9,
                    )
                )
        return _output(segs)


async def test_the_late_start_twin_keeps_its_introduction() -> None:
    pytest.importorskip("silero_vad")
    from asr_worker import vad

    vad._model = None  # a real load, whatever an earlier test left
    fixture = coverage_assert.load("m12_en_late_start")
    stereo = synthesise(fixture)
    pcm = mixdown(stereo)
    truth = [_utterance(t["text"], t["start_ms"], t["end_ms"]) for t in fixture["truth"]]

    # The first decode: prompt words written over the quiet introduction,
    # the rest as said.
    echo_until = fixture["first_pass"]["echo_until_ms"]
    prompt = fixture["prompt"]
    echo_terms = [t.strip() for t in prompt.split(",")]
    first: list[Segment] = []
    for seg in truth:
        if seg.start_ms < echo_until:
            text = ", ".join(echo_terms + echo_terms[:3])
            first.append(_utterance(text, seg.start_ms, seg.end_ms))
        else:
            first.append(seg)

    decoder = _ScriptedDecoder(truth)
    decoder.full = pcm  # type: ignore[attr-defined]
    output = processor._guarded(_output(first), prompt, job_id=uuid4())
    before = coverage_assert.check(fixture["assertions"], output)
    output = await processor._covered(
        type("S", (), {"engine": decoder})(),
        output,
        pcm=pcm,
        stereo=stereo,
        prompt=prompt,
        first_frame_offset_ms=None,
        deadline=time.monotonic() + 300,
        should_cancel=None,
        job_id=uuid4(),
    )
    after = coverage_assert.check(fixture["assertions"], output)

    # Without the second pass the introduction is gone…
    assert not all(ok for _name, ok in before)
    # …with it, every check passes.
    assert all(ok for _name, ok in after), after
    assert decoder.slices, "the introduction was never decoded again"
    assert output.diagnostics.second_pass.by_cause.get("prompt_echo", 0) >= 1
