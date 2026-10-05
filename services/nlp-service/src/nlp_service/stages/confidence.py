"""Stage 6: confidence spans over the post-processed text from per-word Whisper probabilities.

Levels: < high_concern_below → high_concern, < moderate_below → moderate; adjacent same-level spans merge.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from ..config import settings
from ..pipeline.base import (
    ConfidenceSpan,
    ProcessingContext,
    StageInput,
    StageOutput,
    Word,
)

logger = logging.getLogger(__name__)


class ConfidenceStage:
    """Stage 6."""

    name = "confidence"
    runs_on_partials: bool = True

    async def process(self, ctx: ProcessingContext, input: StageInput) -> StageOutput:
        t0 = time.monotonic()
        spans = _compute_spans(
            text=input.text,
            words=input.words,
            high_below=settings.confidence_high_concern_below,
            moderate_below=settings.confidence_moderate_below,
        )
        return StageOutput(
            text=input.text,
            words=input.words,
            confidence_spans=tuple(spans),
            voice_commands=input.voice_commands,
            operations=input.operations,
            warnings=input.warnings,
            metadata={
                self.name + ".latency_ms": (time.monotonic() - t0) * 1000.0,
                self.name + ".spans": len(spans),
            },
        )


def _compute_spans(
    *,
    text: str,
    words: tuple[Word, ...],
    high_below: float,
    moderate_below: float,
) -> list[ConfidenceSpan]:
    """Locate each non-command word in ``text`` and label by probability; adjacent same-level spans merge."""
    out: list[ConfidenceSpan] = []
    cursor = 0
    text_lower = text.lower()
    for w in words:
        if w.is_voice_command_token:
            continue
        if w.probability >= moderate_below:
            continue
        level: Literal["high_concern", "moderate"] = (
            "high_concern" if w.probability < high_below else "moderate"
        )
        # Whole-word match only, else a short word ("і") paints a cue inside a longer one.
        needle = w.text.lower()
        start = _find_word(text_lower, needle, cursor)
        if start == -1:
            continue  # reformatted beyond locating; drop the word
        end = start + len(needle)
        cursor = end
        # Merge with previous if adjacent + same level.
        if out:
            last = out[-1]
            if last.level == level and text[last.end_char : start].strip() == "":
                out[-1] = ConfidenceSpan(
                    start_char=last.start_char,
                    end_char=end,
                    level=level,
                )
                continue
        out.append(ConfidenceSpan(start_char=start, end_char=end, level=level))
    return out


def _find_word(haystack: str, needle: str, start_at: int) -> int:
    """Index of the next whole-word (Unicode-aware) occurrence of ``needle`` at or after ``start_at``, or -1."""
    if not needle:
        return -1
    nlen = len(needle)
    pos = start_at
    while True:
        idx = haystack.find(needle, pos)
        if idx == -1:
            return -1
        before_ok = idx == 0 or not haystack[idx - 1].isalnum()
        after = idx + nlen
        after_ok = after == len(haystack) or not haystack[after].isalnum()
        if before_ok and after_ok:
            return idx
        pos = idx + 1
