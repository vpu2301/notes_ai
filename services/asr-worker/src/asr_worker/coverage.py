"""Coverage of speech by the transcript: pure functions over VAD runs and segments.

A run is covered where a surviving word (widened by ``WORD_REACH_MS``) lies in it;
a gap is a run of at least ``MIN_GAP_MS`` covered for less than half (shorter runs are
never second-passed: that is where Whisper invents "Thank you."). ``no_audio`` is the
client's Record-to-first-frame latency, outside both totals. Backend-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from asr_models.output import Coverage, CoverageGap, EchoSpan, GapCause, Segment, WordTiming

from .vad import SpeechSegment

MIN_GAP_MS: Final = 3_000
LOW_COVERAGE: Final = 0.5
ECHO_SHARE: Final = 0.3
WORD_REACH_MS: Final = 500
NO_AUDIO_TOLERANCE_MS: Final = 2_000
# A second attempt is kept only when it is not itself a guess (stock phrases at low prob).
MIN_SECOND_PASS_CONFIDENCE: Final = 0.4

# Why a run is decoded again (``SecondPass.by_cause`` keys, metric label).
LOW_COVERAGE_CAUSE: Final = "low_coverage"
PROMPT_ECHO_CAUSE: Final = "prompt_echo"
DECODER_EMPTY_CAUSE: Final = "decoder_empty"
TIMEOUT_CAUSE: Final = "timeout"
# A repetition loop the gate truncated.
LOOP_CAUSE: Final = "loop"


def _mid(start_ms: int, end_ms: int) -> float:
    return (start_ms + end_ms) / 2


def _inside(run: SpeechSegment, start_ms: int, end_ms: int) -> bool:
    return run.start_ms <= _mid(start_ms, end_ms) < run.end_ms


def _words(segment: Segment) -> list[WordTiming]:
    """A segment's words; without word timings, one pseudo-word per token at the segment span."""
    if segment.words:
        return segment.words
    return [
        WordTiming(text=t, start_ms=segment.start_ms, end_ms=segment.end_ms, probability=1.0)
        for t in segment.text.split()
    ]


def words_in(run: SpeechSegment, segments: list[Segment]) -> int:
    """Surviving words whose middle lies in ``run``."""
    return sum(1 for seg in segments for w in _words(seg) if _inside(run, w.start_ms, w.end_ms))


def echo_words_in(run: SpeechSegment, spans: list[EchoSpan]) -> int:
    """Words the echo guard removed from ``run``."""
    return sum(s.words for s in spans if _inside(run, s.start_ms, s.end_ms))


def covered_ms(run: SpeechSegment, segments: list[Segment]) -> int:
    """How much of ``run`` lies within reach of a surviving word."""
    spans: list[tuple[int, int]] = []
    for seg in segments:
        for w in _words(seg):
            start = max(run.start_ms, w.start_ms - WORD_REACH_MS)
            end = min(run.end_ms, w.end_ms + WORD_REACH_MS)
            if end > start:
                spans.append((start, end))
    spans.sort()
    total = 0
    cursor = run.start_ms
    for start, end in spans:
        start = max(start, cursor)
        if end > start:
            total += end - start
            cursor = end
    return total


def _length(run: SpeechSegment) -> int:
    return run.end_ms - run.start_ms


def is_gap(run: SpeechSegment, segments: list[Segment]) -> bool:
    length = _length(run)
    return length >= MIN_GAP_MS and covered_ms(run, segments) < LOW_COVERAGE * length


def second_pass_cause(
    run: SpeechSegment, segments: list[Segment], spans: list[EchoSpan]
) -> str | None:
    """Why ``run`` should be decoded again (decision 3), or None."""
    if _length(run) < MIN_GAP_MS:
        return None
    kept = words_in(run, segments)
    removed = echo_words_in(run, spans)
    if kept == 0:
        return PROMPT_ECHO_CAUSE if removed else DECODER_EMPTY_CAUSE
    if removed / (kept + removed) > ECHO_SHARE:
        return PROMPT_ECHO_CAUSE
    if covered_ms(run, segments) < LOW_COVERAGE * _length(run):
        return LOW_COVERAGE_CAUSE
    return None


def confident(segments: list[Segment]) -> bool:
    words = [w for seg in segments for w in seg.words]
    if not words:
        return bool(segments) and all(
            seg.avg_confidence >= MIN_SECOND_PASS_CONFIDENCE for seg in segments
        )
    return sum(w.probability for w in words) / len(words) >= MIN_SECOND_PASS_CONFIDENCE


def shift(segments: list[Segment], offset_ms: int) -> list[Segment]:
    """Slice-relative timestamps → recording time."""
    return [
        seg.model_copy(
            update={
                "start_ms": seg.start_ms + offset_ms,
                "end_ms": seg.end_ms + offset_ms,
                "words": [
                    w.model_copy(
                        update={"start_ms": w.start_ms + offset_ms, "end_ms": w.end_ms + offset_ms}
                    )
                    for w in seg.words
                ],
            }
        )
        for seg in segments
    ]


