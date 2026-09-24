"""Cutting a transcript into pieces a small model can actually read.

The single-pass baseline — one prompt, the whole meeting — loses the
middle of a long meeting: attention thins out, and an hour of talk does
not fit in a small model's context anyway. So the transcript is cut into
windows, each extracted separately, and the results merged.

Three rules make the cut safe:

* **Never mid-turn.** A window boundary inside someone's sentence
  produces half a commitment, and half a commitment is a wrong one. A
  single turn longer than the cap is split at sentence ends instead.
* **One turn of overlap.** A decision stated at the very end of one
  window is usually agreed at the start of the next; without overlap the
  agreement marker lands in a different call and the decision is
  downgraded to a key point.
* **Every millisecond covered exactly once**, so coverage by third
  (hypothesis E2) means something.

Lines are numbered — ``[7] Anna (12:04): …`` — because a fact cites its
line by that number, and :mod:`verify` uses the number to find the words
again. A LINE is one piece of a turn: a monologue cut into three pieces
is three lines with three numbers, so a flag or a citation on one piece
never reaches the others (Summary Engine v2, Q2 — until then the pieces
shared their turn's number, and one "noise" flag silenced a whole story).

Pure: turns in, windows out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Final

# Roughly 1.5–2.7 k tokens depending on the language — Ukrainian and
# German cost more characters per token than English, so the cap is in
# characters and deliberately conservative.
MAX_WINDOW_CHARS: Final = 6_000
# A single turn past this is a monologue; it is split at sentence ends.
# Small enough that a window holds at least two pieces, so the overlap
# carries real context rather than a window of one piece and nothing else.
MAX_TURN_CHARS: Final = 2_500
OVERLAP_TURNS: Final = 1

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…])$")


@dataclass(frozen=True, slots=True)
class Turn:
    """One speaker's uninterrupted stretch of talk."""

    index: int
    """Its number in the transcript — what a fact cites."""
    speaker_label: str | None
    speaker_name: str | None
    text: str
    start_ms: int
    end_ms: int
    """This piece's number in the transcript, unique across it; assigned by
    :func:`build_windows`. ``None`` for a turn nobody numbered (a test's
    hand-built window), which then answers to its turn index."""
    line: int | None = None
    """Q4 — a sound bite: someone quoted in the recording rather than taking
    part in it (see :func:`mark_clips`). Their opinions have no holder
    among the participants."""
    clip: bool = False

    @property
    def number(self) -> int:
        """What the model sees in brackets and cites."""
        return self.index if self.line is None else self.line

    @property
    def display_name(self) -> str:
        return self.speaker_name or self.speaker_label or "Unknown speaker"


@dataclass(frozen=True, slots=True)
class Window:
    index: int
    turns: tuple[Turn, ...] = field(default=())

    @property
    def start_ms(self) -> int:
        return self.turns[0].start_ms if self.turns else 0

    @property
    def end_ms(self) -> int:
        return self.turns[-1].end_ms if self.turns else 0

    @property
    def turn_numbers(self) -> frozenset[int]:
        """The line numbers in this window."""
        return frozenset(t.number for t in self.turns)

    def turn(self, number: int) -> Turn | None:
        """The piece with this line number."""
        return next((t for t in self.turns if t.number == number), None)

    def render(self) -> str:
        """The window as the model sees it: numbered, named, timed."""
        return "\n".join(
            f"[{t.number}] {t.display_name} ({_mmss(t.start_ms)}): {t.text}" for t in self.turns
        )

    @property
    def text(self) -> str:
        """Just the words, for substring checks."""
        return "\n".join(t.text for t in self.turns)


