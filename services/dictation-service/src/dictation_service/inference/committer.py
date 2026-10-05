"""Partial-to-final commitment policy.

A word commits when it is past the revision horizon (the overlap, not the
full window), a silence boundary follows it, and no_speech_prob is low.
Committed words are immutable.
"""

from __future__ import annotations

from dataclasses import dataclass

from asr_models import Segment, WordTiming

from ..config import settings


@dataclass(slots=True)
class CommitDecision:
    """Per-word commit verdict."""

    word: WordTiming
    commit: bool
    reason: str = ""


@dataclass(slots=True)
class Committer:
    """Marks eligible words final per window; the rest stay provisional."""

    no_speech_threshold: float = settings.no_speech_prob_drop_threshold
    max_provisional_ms: int = settings.commit_max_provisional_ms

    def evaluate(
        self,
        *,
        candidates: list[WordTiming],
        now_ms: int,
        commit_horizon_ms: int,
        no_speech_prob: float,
        last_silence_boundary_ms: int | None,
    ) -> list[CommitDecision]:
        decisions: list[CommitDecision] = []
        for w in candidates:
            age_ms = now_ms - w.end_ms
            # Rule 3: hallucination guard.
            if no_speech_prob > self.no_speech_threshold:
                decisions.append(CommitDecision(word=w, commit=False, reason="high_no_speech_prob"))
                continue
            # Rule 1: past the revision horizon.
            if age_ms < commit_horizon_ms:
                decisions.append(CommitDecision(word=w, commit=False, reason="too_recent"))
                continue
            # Rule 2: a silence boundary after the word, else stay provisional...
            if last_silence_boundary_ms is None or last_silence_boundary_ms < w.end_ms:
                # ...but not forever: pause-free speech must not stall the transcript.
                if age_ms >= self.max_provisional_ms:
                    decisions.append(CommitDecision(word=w, commit=True, reason="stale_commit"))
                    continue
                decisions.append(CommitDecision(word=w, commit=False, reason="no_silence_boundary"))
                continue
            decisions.append(CommitDecision(word=w, commit=True, reason="ok"))
        return decisions


def words_to_final_segments(words: list[WordTiming]) -> list[Segment]:
    """Group adjacent committed words into :class:`Segment`s, splitting on gaps > 500 ms."""
    if not words:
        return []
    segments: list[Segment] = []
    bucket: list[WordTiming] = [words[0]]
    for prev, curr in zip(words, words[1:], strict=False):
        if curr.start_ms - prev.end_ms > 500:
            segments.append(_make_segment(bucket))
            bucket = [curr]
        else:
            bucket.append(curr)
    segments.append(_make_segment(bucket))
    return segments


def _make_segment(bucket: list[WordTiming]) -> Segment:
    text = " ".join(w.text for w in bucket).strip()
    avg = sum(w.probability for w in bucket) / len(bucket)
    return Segment(
        text=text,
        start_ms=bucket[0].start_ms,
        end_ms=bucket[-1].end_ms,
        words=bucket,
        avg_confidence=max(0.0, min(1.0, avg)),
    )