def _rebuild(words: list[WordTiming]) -> str:
    return " ".join(w.text.strip() for w in words if w.text.strip()).lstrip(" ,;:—-–").strip()


def splice(
    segments: list[Segment], start_ms: int, end_ms: int, replacement: list[Segment]
) -> list[Segment]:
    """Replace the words centred in ``[start_ms, end_ms)`` with ``replacement``.

    Word-level: a backend segment can straddle the slice; words outside it stay."""
    span = SpeechSegment(start_ms, end_ms)
    kept: list[Segment] = []
    for seg in segments:
        if not seg.words:
            if not _inside(span, seg.start_ms, seg.end_ms):
                kept.append(seg)
            continue
        words = [w for w in seg.words if not _inside(span, w.start_ms, w.end_ms)]
        if len(words) == len(seg.words):
            kept.append(seg)
            continue
        text = _rebuild(words)
        if not words or not text:
            continue
        kept.append(
            seg.model_copy(
                update={
                    "text": text,
                    "words": words,
                    "start_ms": words[0].start_ms,
                    "end_ms": words[-1].end_ms,
                }
            )
        )
    return sorted([*kept, *replacement], key=lambda s: (s.start_ms, s.end_ms))


def run_language(run: SpeechSegment, segments: list[Segment]) -> str | None:
    """The other language the first decode labelled this run with, if any."""
    for seg in segments:
        if seg.language and _inside(run, seg.start_ms, seg.end_ms):
            return seg.language
    return None


@dataclass(slots=True)
class RunOutcome:
    """What happened to one run, for the gap's cause."""

    run: SpeechSegment
    echo_removed: bool = False
    other_language: bool = False
    second_pass_words: int | None = None  # None = no second pass ran
    # The backend request for this run's group failed.
    backend_error: bool = False


def gap_cause(outcome: RunOutcome, *, first_frame_offset_ms: int | None) -> GapCause:
    run = outcome.run
    if (
        first_frame_offset_ms is not None
        and run.start_ms <= NO_AUDIO_TOLERANCE_MS
        and abs(run.end_ms - first_frame_offset_ms) <= NO_AUDIO_TOLERANCE_MS
    ):
        return "no_audio"
    if outcome.backend_error:
        return "backend_error"
    if run.floor_only:
        return "no_speech_detected"
    if outcome.echo_removed:
        return "prompt_echo"
    if outcome.other_language:
        return "other_language"
    if outcome.second_pass_words == 0:
        return "decoder_empty"
    return "unknown"


def _merge(gaps: list[CoverageGap]) -> list[CoverageGap]:
    """Adjacent gaps with one cause become one."""
    out: list[CoverageGap] = []
    for g in gaps:
        if out and out[-1].cause == g.cause and g.start_ms - out[-1].end_ms < WORD_REACH_MS:
            out[-1] = CoverageGap(start_ms=out[-1].start_ms, end_ms=g.end_ms, cause=g.cause)
        else:
            out.append(g)
    return out


def measure(
    runs: list[SpeechSegment],
    segments: list[Segment],
    outcomes: dict[tuple[int, int], RunOutcome],
    *,
    first_frame_offset_ms: int | None,
    stub: bool = False,
) -> Coverage:
    """Decision 1's numbers for the final transcript."""
    speech_ms = sum(_length(r) for r in runs)
    first_segment_ms = min((s.start_ms for s in segments), default=None)
    first_speech_ms = runs[0].start_ms if runs else None
    lead: list[CoverageGap] = []
    if first_frame_offset_ms is not None and first_frame_offset_ms >= MIN_GAP_MS:
        lead.append(CoverageGap(start_ms=0, end_ms=first_frame_offset_ms, cause="no_audio"))
    if stub:
        # No real VAD (dev fallback): one run, coverage complete by construction.
        return Coverage(
            speech_ms=speech_ms,
            transcribed_ms=speech_ms,
            first_speech_ms=first_speech_ms,
            first_segment_ms=first_segment_ms,
            gaps=lead,
            vad="stub",
        )
    gaps: list[CoverageGap] = []
    lost = 0
    for run in runs:
        if not is_gap(run, segments):
            continue
        lost += _length(run)
        outcome = outcomes.get((run.start_ms, run.end_ms)) or RunOutcome(run=run)
        gaps.append(
            CoverageGap(
                start_ms=run.start_ms,
                end_ms=run.end_ms,
                cause=gap_cause(outcome, first_frame_offset_ms=first_frame_offset_ms),
            )
        )
    return Coverage(
        speech_ms=speech_ms,
        transcribed_ms=max(0, speech_ms - lost),
        first_speech_ms=first_speech_ms,
        first_segment_ms=first_segment_ms,
        gaps=[*lead, *_merge(gaps)],
    )
