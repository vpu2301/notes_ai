"""Transcript structure: segments → speaker turns → paragraphs.

Whisper hands back a flat list of short timed segments. Diarization
adds a speaker label to each. Neither is what a person wants to read:
a meeting is a sequence of *turns* ("Alice said this, then Bob said
that"), and a long turn is a few paragraphs, not a wall of text.

This module is the single place that structure is decided, so the web
app, the macOS app and the note built from the transcript all agree.
It is deliberately pure and dependency-free: a list of anything with
``text`` / ``start_ms`` / ``end_ms`` / ``speaker`` goes in, turns come
out. Rules:

* Consecutive segments by the same speaker form one turn.
* A segment the diarizer could not attribute joins the surrounding
  turn when the speaker before and after it is the same person (they
  were clearly mid-sentence); otherwise it stands as an unattributed
  turn — the honesty label, never silently merged into a neighbour.
* Inside a turn, a new paragraph starts at a noticeable pause once the
  paragraph has some length, or at a sentence end once it is long, or
  unconditionally once it is very long (a speaker who never pauses
  still gets readable blocks).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .output import TranscriptTurnView, default_speaker_name


class _SegmentLike(Protocol):
    text: str
    start_ms: int
    end_ms: int
    speaker: str | None


@dataclass(frozen=True)
class StructurePolicy:
    # A pause at least this long breaks a paragraph once the paragraph
    # is at least ``paragraph_min_chars`` long.
    pause_break_ms: int = 1500
    paragraph_min_chars: int = 160
    # Past this length a sentence end (". ! ? …") breaks the paragraph.
    paragraph_soft_chars: int = 600
    # Past this length the paragraph breaks at the next segment no
    # matter what.
    paragraph_hard_chars: int = 1000


DEFAULT_POLICY = StructurePolicy()

_SENTENCE_END = (".", "!", "?", "…", ".»", "!»", "?»", '."', '!"', '?"', ".)", "!)", "?)")


def build_turns(
    segments: list[_SegmentLike],
    *,
    speaker_names: dict[str, str] | None = None,
    policy: StructurePolicy = DEFAULT_POLICY,
) -> list[TranscriptTurnView]:
    """Group ``segments`` into speaker turns with paragraphs.

    ``speaker_names`` maps neutral labels to the names people gave them;
    a label without an entry renders under its neutral default.
    """
    names = speaker_names or {}
    runs = _speaker_runs(segments)
    turns: list[TranscriptTurnView] = []
    for speaker, indices in runs:
        paragraphs = _paragraphs([segments[i] for i in indices], policy)
        if not paragraphs:
            continue
        turns.append(
            TranscriptTurnView(
                speaker=speaker,
                name=(names.get(speaker) or default_speaker_name(speaker)) if speaker else None,
                start_ms=segments[indices[0]].start_ms,
                end_ms=max(segments[i].end_ms for i in indices),
                paragraphs=paragraphs,
                segment_indices=list(indices),
            )
        )
    return turns


def _speaker_runs(segments: list[_SegmentLike]) -> list[tuple[str | None, list[int]]]:
    """Consecutive same-speaker segment indices, with unattributed
    segments absorbed when they sit between two runs of one speaker."""
    labels: list[str | None] = [s.speaker or None for s in segments]

    # Fill None gaps whose neighbours agree.
    filled = list(labels)
    i = 0
    while i < len(filled):
        if filled[i] is not None:
            i += 1
            continue
        j = i
        while j < len(filled) and filled[j] is None:
            j += 1
        before = filled[i - 1] if i > 0 else None
        after = filled[j] if j < len(filled) else None
        if before is not None and before == after:
            for k in range(i, j):
                filled[k] = before
        i = j

    runs: list[tuple[str | None, list[int]]] = []
    for idx, label in enumerate(filled):
        if runs and runs[-1][0] == label:
            runs[-1][1].append(idx)
        else:
            runs.append((label, [idx]))
    return runs


def _paragraphs(segments: list[_SegmentLike], policy: StructurePolicy) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    length = 0
    prev_end: int | None = None
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        if current:
            gap = seg.start_ms - prev_end if prev_end is not None else 0
            ends_sentence = current[-1].endswith(_SENTENCE_END)
            if (
                length >= policy.paragraph_hard_chars
                or (length >= policy.paragraph_soft_chars and ends_sentence)
                or (length >= policy.paragraph_min_chars and gap >= policy.pause_break_ms)
            ):
                paragraphs.append(" ".join(current))
                current, length = [], 0
        current.append(text)
        length += len(text) + 1
        prev_end = seg.end_ms
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs
