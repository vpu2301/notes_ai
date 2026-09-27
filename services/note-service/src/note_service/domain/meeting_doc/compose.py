"""Sprint D2 — composition to the document standard, the parts code owns.

* :class:`VolumeBudget` — from the duration of transcribed speech, before
  any call: target words ``12·D``, bullets per block 2–6, three sub-points,
  three to six orientation sentences.
* :func:`blocks` — facts cut into time-contiguous blocks: ``round(D/4)`` of
  them within [3, 8], each ≥ 4 facts, cut at the largest gaps in time and
  where the extractor reported a new topic.
* :func:`top_per_block` — the most specific fact of each block: the
  skeleton of orientation paragraph 2.
* :func:`orientation_p1` — paragraph 1 from the roles table, the reader's
  type word, the show, the subject and the themes.
* :func:`fallback_heading` — a block with no usable heading: its name and
  first time.

Pure: facts and values in, structures out.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from . import overview, roles_table, support
from .verify import VerifiedFact, _has_date_word
from .windows import Turn

MIN_BLOCKS: Final = 3
MAX_BLOCKS: Final = 8
MINUTES_PER_BLOCK: Final = 4
MIN_BLOCK_FACTS: Final = 4
# A new topic the extractor reported counts like a gap of this long.
TOPIC_SHIFT_MS: Final = 5 * 60_000
WORDS_PER_MINUTE: Final = 12
WORDS_PER_BULLET: Final = 15
ORIENTATION_WORDS: Final = 100
BULLETS: Final = (2, 6)
CHILDREN: Final = 3
P2_SENTENCES: Final = (3, 6)
QUOTE_CHILD_WORDS: Final = 20


@dataclass(frozen=True, slots=True)
class VolumeBudget:
    minutes: float
    blocks: int = 1

    @property
    def target_words(self) -> int:
        return round(WORDS_PER_MINUTE * self.minutes)

    @property
    def bullets_per_block(self) -> int:
        """What one block's call is asked for; selection keeps to it."""
        body = max(0, self.target_words - ORIENTATION_WORDS)
        per_block = round(body / WORDS_PER_BULLET / max(1, self.blocks))
        return max(BULLETS[0], min(BULLETS[1], per_block))


@dataclass(frozen=True, slots=True)
class Block:
    index: int
    facts: tuple[VerifiedFact, ...]

    @property
    def span(self) -> tuple[int, int]:
        return self.facts[0].start_ms, self.facts[-1].start_ms


def target_blocks(minutes: float) -> int:
    return max(MIN_BLOCKS, min(MAX_BLOCKS, round(minutes / MINUTES_PER_BLOCK)))


