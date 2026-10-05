"""Prompt-echo guard: words the decoder copied from its prompt come out, word by word.

Lexical and positional: a run of at least ``MIN_ECHO_RUN`` prompt tokens (one filler
allowed) within the first ``LEAD_WORDS`` words or after a ``GAP_MS`` pause is removed.
Only removes words; returns removed spans with timestamps. Pure and backend-agnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from asr_models.output import EchoSpan, Segment, WordTiming

MIN_ECHO_RUN: Final = 3
LEAD_WORDS: Final = 8
GAP_MS: Final = 1500

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def prompt_tokens(prompt: str | None) -> frozenset[str]:
    """The prompt's words, case-folded, punctuation off."""
    if not prompt:
        return frozenset()
    return frozenset(t.casefold() for t in _TOKEN.findall(prompt))


def prompt_terms(prompt: str | None) -> list[tuple[str, ...]]:
    """The prompt's comma-separated terms as token tuples ("Williams Jet
    Tender" is one term of three tokens)."""
    if not prompt:
        return []
    out: list[tuple[str, ...]] = []
    for part in prompt.split(","):
        tokens = tuple(t.casefold() for t in _TOKEN.findall(part))
        if tokens and tokens not in out:
            out.append(tokens)
    return out


def _is_echo(run_tokens: list[str], terms: list[tuple[str, ...]]) -> bool:
    """Echo = spans two or more distinct prompt terms, or repeats a token straight away."""
    if len(set(run_tokens)) < len(run_tokens):
        return True  # a word the decoder wrote twice: "Gysi, Moderator. Gysi, Moderator."
    occurrences = 0
    for term in terms:
        n = len(term)
        occurrences += sum(
            1 for k in range(len(run_tokens) - n + 1) if tuple(run_tokens[k : k + n]) == term
        )
        if occurrences >= 2:
            return True
    return False


def _token(text: str) -> str:
    found = _TOKEN.findall(text)
    return found[0].casefold() if found else ""


@dataclass(frozen=True, slots=True)
class _Run:
    start: int  # index of the first word in the run
    end: int  # index after the last word in the run
    prompt_words: int


def _runs(
    words: list[WordTiming], tokens: frozenset[str], terms: list[tuple[str, ...]]
) -> list[_Run]:
    """Every removable run, non-overlapping, left to right."""
    out: list[_Run] = []
    i = 0
    n = len(words)
    while i < n:
        is_prompt = _token(words[i].text) in tokens
        gap_before = words[i].start_ms - words[i - 1].end_ms if i > 0 else 0
        if not is_prompt or not (i < LEAD_WORDS or gap_before >= GAP_MS):
            i += 1
            continue
        # Extend over prompt tokens (one filler allowed); the run ends on the last prompt token.
        j = i
        last_prompt = i
        count = 0
        while j < n:
            token = _token(words[j].text)
            if token in tokens:
                count += 1
                last_prompt = j
                j += 1
                continue
            # One filler inside the run, never two, never at the end.
            if j + 1 < n and _token(words[j + 1].text) in tokens and last_prompt == j - 1:
                j += 1
                continue
            break
        end = last_prompt + 1
        run_tokens = [_token(w.text) for w in words[i:end] if _token(w.text) in tokens]
        if count >= MIN_ECHO_RUN and _is_echo(run_tokens, terms):
            out.append(_Run(start=i, end=end, prompt_words=count))
            i = end
        else:
            i += 1
    return out


def strip_prompt_echo(
    words: list[WordTiming], prompt: str | None
) -> tuple[list[WordTiming], list[EchoSpan]]:
    """``(kept words, removed spans)`` for one segment's words."""
    tokens = prompt_tokens(prompt)
    if not tokens or not words:
        return list(words), []
    runs = _runs(words, tokens, prompt_terms(prompt))
    if not runs:
        return list(words), []
    removed: set[int] = set()
    spans: list[EchoSpan] = []
    for run in runs:
        removed.update(range(run.start, run.end))
        spans.append(
            EchoSpan(
                start_ms=words[run.start].start_ms,
                end_ms=words[run.end - 1].end_ms,
                words=run.end - run.start,
            )
        )
    kept = [w for k, w in enumerate(words) if k not in removed]
    return kept, spans


def _rebuild_text(words: list[WordTiming]) -> str:
    text = " ".join(w.text.strip() for w in words if w.text.strip())
    # Leading punctuation left by a removed run is noise, not a word.
    return text.lstrip(" ,;:—-–").strip()


def _words_from_text(segment: Segment) -> list[WordTiming]:
    """Without word timings: one synthetic word per token at the segment's time."""
    return [
        WordTiming(text=t, start_ms=segment.start_ms, end_ms=segment.end_ms, probability=1.0)
        for t in segment.text.split()
    ]


def guard_segments(
    segments: list[Segment], prompt: str | None
) -> tuple[list[Segment], list[EchoSpan], int]:
    """``(segments kept, spans removed, segments dropped)``; a wordless segment is dropped."""
    if not prompt_tokens(prompt):
        return list(segments), [], 0
    kept_segments: list[Segment] = []
    all_spans: list[EchoSpan] = []
    dropped = 0
    for segment in segments:
        timed = bool(segment.words)
        words = segment.words if timed else _words_from_text(segment)
        kept, spans = strip_prompt_echo(words, prompt)
        if not spans:
            kept_segments.append(segment)
            continue
        all_spans.extend(spans)
        if not kept:
            dropped += 1
            continue
        text = _rebuild_text(kept)
        if not text:
            dropped += 1
            continue
        kept_segments.append(
            segment.model_copy(
                update={
                    "text": text,
                    "words": kept if timed else [],
                    "start_ms": kept[0].start_ms if timed else segment.start_ms,
                    "end_ms": kept[-1].end_ms if timed else segment.end_ms,
                }
            )
        )
    return kept_segments, all_spans, dropped
