"""The author's own ``user_notes`` lines: split, keyed, anchored to the recording.
The text is an INPUT, never polished. Anchoring uses the first-keystroke offset
(``[offset - 120 s, offset + 45 s]``: people type after hearing), else lexical
Jaccard against every window. Pure.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from ..action_items import item_key, normalise_text

# The clients' cap on one PUT of line times, and the most lines the engine will anchor.
MAX_USER_LINES: Final = 500

# People type after hearing, so the window reaches back further than forward.
LOOK_BACK_MS: Final = 120_000
LOOK_AHEAD_MS: Final = 45_000

# How many windows a line without a timestamp may fall back to.
LEXICAL_TOP_N: Final = 2
# Below this Jaccard the "match" is two stop words agreeing.
LEXICAL_FLOOR: Final = 0.08

# Stop words per language (a meeting is whatever language it was spoken in).
_STOP_WORDS: Final[frozenset[str]] = frozenset(
    # en
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "not",
        "of",
        "on",
        "or",
        "our",
        "she",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
    # de
    + [
        "aber",
        "auch",
        "auf",
        "aus",
        "bei",
        "dass",
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einer",
        "eines",
        "er",
        "es",
        "für",
        "hat",
        "haben",
        "ich",
        "ihr",
        "im",
        "in",
        "ist",
        "mit",
        "nicht",
        "noch",
        "nur",
        "oder",
        "sich",
        "sie",
        "sind",
        "über",
        "und",
        "von",
        "vor",
        "war",
        "wir",
        "wird",
        "zu",
        "zum",
        "zur",
    ]
    # uk
    + [
        "а",
        "але",
        "бо",
        "був",
        "була",
        "буде",
        "було",
        "вже",
        "ви",
        "від",
        "він",
        "вона",
        "вони",
        "все",
        "для",
        "до",
        "є",
        "же",
        "з",
        "за",
        "і",
        "із",
    ]
    + [
        "як",
        "який",
        "ми",
        "на",
        "не",
        "ні",
        "об",
        "або",
        "при",
        "про",
        "та",
        "так",
        "те",
        "то",
        "ти",
        "це",
        "цей",
        "чи",
        "що",
        "ще",
        "я",
    ]
)

# Words, with digits kept: "40k" and "2026" make a line findable.
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_MIN_TOKEN_LEN: Final = 2


@dataclass(frozen=True, slots=True)
class UserLine:
    """One line the author typed."""

    text: str
    """Verbatim, as typed — this is what goes back in the note."""
    line_key: str
    position: int
    offset_ms: int | None = None
    """First keystroke, relative to the recording's t=0; None when the
    client never reported one (an old client, or text pasted in later)."""


@dataclass(frozen=True, slots=True)
class Window:
    """A slice of transcript the engine reasons over."""

    index: int
    start_ms: int
    end_ms: int
    text: str


def line_key(text: str) -> str:
    """The stable identity of a typed line; one hashing rule with action items."""
    return item_key(normalise_text(text))


def split_lines(section_text: str, *, limit: int = MAX_USER_LINES) -> list[UserLine]:
    """The ``user_notes`` section as lines, in order: marker stripped for KEYING only,
    ``text`` exactly as typed; lines with one key collapse to the first."""
    out: list[UserLine] = []
    seen: set[str] = set()
    for raw in section_text.splitlines():
        text = raw.rstrip()
        if not text.strip():
            continue
        key = line_key(_strip_bullet(text))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(UserLine(text=text, line_key=key, position=len(out)))
        if len(out) == limit:
            break
    return out


_BULLET = re.compile(r"^[\s\-•*·▪◦]*(?:\d{1,2}[.)]\s*)?[\s\-•*·]*")


def _strip_bullet(text: str) -> str:
    return _BULLET.sub("", text, count=1)


def with_times(lines: list[UserLine], times: dict[str, int]) -> list[UserLine]:
    """Join the lines with the ``note_user_line_times`` sidecar."""
    return [
        line
        if line.line_key not in times
        else UserLine(
            text=line.text,
            line_key=line.line_key,
            position=line.position,
            offset_ms=times[line.line_key],
        )
        for line in lines
    ]


def anchor_lines(lines: list[UserLine], windows: list[Window]) -> dict[str, tuple[int, ...]]:
    """``{line_key: window indices}``, best first: every window overlapping a timed
    line's listening interval; else the top :data:`LEXICAL_TOP_N` by Jaccard, none
    below :data:`LEXICAL_FLOOR`."""
    if not windows:
        return {line.line_key: () for line in lines}

    tokenised: list[frozenset[str]] | None = None
    anchors: dict[str, tuple[int, ...]] = {}
    for line in lines:
        if line.offset_ms is not None:
            lo = line.offset_ms - LOOK_BACK_MS
            hi = line.offset_ms + LOOK_AHEAD_MS
            hits = tuple(w.index for w in windows if w.start_ms <= hi and w.end_ms >= lo)
            if hits:
                anchors[line.line_key] = hits
                continue
            # Outside every window: fall through to the words.
        if tokenised is None:  # pay for it only when a line needs it
            tokenised = [content_tokens(w.text) for w in windows]
        anchors[line.line_key] = _lexical_anchors(line.text, tokenised)
    return anchors


def _lexical_anchors(text: str, windows: list[frozenset[str]]) -> tuple[int, ...]:
    needle = content_tokens(text)
    if not needle:
        return ()
    scored = [(_jaccard(needle, hay), index) for index, hay in enumerate(windows) if hay]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return tuple(index for score, index in scored[:LEXICAL_TOP_N] if score >= LEXICAL_FLOOR)


def content_tokens(text: str) -> frozenset[str]:
    """Lower-cased words of two+ characters, accents folded, stop words dropped."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return frozenset(
        token
        for token in _WORD.findall(folded)
        if len(token) >= _MIN_TOKEN_LEN and token not in _STOP_WORDS
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    overlap = len(a & b)
    return overlap / len(a | b) if overlap else 0.0


def coverage_states(lines: list[UserLine], supported: set[str]) -> dict[str, str]:
    """Every line ``supported`` or ``unsupported``; an unsupported line is KEPT and
    marked, never dropped or "corrected"."""
    return {
        line.line_key: "supported" if line.line_key in supported else "unsupported"
        for line in lines
    }