def _mmss(ms: int) -> str:
    total = max(0, ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def turns_from_result(result: dict[str, Any]) -> list[Turn]:
    """asr-service's ``/result`` → turns.

    Prefers the structured ``turns`` the ASR already built (consecutive
    same-speaker segments, display names applied); falls back to segments
    for an older producer or a fixture.
    """
    out: list[Turn] = []
    for raw in result.get("turns") or []:
        text = " ".join(str(p).strip() for p in (raw.get("paragraphs") or []) if str(p).strip())
        if not text:
            continue
        out.append(
            Turn(
                index=len(out),
                speaker_label=raw.get("speaker"),
                speaker_name=raw.get("name"),
                text=text,
                start_ms=int(raw.get("start_ms") or 0),
                end_ms=int(raw.get("end_ms") or raw.get("start_ms") or 0),
            )
        )
    if out:
        return out

    names = result.get("speaker_names") or {}
    for seg in result.get("segments") or []:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        label = seg.get("speaker")
        start = int(seg.get("start_ms") or round(float(seg.get("start") or 0) * 1000))
        end = int(seg.get("end_ms") or round(float(seg.get("end") or 0) * 1000)) or start
        if out and out[-1].speaker_label == label:
            # Merge consecutive segments from one speaker into a turn.
            previous = out.pop()
            out.append(
                Turn(
                    index=previous.index,
                    speaker_label=previous.speaker_label,
                    speaker_name=previous.speaker_name,
                    text=f"{previous.text} {text}",
                    start_ms=previous.start_ms,
                    end_ms=max(previous.end_ms, end),
                )
            )
            continue
        out.append(
            Turn(
                index=len(out),
                speaker_label=label,
                speaker_name=names.get(label) if label else None,
                text=text,
                start_ms=start,
                end_ms=end,
            )
        )
    return out


def split_long_turn(turn: Turn, *, cap: int = MAX_TURN_CHARS) -> list[Turn]:
    """A monologue, cut at sentence ends.

    The pieces keep the ORIGINAL turn's ``index`` (what the sidecar and the
    speaker roster key on); :func:`build_windows` gives each its own
    ``line``.
    """
    if len(turn.text) <= cap:
        return [turn]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(turn.text):
        if not sentence:
            continue
        if current and len(current) + len(sentence) + 1 > cap:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    if len(pieces) <= 1:
        # One sentence longer than the cap: cut on the character, which
        # is ugly but bounded. Better than one call that cannot run.
        pieces = [turn.text[i : i + cap] for i in range(0, len(turn.text), cap)]

    span = max(1, turn.end_ms - turn.start_ms)
    total = sum(len(p) for p in pieces) or 1
    out: list[Turn] = []
    elapsed = 0
    for piece in pieces:
        share = round(span * len(piece) / total)
        out.append(
            Turn(
                index=turn.index,
                speaker_label=turn.speaker_label,
                speaker_name=turn.speaker_name,
                text=piece,
                start_ms=turn.start_ms + elapsed,
                end_ms=turn.start_ms + elapsed + share,
            )
        )
        elapsed += share
    return out


# What a presenter says just before playing a clip.
_CLIP_CUE: Final = re.compile(
    r"\b(?:o-ton|sagte|sagt|erklärte|erklärt|hören wir|geäußert|äußerte|"
    r"said|says|listen to|here is|here's|"
    r"сказав|сказала|каже|послухаймо)\b",
    re.IGNORECASE,
)
CLIP_MAX_SHARE: Final = 0.08
CLIP_MAX_TURNS: Final = 2
CLIP_CUE_WITHIN_MS: Final = 15_000


def mark_clips(turns: list[Turn]) -> list[Turn]:
    """Mark the turns of a speaker who is played rather than present.

    A Hypothesis (Q4): a speaker with under 8 % of the speech, at most two
    turns, whose first turn follows a cue ("O-Ton", "sagte", "here is")
    in the previous speaker's words within 15 seconds. Measured against
    the ``speakers`` gold on broadcast recordings."""
    total = sum(max(0, t.end_ms - t.start_ms) for t in turns) or 1
    by_label: dict[str, list[Turn]] = {}
    for turn in turns:
        if turn.speaker_label:
            by_label.setdefault(turn.speaker_label, []).append(turn)
    clips: set[str] = set()
    for label, own in by_label.items():
        speech = sum(max(0, t.end_ms - t.start_ms) for t in own)
        if speech / total >= CLIP_MAX_SHARE or len(own) > CLIP_MAX_TURNS:
            continue
        first = own[0]
        before = [
            t
            for t in turns
            if t.speaker_label not in (None, label)
            and t.end_ms <= first.start_ms
            and first.start_ms - t.end_ms <= CLIP_CUE_WITHIN_MS
        ]
        if before and _CLIP_CUE.search(before[-1].text):
            clips.add(label)
    if not clips:
        return turns
    return [replace(t, clip=True) if t.speaker_label in clips else t for t in turns]


def build_windows(
    turns: list[Turn], *, max_chars: int = MAX_WINDOW_CHARS, overlap: int = OVERLAP_TURNS
) -> list[Window]:
    """The transcript as windows, in order."""
    pieces: list[Turn] = []
    for turn in mark_clips(turns):
        pieces.extend(split_long_turn(turn))
    if not pieces:
        return []
    # One number per piece, across the whole transcript.
    pieces = [replace(piece, line=n) for n, piece in enumerate(pieces)]

    windows: list[Window] = []
    current: list[Turn] = []
    size = 0
    for piece in pieces:
        cost = len(piece.text) + 24  # the "[7] Anna (12:04): " prefix
        if current and size + cost > max_chars:
            windows.append(Window(index=len(windows), turns=tuple(current)))
            # Carry the last turn(s) forward so an agreement that follows
            # a proposal is in the same call as the proposal.
            current = current[-overlap:] if overlap else []
            size = sum(len(t.text) + 24 for t in current)
        current.append(piece)
        size += cost
    if current:
        windows.append(Window(index=len(windows), turns=tuple(current)))
    return windows


def thirds(windows: list[Window]) -> dict[int, int]:
    """``{window index: 1|2|3}`` — which third of the meeting it is in.

    Coverage by third is hypothesis E2: a pipeline that quietly loses the
    middle of an hour-long meeting is the thing this design exists to
    avoid, and it is invisible without this split.
    """
    if not windows:
        return {}
    start, end = windows[0].start_ms, windows[-1].end_ms
    span = max(1, end - start)
    out: dict[int, int] = {}
    for window in windows:
        middle = (window.start_ms + window.end_ms) / 2
        share = (middle - start) / span
        out[window.index] = 1 if share < 1 / 3 else (2 if share < 2 / 3 else 3)
    return out
