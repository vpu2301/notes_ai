"""Composition to the document standard, the parts code owns: the volume budget
from speech duration, time-contiguous blocks, the skeleton of paragraph 2,
paragraph 1, fallback headings. Pure.
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
    """A quote sub-point from the fact's own quote: „…" — Name (mm:ss), cut to 20
    words. None without a verified speaker name: a label is never written."""
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


# ── orientation paragraph 1 ─────────────────────────────────────────

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


# The role words of paragraph 1, and the person nobody named.
_ROLE_NOUNS: Final[dict[str, dict[str, str]]] = {
    "en": {"expert": "expert", "interviewee": "interviewee"},
    "de": {"expert": "Experte/Expertin", "interviewee": "Interviewpartner/in"},
    "uk": {"expert": "експерт", "interviewee": "співрозмовник"},
}
_UNNAMED: Final[dict[str, tuple[str, str]]] = {
    "en": ("another person", "{n} other people"),
    "de": ("eine weitere Person", "{n} weitere Personen"),
    "uk": ("ще одна особа", "ще {n} особи"),
}
LIST_MIN_SHARE: Final = 0.05
_ARTICLE: Final = re.compile(r"^(?:a|an|the|ein|eine|einen|der|die|das)\s+", re.IGNORECASE)


def _described(s: roles_table.Speaker, role_word: str | None, language: str = "en") -> str:
    """``Name (role with organisation, qualifier)`` from the verified introduction
    fields; ``role_word`` stands in when the introduction gives no role."""
    from .render import PRESENTER_LABELS

    person = s.introduced_as
    name = s.name or ""
    role = _ARTICLE.sub("", person.role).strip() if person else ""
    role = role or (role_word or "")
    org = (person.organisation if person else "").strip()
    joiner = (person.joiner if person else "") or PRESENTER_LABELS.get(
        language, PRESENTER_LABELS["en"]
    )[2]
    what = f"{role} {joiner} {org}" if role and org else (role or org)
    qualifier = _ARTICLE.sub("", person.qualifier).strip() if person else ""
    bits = [b for b in (what, qualifier) if b]
    return f"{name} ({', '.join(bits)})" if bits and name else name


def speakers_of(
    table: roles_table.RolesTable, language: str
) -> tuple[list[str], list[str], list[str]]:
    """``(speakers, guests, others)`` for paragraph 1: every voice with >= 5 % of the
    speech or a role, by role rank then share. An unnamed voice is "eine weitere
    Person", never a label; clips and adverts are nobody."""
    words = _ROLE_WORDS.get(language, _ROLE_WORDS["en"])
    nouns = _ROLE_NOUNS.get(language, _ROLE_NOUNS["en"])
    one, many = _UNNAMED.get(language, _UNNAMED["en"])
    listed = [
        s
        for s in table.speakers.values()
        if s.role in roles_table.ROLE_RANK
        and (s.share >= LIST_MIN_SHARE or s.role != roles_table.PARTICIPANT)
    ]
    listed.sort(key=lambda s: (roles_table.ROLE_RANK[s.role], -s.share))
    speakers: list[str] = []
    guests: list[str] = []
    others: list[str] = []
    unnamed = 0
    for s in listed:
        name = roles_table.real_name(s.name)
        if s.role in (roles_table.NARRATOR, roles_table.HOST):
            # A presenter who introduced themselves: their own role and organisation.
            if name:
                speakers.append(_described(s, words[s.role], language))
            else:
                speakers.append(words[s.role])
        elif s.role == roles_table.EXPERT:
            speakers.append(
                _described(s, nouns["expert"], language) if name else f"{one} ({nouns['expert']})"
            )
        elif s.role == roles_table.GUEST:
            guests.append(_described(s, None, language) if name else one)
        elif s.role == roles_table.INTERVIEWEE:
            others.append(
                _described(s, nouns["interviewee"], language)
                if name
                else f"{one} ({nouns['interviewee']})"
            )
        elif name:
            others.append(name)
        else:
            unnamed += 1
    if unnamed:
        others.append(one if unnamed == 1 else many.format(n=unnamed))
    return speakers, guests, others


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
    speakers, guests, others = speakers_of(table, language)
    text = overview.first_paragraph(
        language=language,
        recording_type=recording_type,
        subject=subject,
        framing=framing,
        speakers=speakers,
        guests=guests,
        others=others,
        themes=list(themes),
    )
    if show and not framing.strip():
        labels = overview.TYPE_LABELS.get(language, overview.TYPE_LABELS["en"])
        word = labels.get(recording_type or "meeting") or labels["meeting"]
        if text.startswith(word):
            text = f"{word} ({show}){text[len(word) :]}"
    return text


