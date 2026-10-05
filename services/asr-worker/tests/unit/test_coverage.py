"""Coverage diagnostics, gap causes, the second pass, the VAD pad and the floor pass.
Scripted engine, no Whisper."""

from __future__ import annotations

import time
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest

from asr_models import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker import coverage as cov
from asr_worker import processor, vad
from asr_worker.audio_io import mixdown
from asr_worker.vad import SpeechRuns, SpeechSegment

PROMPT = "Gysi, Moderator, Narrator"
_CLIP = Path(__file__).resolve().parents[4] / "libs/models/src/models/probe_clip.wav"


def _words(text: str, start_ms: int, step_ms: int = 400) -> list[WordTiming]:
    return [
        WordTiming(
            text=t,
            start_ms=start_ms + k * step_ms,
            end_ms=start_ms + k * step_ms + 300,
            probability=0.9,
        )
        for k, t in enumerate(text.split())
    ]


def _seg(text: str, start_ms: int, step_ms: int = 400) -> Segment:
    words = _words(text, start_ms, step_ms)
    return Segment(
        text=text,
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        words=words,
        avg_confidence=0.9,
    )


def _output(segments: list[Segment], language: str = "en") -> TranscriptionOutput:
    return TranscriptionOutput(
        language=language,
        segments=segments,
        metadata=TranscriptionMetadata(
            model="scripted", vad_seconds_speech=0, infer_seconds=0, beam_size=5
        ),
    )


class _ScriptedEngine:
    """Answers each second-pass call with the next scripted output
    (slice-relative timestamps, as a real backend would)."""

    def __init__(self, *answers: list[Segment]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    async def transcribe(self, pcm: np.ndarray, **kw: Any) -> TranscriptionOutput:
        self.calls.append({"samples": len(pcm), **kw})
        return _output(self.answers.pop(0) if self.answers else [])


def _state(engine: Any) -> Any:
    return type("S", (), {"engine": engine})()


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    output: TranscriptionOutput,
    runs: list[SpeechSegment],
    engine: Any,
    *,
    offset: int | None = None,
    deadline: float | None = None,
) -> TranscriptionOutput:
    monkeypatch.setattr(vad, "speech_runs", lambda *a, **k: SpeechRuns(runs=runs))
    output = processor._guarded(output, PROMPT, job_id=uuid4())
    return await processor._covered(
        _state(engine),
        output,
        pcm=np.zeros(16_000 * 120, dtype=np.float32),
        stereo=None,
        prompt=PROMPT,
        first_frame_offset_ms=offset,
        deadline=deadline if deadline is not None else time.monotonic() + 600,
        should_cancel=None,
        job_id=uuid4(),
    )


# ── the second pass ─────────────────────────────────────────────────────


async def test_a_prompt_only_first_decode_is_replaced_by_the_second_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 11–41 s: the first decode wrote the prompt back.
    first = [
        _seg("Gysi, Moderator, Narrator, Gysi, Moderator", 11_000),
        _seg("If you have any questions", 42_000),
    ]
    runs = [SpeechSegment(11_000, 41_000), SpeechSegment(41_000, 46_000)]
    opening = (
        "Thank you for watching this highly anticipated world debut of the Pardo 65 GT here "
        "at the Cannes Yachting Festival my name is Mitchell I am a broker with Springbrook Marine"
    )
    rescued = [_seg(opening, 300, step_ms=900)]
    engine = _ScriptedEngine(rescued)
    # The pad is off by default; set, it moves the slice start.
    monkeypatch.setattr(processor.settings, "asr_vad_pad_ms", 300)

    out = await _run(monkeypatch, _output(first), runs, engine)

    assert engine.calls[0]["prompt"] is None and engine.calls[0]["second_pass"] is True
    # The slice starts 300 ms early (the pad) and timestamps come back in
    # recording time.
    assert out.segments[0].start_ms == 11_000 - 300 + 300
    assert "Mitchell" in out.segments[0].text
    c = out.diagnostics.coverage
    assert c is not None and c.gaps == [] and c.transcribed_ms == c.speech_ms
    assert out.diagnostics.second_pass.chunks == 1
    assert out.diagnostics.second_pass.by_cause == {"prompt_echo": 1}
    assert out.diagnostics.second_pass.recovered_words == len(opening.split())
    assert out.metadata.coverage_share == 1.0


async def test_both_decodes_empty_is_a_decoder_empty_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    first = [_seg("and then the next thing", 20_000)]
    runs = [SpeechSegment(0, 8_000), SpeechSegment(20_000, 22_000)]
    engine = _ScriptedEngine([])

    out = await _run(monkeypatch, _output(first), runs, engine)

    c = out.diagnostics.coverage
    assert c is not None
    assert [(g.start_ms, g.end_ms, g.cause) for g in c.gaps] == [(0, 8_000, "decoder_empty")]
    assert c.speech_ms == 10_000 and c.transcribed_ms == 2_000
    assert out.diagnostics.second_pass.by_cause == {"decoder_empty": 1}