def blocks(
    facts: Sequence[VerifiedFact],
    minutes: float,
    topic_titles: dict[int, str] | None = None,
) -> list[Block]:
    """Time-contiguous blocks. A recording too short for three blocks of
    four facts gets as many as it can fill (at least one)."""
    ordered = sorted(facts, key=lambda f: (f.start_ms, f.item_key))
    if not ordered:
        return []
    titles = topic_titles or {}
    wanted = min(target_blocks(minutes), max(1, len(ordered) // MIN_BLOCK_FACTS))
    scores = []
    for k in range(1, len(ordered)):
        gap = ordered[k].start_ms - ordered[k - 1].start_ms
        before = titles.get(ordered[k - 1].window_index, "").strip().casefold()
        after = titles.get(ordered[k].window_index, "").strip().casefold()
        shift = TOPIC_SHIFT_MS if before and after and before != after else 0
        scores.append((gap + shift, k))
    cuts: list[int] = []
    for _score, k in sorted(scores, reverse=True):
        if len(cuts) >= wanted - 1:
            break
        trial = sorted([*cuts, k])
        edges = [0, *trial, len(ordered)]
        if all(b - a >= MIN_BLOCK_FACTS for a, b in zip(edges, edges[1:], strict=False)):
            cuts = trial
    edges = [0, *sorted(cuts), len(ordered)]
    return [
        Block(n, tuple(ordered[a:b]))
        for n, (a, b) in enumerate(zip(edges, edges[1:], strict=False))
    ]


def specificity(fact: VerifiedFact, language: str, known: frozenset[str]) -> int:
    return support.specificity(fact.text, language, known=known, has_date=_has_date_word(fact.text))


def top_per_block(
    parts: Sequence[Block], language: str, known: frozenset[str] = frozenset()
) -> list[VerifiedFact]:
    """The most specific statement of each block (ties: the earlier)."""
    out = []
    for block in parts:
        usable = [
            f for f in block.facts if not f.evidence_only and f.figure is None and f.person is None
        ]
        if usable:
            out.append(max(usable, key=lambda f: (specificity(f, language, known), -f.start_ms)))
    return out


def fallback_heading(facts: Sequence[VerifiedFact], language: str, known: frozenset[str]) -> str:
    if not facts:
        return ""
    name = overview._top_name(list(facts), language, known)
    if not name:
        runs = Counter(run for f in facts for run in support.capital_runs(f.text))
        name = runs.most_common(1)[0][0] if runs else ""
    stamp = overview.mmss(min(f.start_ms for f in facts))
    return f"{stamp} — {name}" if name else stamp


def quote_child(fact: VerifiedFact, speaker: str | None, language: str) -> str | None:
    """T2 — a quote sub-point from the fact's own quote, never from model
    text: „…" — Name (mm:ss), cut to 20 words at a word. None when nobody
    verified the speaker's name: a label is never written."""
    name = roles_table.real_name(speaker)
    words = fact.quote.split()
    if not name or not words:
        return None
    cut = " ".join(words[:QUOTE_CHILD_WORDS])
    if len(words) > QUOTE_CHILD_WORDS:
        cut = cut.rstrip(",;:") + " …"
    opening, closing = _QUOTES.get(language, _QUOTES["en"])
    return f"{opening}{cut.strip()}{closing} — {name} ({overview.mmss(fact.start_ms)})"


_QUOTES: Final[dict[str, tuple[str, str]]] = {"en": ("“", "”"), "de": ("„", "“"), "uk": ("«", "»")}


# ── orientation paragraph 1 (T4) ────────────────────────────────────

# The reader's word for each role, per language.
_ROLE_WORDS: Final[dict[str, dict[str, str]]] = {
    "en": {"narrator": "the narrator", "host": "the host"},
    "de": {"narrator": "Erzähler/in", "host": "Moderator/in"},
    "uk": {"narrator": "оповідач", "host": "ведучий"},
}
_SHOW: Final = re.compile(
    r"\b(?P<show>[A-ZÄÖÜ][\w'’-]{2,}(?:\s[A-ZÄÖÜ][\w'’-]{2,})?)\s+(?:Podcast|podcast)\b"
    r"|(?:willkommen (?:bei|zu|zum)|welcome to|ви слухаєте)\s+(?P<show2>[A-ZÄÖÜ][\w'’-]{2,}"
    r"(?:\s[A-ZÄÖÜ][\w'’-]{2,}){0,2})",
    re.IGNORECASE,
)
SHOW_WITHIN_MS: Final = 3 * 60_000


def show_name(turns: Sequence[Turn]) -> str | None:
    """The show, only as a jingle or an introduction line says it in the
    first minutes ("Simplicissimus Podcast", "Willkommen bei …")."""
    for turn in turns:
        if turn.start_ms > SHOW_WITHIN_MS:
            break
        match = _SHOW.search(turn.text)
        if match:
            name = (match["show"] or match["show2"] or "").strip()
            if name and name[0].isupper():
                return name
    return None


def speakers_of(table: roles_table.RolesTable, language: str) -> tuple[list[str], list[str]]:
    """``(speakers, guests)`` for paragraph 1: the narrator or host by role
    (and name when introduced), participants by verified name only, guests
    and interviewees as "Name (organisation)". Clips and adverts: nobody."""
    words = _ROLE_WORDS.get(language, _ROLE_WORDS["en"])
    speakers: list[str] = []
    guests: list[str] = []
    for s in sorted(table.speakers.values(), key=lambda s: -s.share):
        if s.role in (roles_table.NARRATOR, roles_table.HOST):
            speakers.append(s.name or words[s.role])
        elif s.role in (roles_table.GUEST, roles_table.INTERVIEWEE) and s.name:
            where = ", ".join(
                p for p in (s.introduced_as.organisation if s.introduced_as else "",) if p
            )
            guests.append(f"{s.name} ({where})" if where else s.name)
        elif s.role == roles_table.PARTICIPANT and s.name:
            speakers.append(s.name)
    return speakers, guests


def orientation_p1(
    *,
    language: str,
    recording_type: str | None,
    table: roles_table.RolesTable,
    subject: str = "",
    framing: str = "",
    themes: Sequence[str] = (),
    show: str | None = None,
) -> str:
    speakers, guests = speakers_of(table, language)
    text = overview.first_paragraph(
        language=language,
        recording_type=recording_type,
        subject=subject,
        framing=framing,
        speakers=speakers,
        guests=guests,
        themes=list(themes),
    )
    if show and not framing.strip():
        labels = overview.TYPE_LABELS.get(language, overview.TYPE_LABELS["en"])
        word = labels.get(recording_type or "meeting") or labels["meeting"]
        if text.startswith(word):
            text = f"{word} ({show}){text[len(word) :]}"
    return text
