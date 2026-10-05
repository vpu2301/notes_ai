"""Parakeet output as the OpenAI-style ``verbose_json`` the worker's ``asr_http`` reads
(ADR-0037: words with times are a contract). Pure functions: tokens -> words -> segments.
``language`` is echoed only when the caller named one; the segment-quality fields are
absent and the worker treats them as unavailable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# A token's duration when nothing follows it (Parakeet's 80 ms frame).
FRAME_S = 0.08
# A word ends at the next word's start only when the two are close (no pause).
LAST_TOKEN_MAX_S = 0.4
SEGMENT_MAX_S = 30.0
SEGMENT_GAP_S = 1.0
_SENTENCE_END = (".", "?", "!", "…")


@dataclass(frozen=True)
class Word:
    word: str
    start: float
    end: float
    probability: float | None = None


def words_from_tokens(
    tokens: Sequence[str],
    starts: Sequence[float],
    logprobs: Sequence[float] | None = None,
    *,
    duration: float | None = None,
) -> list[Word]:
    """Join SentencePiece tokens into words; a word's probability is its lowest token's."""
    out: list[Word] = []
    pieces: list[tuple[str, float, float | None]] = []

    def flush(next_start: float | None) -> None:
        if not pieces:
            return
        text = "".join(p[0] for p in pieces).strip()
        start = pieces[0][1]
        last = pieces[-1][1]
        end = min(next_start, last + LAST_TOKEN_MAX_S) if next_start is not None else last + FRAME_S
        if duration is not None:
            end = min(end, duration)
        probs = [p[2] for p in pieces if p[2] is not None]
        prob = min(probs) if probs else None
        if text:
            out.append(Word(text, round(start, 3), round(max(end, start), 3), prob))
        pieces.clear()

    for k, (tok, start) in enumerate(zip(tokens, starts, strict=False)):
        lp = logprobs[k] if logprobs is not None and k < len(logprobs) else None
        prob = None if lp is None else max(0.0, min(1.0, math.exp(float(lp))))
        if tok.startswith((" ", "▁")) and pieces:
            flush(float(start))
        pieces.append((tok.replace("▁", " "), float(start), prob))
    flush(None)
    return out


def segments_from_words(words: Sequence[Word]) -> list[dict[str, Any]]:
    """Sentences: cut after terminal punctuation, at a pause of a second, or at 30 s."""
    segments: list[dict[str, Any]] = []
    current: list[Word] = []

    def close() -> None:
        if current:
            segments.append(
                {
                    "id": len(segments),
                    "start": current[0].start,
                    "end": current[-1].end,
                    "text": " " + " ".join(w.word for w in current),
                }
            )
            current.clear()

    for w in words:
        if current and (
            w.start - current[-1].end >= SEGMENT_GAP_S or w.end - current[0].start > SEGMENT_MAX_S
        ):
            close()
        current.append(w)
        if w.word.endswith(_SENTENCE_END):
            close()
    close()
    return segments


def verbose_json(words: Sequence[Word], *, duration: float, language: str | None) -> dict[str, Any]:
    """The reply body. ``language`` only when the caller pinned one."""
    body: dict[str, Any] = {
        "task": "transcribe",
        "duration": round(duration, 3),
        "text": " ".join(w.word for w in words),
        "segments": segments_from_words(words),
        "words": [
            {
                k: v
                for k, v in (
                    ("word", w.word),
                    ("start", w.start),
                    ("end", w.end),
                    ("probability", w.probability),
                )
                if v is not None
            }
            for w in words
        ],
    }
    if language and language != "auto":
        body["language"] = language
    return body