async def test_echo_the_second_pass_cannot_recover_is_a_prompt_echo_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = [_seg("Gysi, Moderator, Narrator, Gysi", 1_000)]
    out = await _run(
        monkeypatch, _output(first), [SpeechSegment(1_000, 6_000)], _ScriptedEngine([])
    )
    c = out.diagnostics.coverage
    assert c is not None and [g.cause for g in c.gaps] == ["prompt_echo"]


async def test_a_worse_second_attempt_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    # 5 of 10 s covered by words (low coverage) — the second attempt finds less.
    first = [_seg("one two three four five six seven eight", 0, step_ms=500)]
    out = await _run(
        monkeypatch,
        _output(first),
        [SpeechSegment(0, 12_000)],
        _ScriptedEngine([_seg("one two", 0)]),
    )
    assert out.segments[0].text == "one two three four five six seven eight"
    assert out.diagnostics.second_pass.recovered_words == 0


async def test_a_low_confidence_second_attempt_is_not_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    guess = [
        Segment(
            text="Thank you for watching",
            start_ms=0,
            end_ms=2_000,
            words=[
                WordTiming(text=w, start_ms=k * 500, end_ms=k * 500 + 400, probability=0.1)
                for k, w in enumerate(["Thank", "you", "for", "watching"])
            ],
            avg_confidence=0.1,
        )
    ]
    out = await _run(monkeypatch, _output([]), [SpeechSegment(0, 5_000)], _ScriptedEngine(guess))
    assert out.segments == []
    c = out.diagnostics.coverage
    assert c is not None and [g.cause for g in c.gaps] == ["unknown"]


async def test_short_runs_are_never_second_passed_or_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _ScriptedEngine()
    out = await _run(
        monkeypatch,
        _output([_seg("hello there", 5_000)]),
        [SpeechSegment(0, 2_500), SpeechSegment(5_000, 6_000)],
        engine,
    )
    assert engine.calls == []
    c = out.diagnostics.coverage
    assert c is not None and c.gaps == []


async def test_an_exhausted_budget_keeps_the_first_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _ScriptedEngine([_seg("words", 0)])
    out = await _run(
        monkeypatch, _output([]), [SpeechSegment(0, 5_000)], engine, deadline=time.monotonic()
    )
    assert engine.calls == []
    assert out.diagnostics.second_pass.by_cause == {"timeout": 1}


async def test_the_splice_keeps_words_outside_the_rescued_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An HTTP backend's one segment spans a good run (0–4 s) and a lost one
    # whose words were echo (6–12 s).
    words = _words("we start here fine", 0, step_ms=1_000) + _words(
        "Gysi, Moderator, Narrator, Gysi", 6_000, step_ms=1_500
    )
    first = [
        Segment(
            text=" ".join(w.text for w in words),
            start_ms=0,
            end_ms=words[-1].end_ms,
            words=words,
            avg_confidence=0.9,
        )
    ]
    rescued = [_seg("the real opening words were said here", 300)]
    out = await _run(
        monkeypatch,
        _output(first),
        [SpeechSegment(0, 4_000), SpeechSegment(6_000, 12_000)],
        _ScriptedEngine(rescued),
    )
    texts = [s.text for s in out.segments]
    assert texts[0] == "we start here fine"
    assert "real opening words" in texts[1]


async def test_a_late_first_frame_is_a_no_audio_gap_before_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = await _run(
        monkeypatch,
        _output([_seg("hello everyone", 0)]),
        [SpeechSegment(0, 1_000)],
        _ScriptedEngine(),
        offset=4_200,
    )
    c = out.diagnostics.coverage
    assert c is not None
    assert [(g.start_ms, g.end_ms, g.cause) for g in c.gaps] == [(0, 4_200, "no_audio")]
    # Outside the file: not part of the totals.
    assert c.transcribed_ms == c.speech_ms == 1_000


async def test_a_vad_failure_leaves_the_transcript_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> SpeechRuns:
        raise RuntimeError("vad died")

    monkeypatch.setattr(vad, "speech_runs", boom)
    output = _output([_seg("hello", 0)])
    out = await processor._covered(
        _state(_ScriptedEngine()),
        output,
        pcm=np.zeros(16_000, dtype=np.float32),
        stereo=None,
        prompt=None,
        first_frame_offset_ms=None,
        deadline=time.monotonic() + 60,
        should_cancel=None,
        job_id=uuid4(),
    )
    assert out is output and out.diagnostics.coverage is None


# ── gap causes and arithmetic ───────────────────────────────────────────


def test_gap_causes() -> None:
    run = SpeechSegment(0, 5_000)
    assert cov.gap_cause(cov.RunOutcome(run=run), first_frame_offset_ms=4_000) == "no_audio"
    assert (
        cov.gap_cause(
            cov.RunOutcome(run=SpeechSegment(10_000, 15_000, floor_only=True)),
            first_frame_offset_ms=None,
        )
        == "no_speech_detected"
    )
    assert (
        cov.gap_cause(cov.RunOutcome(run=run, echo_removed=True), first_frame_offset_ms=None)
        == "prompt_echo"
    )
    assert (
        cov.gap_cause(cov.RunOutcome(run=run, other_language=True), first_frame_offset_ms=None)
        == "other_language"
    )
    assert (
        cov.gap_cause(cov.RunOutcome(run=run, second_pass_words=0), first_frame_offset_ms=None)
        == "decoder_empty"
    )
    assert cov.gap_cause(cov.RunOutcome(run=run), first_frame_offset_ms=None) == "unknown"


