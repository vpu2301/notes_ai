"""Sprint TQ2 T2/T3 — the segment gates, rule by rule, on synthetic
segments; the rollback switch; and the no-content rule for diagnostics."""

from __future__ import annotations

import json
from typing import Any

import pytest

from asr_models import (
    Diagnostics,
    Segment,
    SegmentDiagnostics,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from asr_worker import guards
from asr_worker.config import settings
from asr_worker.vad import SpeechSegment


def _seg(start: int, text: str, *, ms_per_word: int = 300, prob: float = 0.9) -> Segment:
    words = []
    t = start
    for w in text.split():
        words.append(WordTiming(text=w, start_ms=t, end_ms=t + ms_per_word - 20, probability=prob))
        t += ms_per_word
    return Segment(
        text=text, start_ms=start, end_ms=max(t, start + 1), words=words, avg_confidence=prob
    )


def _out(
    segments: list[Segment], diags: list[SegmentDiagnostics] | None = None
) -> TranscriptionOutput:
    return TranscriptionOutput(
        language="de",
        segments=segments,
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
        diagnostics=Diagnostics(segments=diags or []),
    )


def _d(seg: Segment, **numbers: float) -> SegmentDiagnostics:
    return SegmentDiagnostics(start_ms=seg.start_ms, end_ms=seg.end_ms, **numbers)


SILENCE: list[SpeechSegment] = []


def _speech_over(seg: Segment) -> list[SpeechSegment]:
    return [SpeechSegment(seg.start_ms, seg.end_ms)]


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_gates_enabled", True)


# ── G1 ───────────────────────────────────────────────────────────────


def test_g1_drops_text_over_silence_the_decoder_calls_no_speech() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.9, avg_logprob=-1.4)]), SILENCE).output
    assert out.segments == []
    (drop,) = out.diagnostics.dropped_segments
    assert (drop.reason, drop.no_speech_prob, drop.speech_share, drop.dry_run) == (
        "no_speech",
        0.9,
        0.0,
        False,
    )


def test_g1_keeps_the_same_segment_where_vad_heard_speech() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    speech = [SpeechSegment(seg.start_ms, seg.start_ms + int(0.8 * (seg.end_ms - seg.start_ms)))]
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.9, avg_logprob=-1.4)]), speech).output
    assert out.segments == [seg] and out.diagnostics.dropped_segments == []


def test_g1_keeps_a_confident_segment() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.9, avg_logprob=-0.2)]), SILENCE).output
    assert out.segments == [seg]


def test_g1_without_the_decoders_figure_rests_on_vad_alone() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    out = guards.apply(_out([seg]), SILENCE).output
    assert out.segments == []
    assert out.diagnostics.gate_unavailable["no_speech_prob"] == 1


# ── G2 ───────────────────────────────────────────────────────────────


def test_g2_a_two_gram_repeated_six_times_is_cut_after_two() -> None:
    seg = _seg(0, "vielen dank " * 6)
    result = guards.apply(_out([seg]), _speech_over(seg))
    (kept,) = result.output.segments
    assert kept.text == "vielen dank vielen dank"
    assert result.loop_ranges == [(seg.start_ms, seg.end_ms)], "the range goes to the second pass"
    (drop,) = result.output.diagnostics.dropped_segments
    assert drop.reason == "loop" and drop.start_ms == seg.words[4].start_ms


def test_g2_identical_segments_in_a_row_keep_two() -> None:
    segs = [_seg(k * 2000, "Vielen Dank.") for k in range(5)]
    result = guards.apply(_out(segs), [SpeechSegment(0, 10_000)])
    assert [s.start_ms for s in result.output.segments] == [0, 2000]
    assert [d.reason for d in result.output.diagnostics.dropped_segments] == ["loop"] * 3


def test_g2_a_high_compression_ratio_alone_asks_for_a_second_pass_without_cutting() -> None:
    seg = _seg(0, "das ist ein ganz normaler satz")
    result = guards.apply(_out([seg], [_d(seg, compression_ratio=2.9)]), _speech_over(seg))
    assert result.output.segments == [seg]
    assert result.loop_ranges == [(seg.start_ms, seg.end_ms)]