MAX_THEMES: Final = 5
_THEME_SPLIT: Final = re.compile(r"[,;]|[„“”\"«»]")


def clean_themes(themes: Sequence[str]) -> list[str]:
    """Themes as a reader's list: packed quoted themes split and unquoted; a cut fragment ends the list."""
    out: list[str] = []
    for theme in themes:
        parts = [p.strip(" .-—") for p in _THEME_SPLIT.split(theme)]
        pieces = [p for p in parts if len(p) >= 3]
        if len(pieces) > 1 and len(theme) >= 50:
            pieces = pieces[:-1]  # the last piece of a long, packed answer is often cut
        for piece in pieces:
            if piece.casefold() not in {o.casefold() for o in out}:
                out.append(piece)
    return out


# ── Sections follow the recording ───────────────────────────────────
# Block boundaries come from the TRANSCRIPT: spoken cues, else lexical shifts
# over two-minute tiles (TextTiling, no model call), reconciled to round(D/4)
# within [3, 8]. No shift at all: equal blocks. A block under two facts joins its neighbour.

TILE_MS: Final = 120_000
TILING_SIDE: Final = 2  # tiles compared either side of a gap
MIN_SEGMENT_FACTS: Final = 2
# A cue and a lexical boundary closer than this are the same boundary.
BOUNDARY_NEAR_MS: Final = 90_000
# Below this depth a gap is not a shift (cosines are 0–1).
MIN_DEPTH: Final = 0.05
CUE_STRENGTH: Final = 2.0  # a spoken cue outranks any lexical depth

SOURCE_CUES: Final = "cues"
SOURCE_LEXICAL: Final = "lexical"
SOURCE_MIXED: Final = "cues+lexical"
SOURCE_UNIFORM: Final = "uniform"
SOURCE_SINGLE: Final = "single"


