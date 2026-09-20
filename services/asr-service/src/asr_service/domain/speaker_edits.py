"""Speaker edit overlay (Sprint 28 merge, Sprint 30 reassign): pure folding.

The stored transcript is the raw diarization artifact and is never
rewritten. Edits are an ordered overlay: every read folds the live edits
of the current diarization run (``result_rev``) onto the segments in
``seq`` order, before the roster, names and turns are built. Labels are
never renumbered, so names stay keyed by label.

Fold order is ``seq`` and nothing else, so the result is deterministic and
independent of when it is read:

* ``merge`` relabels every segment currently carrying ``from_label`` —
  including segments an EARLIER reassign moved there;
* ``reassign`` relabels the segments it names (by ARTIFACT index) to
  ``to_label`` (``None`` = unattributed); a LATER merge of that label
  carries them along. The route resolves ``to_label`` through the merges
  that precede it, so a reassign always targets a surviving label.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from asr_models import SpeakerStatView


@dataclass(frozen=True)
class SpeakerEdit:
    id: UUID
    kind: str  # "merge" | "reassign"
    from_label: str | None
    to_label: str | None
    segment_indices: list[int]
    result_rev: int
    seq: int
    created_at: datetime
    creates_label: bool = False


class _Segment(Protocol):
    start_ms: int
    end_ms: int
    speaker: str | None

    def model_copy(self, *, update: dict[str, object]) -> _Segment: ...


def resolve_label(label: str, edits: Iterable[SpeakerEdit]) -> str:
    """Where ``label`` ends up after the merges (chains resolve: 3→2, 2→1 ends at 1)."""
    for edit in edits:
        if edit.kind == "merge" and edit.from_label == label and edit.to_label:
            label = edit.to_label
    return label


def fold_segment(
    label: str | None, index: int, edits: Sequence[SpeakerEdit]
) -> tuple[str | None, bool]:
    """One artifact segment's label after ``edits`` (``seq`` order), and
    whether a reassign touched it (a person decided this segment)."""
    touched = False
    for edit in edits:
        if edit.kind == "merge":
            if label is not None and label == edit.from_label and edit.to_label:
                label = edit.to_label
        elif edit.kind == "reassign" and index in edit.segment_indices:
            label = edit.to_label
            touched = True
    return label, touched


def fold_label(label: str | None, index: int, edits: Sequence[SpeakerEdit]) -> str | None:
    return fold_segment(label, index, edits)[0]


def host_index(seg: object, position: int) -> int:
    """The artifact segment a served segment is labelled by: its own
    ``artifact_index`` (absorbed punctuation follows its host, never the
    other way round), else its position in the artifact."""
    index = getattr(seg, "artifact_index", None)
    return int(index) if index is not None else position


def apply_edits[S: _Segment](segments: Sequence[S], edits: Sequence[SpeakerEdit]) -> list[S]:
    """Relabel segments by folding ``edits`` (already filtered).

    A segment a reassign touched is a person's decision: it is no longer
    ``speaker_uncertain``, and when it was made unattributed it is marked
    ``speaker_cleared`` so turn building never folds it back into a
    neighbour.
    """
    ordered = sorted(edits, key=lambda e: e.seq)
    out: list[S] = []
    for position, seg in enumerate(segments):
        label, touched = fold_segment(seg.speaker, host_index(seg, position), ordered)
        update: dict[str, object] = {}
        if label != seg.speaker:
            update["speaker"] = label
        if touched and hasattr(seg, "speaker_cleared"):
            update["speaker_uncertain"] = False
            update["speaker_cleared"] = label is None
        out.append(seg.model_copy(update=update) if update else seg)  # type: ignore[arg-type]
    return out


def roster_after(roster: Iterable[str], segments: Sequence[object]) -> list[str]:
    """The live roster once edits are folded: labels still on a segment,
    original roster order first, then new labels by first appearance. A
    label every segment was moved away from is gone."""
    present: list[str] = []
    for seg in segments:
        label = getattr(seg, "speaker", None)
        if label and label not in present:
            present.append(label)
    ordered = [label for label in roster if label in present]
    return ordered + [label for label in present if label not in ordered]


def next_free_label(known: Iterable[str | None]) -> str:
    """``SPEAKER_{max+1}`` over every label ever seen on the job (merged
    away ones included), so a new speaker never reuses an old name."""
    highest = 0
    for label in known:
        if label and label.startswith("SPEAKER_") and label[8:].isdigit():
            highest = max(highest, int(label[8:]))
    return f"SPEAKER_{highest + 1}"


def apply_to_roster(roster: Iterable[str], edits: Sequence[SpeakerEdit]) -> list[str]:
    ordered = sorted(edits, key=lambda e: e.seq)
    out: list[str] = []
    for label in roster:
        resolved = resolve_label(label, ordered)
        if resolved not in out:
            out.append(resolved)
    return out


def speaker_stats(segments: Sequence[object], roster: Sequence[str]) -> list[SpeakerStatView]:
    """Talk time per roster label: word spans when present, else the
    segment span. ``turns`` counts runs of consecutive segments."""
    speech: dict[str, int] = dict.fromkeys(roster, 0)
    turns: dict[str, int] = dict.fromkeys(roster, 0)
    previous: str | None = None
    for seg in segments:
        label = getattr(seg, "speaker", None)
        if label is None:
            previous = None
            continue
        words = getattr(seg, "words", None) or []
        spoken = (
            sum(w.end_ms - w.start_ms for w in words) if words else seg.end_ms - seg.start_ms  # type: ignore[attr-defined]
        )
        speech[label] = speech.get(label, 0) + max(0, spoken)
        if label != previous:
            turns[label] = turns.get(label, 0) + 1
        previous = label
    total = sum(speech.values())
    return [
        SpeakerStatView(
            label=label,
            speech_ms=speech.get(label, 0),
            share=round(speech.get(label, 0) / total, 4) if total else 0.0,
            turns=turns.get(label, 0),
        )
        for label in roster
    ]