def test_g2_leaves_ordinary_repetition_alone() -> None:
    seg = _seg(0, "ja ja genau das das ist es")
    result = guards.apply(_out([seg]), _speech_over(seg))
    assert result.output.segments == [seg] and result.loop_ranges == []


# ── G3 ───────────────────────────────────────────────────────────────


def test_g3_drops_a_short_unsure_segment_where_vad_heard_nothing() -> None:
    seg = _seg(5000, "hm ja", prob=0.1)
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.1, avg_logprob=-0.5)]), SILENCE).output
    assert out.segments == []
    assert out.diagnostics.dropped_segments[0].reason == "low_confidence_nonspeech"


def test_g3_keeps_a_short_unsure_segment_over_speech() -> None:
    seg = _seg(5000, "hm ja", prob=0.1)
    out = guards.apply(
        _out([seg], [_d(seg, no_speech_prob=0.1, avg_logprob=-0.5)]), _speech_over(seg)
    ).output
    assert out.segments == [seg]


# ── T3 artefacts ─────────────────────────────────────────────────────


def test_an_artefact_in_silence_is_dropped() -> None:
    seg = _seg(30_000, "Vielen Dank.")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.0, avg_logprob=-0.2)]), SILENCE).output
    assert out.segments == []
    (drop,) = out.diagnostics.dropped_segments
    assert drop.reason == "artefact" and drop.artefact and drop.artefact.startswith("de:")


def test_an_artefact_over_speech_is_kept_and_flagged() -> None:
    seg = _seg(30_000, "Vielen Dank.")
    out = guards.apply(
        _out([seg], [_d(seg, no_speech_prob=0.0, avg_logprob=-0.2)]), _speech_over(seg)
    ).output
    assert out.segments == [seg]
    assert len(out.diagnostics.artefact_kept) == 1 and out.diagnostics.dropped_segments == []


def test_an_artefact_the_decoder_calls_no_speech_is_dropped_even_over_vad_speech() -> None:
    seg = _seg(0, "Untertitelung des ZDF, 2020")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.7)]), _speech_over(seg)).output
    assert out.segments == []


# ── Rollback switch ──────────────────────────────────────────────────


def test_gates_off_drop_nothing_and_record_a_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_gates_enabled", False)
    silent = _seg(30_000, "Vielen Dank.")
    loop = _seg(0, "vielen dank " * 6)
    result = guards.apply(
        _out([loop, silent], [_d(silent, no_speech_prob=0.9, avg_logprob=-1.5)]), _speech_over(loop)
    )
    assert result.output.segments == [loop, silent]
    assert result.loop_ranges == []
    reasons = sorted(d.reason for d in result.output.diagnostics.dropped_segments)
    assert reasons == ["artefact", "loop"]
    assert all(d.dry_run for d in result.output.diagnostics.dropped_segments)


# ── No content in diagnostics ────────────────────────────────────────


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (_strings(k) + _strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_diagnostics_carry_no_text() -> None:
    segs = [
        _seg(0, "vielen dank " * 6),
        _seg(10_000, "Untertitelung des ZDF, 2020"),
        _seg(20_000, "Ein ganz gewöhnlicher Satz über Handala"),
        _seg(40_000, "Vielen Dank."),
    ]
    out = guards.apply(
        _out(segs, [_d(s, no_speech_prob=0.1, avg_logprob=-0.3) for s in segs]),
        [SpeechSegment(0, 25_000)],
    ).output
    dumped = json.loads(out.diagnostics.model_dump_json())
    for s in _strings(dumped):
        assert len(s) <= 32, s
    blob = json.dumps(dumped).casefold()
    for word in ("vielen", "dank", "untertitelung", "zdf", "handala", "satz"):
        assert word not in blob


def test_g3_is_skipped_when_the_backend_gave_no_word_probabilities() -> None:
    seg = _seg(5000, "hm ja", prob=1.0)  # read as 1.0 because none were sent
    out = _out([seg]).model_copy(
        update={"diagnostics": Diagnostics(gate_unavailable={"word_probability": 2})}
    )
    result = guards.apply(out, [SpeechSegment(0, 4000)]).output
    # No no_speech_prob either: G1 rests on VAD alone and drops it, G3 did not run.
    assert [d.reason for d in result.diagnostics.dropped_segments] == ["no_speech"]