def test_coverage_arithmetic_on_hand_built_runs() -> None:
    runs = [
        SpeechSegment(0, 10_000),
        SpeechSegment(10_000, 20_000),
        SpeechSegment(30_000, 34_000),
        SpeechSegment(40_000, 41_000),
    ]
    # Only the 30–34 s run carries words; 0–20 s is one lost passage in two
    # 10 s pieces; 40–41 s is too short to be a gap.
    segments = [_seg("a b c d e f g h i j", 30_000)]
    c = cov.measure(runs, segments, {}, first_frame_offset_ms=None)
    assert c.speech_ms == 25_000
    assert [(g.start_ms, g.end_ms, g.cause) for g in c.gaps] == [(0, 20_000, "unknown")]
    assert c.transcribed_ms == 5_000
    assert c.first_speech_ms == 0 and c.first_segment_ms == 30_000
    assert c.share == pytest.approx(0.2)


def test_covered_ms_bridges_pauses_between_words() -> None:
    run = SpeechSegment(0, 10_000)
    seg = _seg("one two three four five six seven eight nine ten", 200, step_ms=1_000)
    assert cov.covered_ms(run, [seg]) == 10_000
    assert not cov.is_gap(run, [seg])


def test_the_stub_vad_is_complete_by_construction() -> None:
    c = cov.measure([SpeechSegment(0, 60_000)], [], {}, first_frame_offset_ms=None, stub=True)
    assert c.vad == "stub" and c.gaps == [] and c.share == 1.0


# ── VAD: pad and floor ──────────────────────────────────────────────────


def test_the_pad_starts_runs_300_ms_earlier_and_never_overlaps() -> None:
    runs = [SpeechSegment(100, 2_000), SpeechSegment(2_100, 5_000), SpeechSegment(9_000, 10_000)]
    padded = vad.pad_runs(runs, 300)
    assert padded == [
        SpeechSegment(0, 2_000),
        SpeechSegment(2_000, 5_000),
        SpeechSegment(8_700, 10_000),
    ]
    assert vad.pad_runs(runs, 0) == runs


def test_the_union_marks_runs_only_the_floor_heard() -> None:
    merged = vad.union_runs(
        [SpeechSegment(0, 1_000)], [SpeechSegment(800, 2_000), SpeechSegment(5_000, 6_000)]
    )
    assert merged == [SpeechSegment(0, 2_000, False), SpeechSegment(5_000, 6_000, True)]


def _db(x: np.ndarray, dbfs: float) -> np.ndarray:
    return x * (10 ** (dbfs / 20) / np.sqrt(np.mean(x**2)))


def test_quiet_call_audio_under_a_loud_microphone_is_found_by_the_floor_pass() -> None:
    """Speech at −30 dBFS on the call channel under −20 dBFS microphone noise: ordinary
    VAD hears nothing on the mixdown; the per-channel floor pass finds it."""
    vad._ensure_loaded()
    if vad.is_stub():
        pytest.skip("silero-vad not installed")
    with wave.open(str(_CLIP)) as w:
        clip = (
            np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        )
    n = 16_000 * 40
    mic = _db(np.random.default_rng(7).standard_normal(n).astype(np.float32), -20)
    call = np.zeros(n, dtype=np.float32)
    speech = _db(np.concatenate([clip, clip]), -30)
    call[16_000 * 10 : 16_000 * 10 + len(speech)] = speech
    stereo = (np.stack([mic, call], axis=1) * 32767).clip(-32768, 32767).astype(np.int16)
    mono = mixdown(stereo)

    assert vad.speech_runs(mono, stereo=stereo, floor=False).runs == []
    found = vad.speech_runs(mono, stereo=stereo, floor=True)
    assert found.floor_used
    assert len(found.runs) == 1 and found.runs[0].floor_only
    assert 9_500 <= found.runs[0].start_ms <= 10_500
    assert found.runs[0].end_ms >= 15_000


def test_the_floor_leaves_an_ordinary_meeting_alone() -> None:
    vad._ensure_loaded()
    if vad.is_stub():
        pytest.skip("silero-vad not installed")
    silence = np.zeros(16_000 * 10, dtype=np.float32)
    runs = [SpeechSegment(0, 5_000)]
    # Half the file is speech: the share condition fails.
    assert not vad.floor_applies(silence, runs, 16_000, max_speech_share=0.2)
    # Little speech, but the rest is silence (below −45 dBFS).
    assert not vad.floor_applies(silence, [SpeechSegment(0, 500)], 16_000, max_speech_share=0.2)
