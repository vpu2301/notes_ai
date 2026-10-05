"""Transcript structure: segments → speaker turns → paragraphs (pure; the single place structure is decided).

Unattributed segments join the surrounding turn only when both neighbours are the same speaker;
``segment_indices`` address the STORED ARTIFACT (``artifact_indices``) when present.
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
    # A pause this long breaks a paragraph once it is ``paragraph_min_chars`` long.
    pause_break_ms: int = 1500
    paragraph_min_chars: int = 160
    # Past this length a sentence end breaks the paragraph.
    paragraph_soft_chars: int = 600
    # Past this length the next segment breaks it unconditionally.
    paragraph_hard_chars: int = 1000


DEFAULT_POLICY = StructurePolicy()

_SENTENCE_END = (".", "!", "?", "…", ".»", "!»", "?»", '."', '!"', '?"', ".)", "!)", "?)")


def build_turns(
    segments: list[_SegmentLike],
    *,
    speaker_names: dict[str, str] | None = None,
    policy: StructurePolicy = DEFAULT_POLICY,
    overlap_ms: list[tuple[int, int]] | None = None,
) -> list[TranscriptTurnView]:
    """Group ``segments`` into speaker turns with paragraphs; unnamed labels render under their neutral default."""
    names = speaker_names or {}
    overlaps = overlap_ms or []
    runs = _speaker_runs(segments)
    turns: list[TranscriptTurnView] = []
    for speaker, indices, absorbed in _split_by_language(segments, runs):
        run = [segments[i] for i in indices]
        paragraphs = _paragraphs(run, policy)
        if not paragraphs:
            continue
        artifact: list[int] = []
        for i, seg in zip(indices, run, strict=True):
            artifact.extend(getattr(seg, "artifact_indices", None) or [i])
        uncertain = (
            (absorbed and speaker is not None)
            or any(getattr(seg, "speaker_uncertain", False) for seg in run)
            or any(_overlaps(seg, overlaps) for seg in run)
        )
        turns.append(
            TranscriptTurnView(
                speaker=speaker,
                name=(names.get(speaker) or default_speaker_name(speaker)) if speaker else None,
                start_ms=run[0].start_ms,
                end_ms=max(seg.end_ms for seg in run),
                paragraphs=paragraphs,
                segment_indices=artifact,
                uncertain=bool(uncertain),
                language=getattr(run[0], "language", None) or None,
            )
        )
    return turns


def _split_by_language(
    segments: list[_SegmentLike], runs: list[tuple[str | None, list[int], bool]]
) -> list[tuple[str | None, list[int], bool]]:
    """A turn is never in two languages: a speaker run breaks where ``language`` changes."""
    out: list[tuple[str | None, list[int], bool]] = []
    for speaker, indices, absorbed in runs:
        current: list[int] = []
        language: str | None = None
        for idx in indices:
            here = getattr(segments[idx], "language", None) or None
            if current and here != language:
                out.append((speaker, current, absorbed))
                current = []
            current.append(idx)
            language = here
        if current:
            out.append((speaker, current, absorbed))
    return out


def _overlaps(seg: _SegmentLike, spans: list[tuple[int, int]]) -> bool:
    return any(a < seg.end_ms and seg.start_ms < b for a, b in spans)


def _speaker_runs(segments: list[_SegmentLike]) -> list[tuple[str | None, list[int], bool]]:
    """Consecutive same-speaker runs; unattributed segments between two runs of one speaker are absorbed (flag)."""
    labels: list[str | None] = [s.speaker or None for s in segments]
    # Person-cleared segments are never filled and bound the gaps around them.
    cleared = [bool(getattr(s, "speaker_cleared", False)) for s in segments]

    # Fill None gaps whose neighbours agree.
    filled = list(labels)
    i = 0
    while i < len(filled):
        if filled[i] is not None or cleared[i]:
            i += 1
            continue
        j = i
        while j < len(filled) and filled[j] is None and not cleared[j]:
            j += 1
        before = filled[i - 1] if i > 0 else None
        after = filled[j] if j < len(filled) else None
        if before is not None and before == after:
            for k in range(i, j):
                filled[k] = before
        i = j

    runs: list[tuple[str | None, list[int], bool]] = []
    for idx, label in enumerate(filled):
        absorbed = labels[idx] is None and label is not None
        if runs and runs[-1][0] == label:
            runs[-1][1].append(idx)
            if absorbed:
                runs[-1] = (label, runs[-1][1], True)
        else:
            runs.append((label, [idx], absorbed))
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