@dataclass(frozen=True, slots=True)
class Segmentation:
    """Where the recording's parts begin (ms, ascending, the first part's
    start excluded) and what found them."""

    boundaries: tuple[int, ...]
    source: str


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def lexical_shifts(turns: Sequence[Turn], language: str) -> list[tuple[int, float]]:
    """``[(boundary ms, depth)]`` at every tile gap, strongest first: cosine of the
    content words either side, depth against the neighbouring peaks."""
    if not turns:
        return []
    start = turns[0].start_ms
    tiles: list[Counter[str]] = []
    starts: list[int] = []
    for turn in turns:
        k = max(0, (turn.start_ms - start) // TILE_MS)
        while len(tiles) <= k:
            tiles.append(Counter())
            starts.append(start + len(starts) * TILE_MS)
        tiles[k].update(support.content_tokens(turn.text, language))
    if len(tiles) < 2:
        return []
    scores: list[float] = []
    for gap in range(1, len(tiles)):
        left = sum((tiles[i] for i in range(max(0, gap - TILING_SIDE), gap)), Counter())
        right = sum((tiles[i] for i in range(gap, min(len(tiles), gap + TILING_SIDE))), Counter())
        scores.append(_cosine(left, right))
    out: list[tuple[int, float]] = []
    for i, score in enumerate(scores):
        left_peak = max(scores[: i + 1])
        right_peak = max(scores[i:])
        depth = (left_peak - score) + (right_peak - score)
        if depth >= MIN_DEPTH:
            out.append((starts[i + 1], depth))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def segment(
    turns: Sequence[Turn],
    minutes: float,
    language: str,
    cue_starts: Sequence[int] = (),
) -> Segmentation:
    """The recording's parts: cues first, lexical shifts to fill, the
    weakest dropped to ``target_blocks(minutes)``; equal parts when the
    transcript has no shift at all."""
    if not turns:
        return Segmentation((), SOURCE_SINGLE)
    start, end = turns[0].start_ms, turns[-1].end_ms
    wanted = target_blocks(minutes) - 1
    candidates: list[tuple[int, float, str]] = [
        (ms, CUE_STRENGTH, SOURCE_CUES)
        for ms in sorted(set(cue_starts))
        if start + BOUNDARY_NEAR_MS <= ms <= end - BOUNDARY_NEAR_MS
    ]
    for ms, depth in lexical_shifts(turns, language):
        if all(abs(ms - c) >= BOUNDARY_NEAR_MS for c, _d, _s in candidates):
            candidates.append((ms, depth, SOURCE_LEXICAL))
    # Strongest first, but no part shorter than half an equal share (it would be merged away).
    min_part = (end - start) / (wanted + 1) / 2 if wanted > 0 else 0
    chosen: list[tuple[int, float, str]] = []
    for cand in sorted(candidates, key=lambda c: (-c[1], c[0])):
        if len(chosen) >= wanted:
            break
        edges = [start, *sorted(c[0] for c in chosen), end]
        if all(abs(cand[0] - e) >= min_part for e in edges):
            chosen.append(cand)
    sources = {src for _m, _d, src in chosen}
    cuts = sorted(ms for ms, _d, _s in chosen)
    if not chosen and wanted > 0 and end - start >= (wanted + 1) * BOUNDARY_NEAR_MS:
        # No shift anywhere (a monologue on one subject): equal parts.
        step = (end - start) / (wanted + 1)
        return Segmentation(
            tuple(round(start + step * k) for k in range(1, wanted + 1)), SOURCE_UNIFORM
        )
    # Fewer shifts than wanted: the longest part is halved until the count holds.
    while len(cuts) < wanted:
        edges = [start, *cuts, end]
        a, b = max(zip(edges, edges[1:], strict=False), key=lambda e: e[1] - e[0])
        if b - a < 2 * BOUNDARY_NEAR_MS:
            break
        cuts = sorted([*cuts, (a + b) // 2])
        sources.add(SOURCE_UNIFORM)
    if not cuts:
        return Segmentation((), SOURCE_SINGLE)
    if sources == {SOURCE_UNIFORM}:
        source = SOURCE_UNIFORM
    elif SOURCE_CUES in sources and SOURCE_LEXICAL in sources:
        source = SOURCE_MIXED
    else:
        source = next(iter(sorted(sources - {SOURCE_UNIFORM})))
        if SOURCE_UNIFORM in sources:
            source = f"{source}+{SOURCE_UNIFORM}"
    return Segmentation(tuple(cuts), source)


def blocks_at(facts: Sequence[VerifiedFact], segmentation: Segmentation) -> tuple[list[Block], int]:
    """Facts placed in the parts by their evidence time; a part with fewer
    than ``MIN_SEGMENT_FACTS`` joins its smaller neighbour (counted)."""
    ordered = sorted(facts, key=lambda f: (f.start_ms, f.item_key))
    if not ordered:
        return [], 0
    edges = [-1, *segmentation.boundaries]
    groups: list[list[VerifiedFact]] = [[] for _ in edges]
    for fact in ordered:
        k = max(i for i, edge in enumerate(edges) if fact.start_ms >= edge)
        groups[k].append(fact)
    groups = [g for g in groups if g]
    merged = 0
    while len(groups) > 1:
        small = [i for i, g in enumerate(groups) if len(g) < MIN_SEGMENT_FACTS]
        if not small:
            break
        i = small[0]
        if i == 0:
            j = 1
        elif i == len(groups) - 1:
            j = i - 1
        else:
            j = i - 1 if len(groups[i - 1]) <= len(groups[i + 1]) else i + 1
        a, b = sorted((i, j))
        groups[a : b + 1] = [groups[a] + groups[b]]
        merged += 1
    return [Block(n, tuple(g)) for n, g in enumerate(groups)], merged
