"""The top of the note, and structure when the model gives none (F3
amendment after r03, §2.6 and §2.9).

* :func:`first_paragraph` — what this recording is, composed by code from
  values the engine already verified: the recording type, the subject and
  themes the context pass named (gated against the facts), the speakers.
  It exists even when every model pass fails.
* :func:`composed_sentences` — the third rung of the summary ladder: the
  most specific facts in time order, joined with per-language connectives.
  Still prose a reader can follow; bullets are never the overview.
* :func:`chapters` — when the topics pass fails on a long recording, the
  facts grouped by time, headed by their first timestamp and the name the
  span mentions most.
* :func:`reduce_blocks` — a long recording's facts cut into time-contiguous
  blocks for the two-stage topics pass (A-12).

Pure. Facts and values in, strings and structures out.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Final

from . import support
from .verify import VerifiedFact, _has_date_word

# What the recording is, per language (Q3's recording types).
TYPE_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "meeting": "Meeting",
        "client_call": "Client call",
        "sales_call": "Sales call",
        "interview": "Interview",
        "one_on_one": "One-on-one",
        "podcast_broadcast": "Podcast episode",
        "lecture_webinar": "Talk",
        "voice_memo": "Voice memo",
        "presentation_demo": "Presentation",
    },
    "de": {
        "meeting": "Besprechung",
        "client_call": "Kundengespräch",
        "sales_call": "Verkaufsgespräch",
        "interview": "Interview",
        "one_on_one": "Einzelgespräch",
        "podcast_broadcast": "Podcast-Folge",
        "lecture_webinar": "Vortrag",
        "voice_memo": "Sprachnotiz",
        "presentation_demo": "Präsentation",
    },
    "uk": {
        "meeting": "Зустріч",
        "client_call": "Розмова з клієнтом",
        "sales_call": "Продажний дзвінок",
        "interview": "Інтерв'ю",
        "one_on_one": "Розмова один на один",
        "podcast_broadcast": "Випуск подкасту",
        "lecture_webinar": "Лекція",
        "voice_memo": "Голосова нотатка",
        "presentation_demo": "Презентація",
    },
}
_ABOUT: Final[dict[str, str]] = {"en": "about", "de": "über", "uk": "про"}
# No colon anywhere near the start: "Label: text" is what a transcript turn
# looks like, and the shared page and the client version treat a section
# that reads like turns as a transcript (client_view.looks_like_transcript).
_SPEAKERS: Final[dict[str, str]] = {
    "en": "With {who}.",
    "de": "Es sprechen {who}.",
    "uk": "Говорять {who}.",
}
_AND: Final[dict[str, str]] = {"en": "and", "de": "und", "uk": "і"}
_GUEST: Final[dict[str, str]] = {"en": "as guest", "de": "als Gast", "uk": "гість"}
_THEMES: Final[dict[str, str]] = {
    "en": "Themes are {themes}.",
    "de": "Themen sind {themes}.",
    "uk": "Теми — {themes}.",
}
NARRATOR: Final[dict[str, str]] = {"en": "the narrator", "de": "Erzähler/in", "uk": "оповідач"}
# Connectives for composed prose: a dash, not an adverb that moves the verb
# ("Zunächst gründet Thiel …") and not a colon (see above).
CONNECTIVES: Final[dict[str, tuple[str, str, str]]] = {
    "en": ("First —", "Then —", "Finally —"),
    "de": ("Zunächst —", "Anschließend —", "Schließlich —"),
    "uk": ("Спочатку —", "Потім —", "Зрештою —"),
}
MAX_THEMES: Final = 5
COMPOSED_MIN: Final = 3
COMPOSED_MAX: Final = 6
CHAPTER_MIN_FACTS: Final = 3
CHAPTERS_AFTER_MS: Final = 10 * 60_000
# A window of a long recording can hold ten minutes of talk: a span is at
# most this long, so a chapter or a reduce block is a part of the story.
SPAN_MAX_MS: Final = 3 * 60_000
# A name said across most of the recording is its subject, not what one
# part of it is about: it does not head a chapter.
TITLE_NAME_MAX_SPAN_SHARE: Final = 0.5
REDUCE_MAX_BLOCKS: Final = 8
REDUCE_MIN_BLOCK_FACTS: Final = 4


def _pick(table: Mapping[str, object], language: str) -> object:
    return table.get(language) or table["en"]


def mmss(ms: int) -> str:
    total = max(0, ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def first_paragraph(
    *,
    language: str,
    recording_type: str | None,
    subject: str = "",
    framing: str = "",
    speakers: list[str] | None = None,
    guests: list[str] | None = None,
    themes: list[str] | None = None,
) -> str:
    """ "Podcast-Folge über Palantir. Es sprechen Erzähler/in und als Gast
    Felix Holtermann (Handelsblatt). Es geht um …". A model framing sentence that
    passed the gate replaces the first clause; speakers and themes are
    always code."""
    types = _pick(TYPE_LABELS, language)
    assert isinstance(types, dict)
    kind = types.get(recording_type or "meeting") or types["meeting"]
    if framing.strip():
        first = framing.strip().rstrip(".") + "."
    elif subject.strip():
        first = f"{kind} {_pick(_ABOUT, language)} {subject.strip().rstrip('.')}."
    else:
        first = f"{kind}."
    parts = [first]
    joiner = str(_pick(_AND, language))
    guest_label = str(_pick(_GUEST, language))
    who = [w for w in (speakers or []) if w] + [f"{guest_label} {g}" for g in (guests or []) if g]
    if who:
        listed = ", ".join(who[:-1]) + f" {joiner} {who[-1]}" if len(who) > 1 else who[0]
        template = str(_pick(_SPEAKERS, language))
        parts.append(template.format(who=listed))
    listed_themes = [t.strip().rstrip(".") for t in (themes or []) if t.strip()][:MAX_THEMES]
    if listed_themes:
        joined = (
            ", ".join(listed_themes[:-1]) + f" {joiner} {listed_themes[-1]}"
            if len(listed_themes) > 1
            else listed_themes[0]
        )
        parts.append(str(_pick(_THEMES, language)).format(themes=joined))
    return " ".join(parts)


def _specific(fact: VerifiedFact, language: str, known: frozenset[str]) -> int:
    return support.specificity(fact.text, language, known=known, has_date=_has_date_word(fact.text))


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".;,")
    return (text[:1].upper() + text[1:] + ".") if text else ""


def composed_sentences(
    facts: list[VerifiedFact],
    *,
    language: str,
    known: frozenset[str] = frozenset(),
    key_ids: list[str] | None = None,
) -> list[tuple[str, list[str]]]:
    """Ladder rung 3: 3–6 sentences, each one fact's text, in time order,
    joined by connectives, each citing its fact. The key facts the context
    pass named come first; otherwise the most specific fact of each part of
    the recording."""
    usable = [f for f in facts if not f.evidence_only and f.figure is None and f.person is None]
    if not usable:
        return []
    by_id = {f.item_key: f for f in usable}
    chosen = [by_id[i] for i in (key_ids or []) if i in by_id]
    if len(chosen) < COMPOSED_MIN:
        ordered = sorted(usable, key=lambda f: f.start_ms)
        slices = max(1, min(COMPOSED_MAX, len(ordered)))
        size = max(1, len(ordered) // slices)
        for k in range(0, len(ordered), size):
            part = ordered[k : k + size]
            best = max(part, key=lambda f: _specific(f, language, known))
            if best not in chosen:
                chosen.append(best)
    chosen = sorted(chosen[:COMPOSED_MAX], key=lambda f: f.start_ms)
    first, middle, last = CONNECTIVES.get(language) or CONNECTIVES["en"]
    out: list[tuple[str, list[str]]] = []
    for n, fact in enumerate(chosen):
        sentence = _sentence(fact.text)
        if not sentence:
            continue
        if len(chosen) >= COMPOSED_MIN:
            lead = first if n == 0 else last if n == len(chosen) - 1 else middle
            sentence = f"{lead} {sentence}"
        out.append((sentence, [fact.item_key]))
    return out


def _top_name(
    facts: list[VerifiedFact],
    language: str,
    known: frozenset[str],
    common: frozenset[str] = frozenset(),
) -> str:
    counts: Counter[str] = Counter()
    for fact in facts:
        counts.update(n for n in _name_runs(fact.text, language, known) if n not in common)
    return counts.most_common(1)[0][0] if counts else ""


def _name_runs(text: str, language: str, known: frozenset[str]) -> list[str]:
    """Named things, with adjacent name words as one ("Alex Karp", not
    "Alex" and "Karp")."""
    names = set(support.entities_in(text, language, known))
    runs: list[str] = []
    current: list[str] = []
    for word in re.findall(r"[\w'’-]+", text):
        if word in names:
            current.append(word)
            continue
        if current:
            runs.append(" ".join(current))
        current = []
    if current:
        runs.append(" ".join(current))
    return list(dict.fromkeys(runs))


def _common_names(
    spans: list[list[VerifiedFact]], language: str, known: frozenset[str]
) -> frozenset[str]:
    """Names in more than half of the spans (with three spans or more)."""
    if len(spans) < 3:
        return frozenset()
    seen: Counter[str] = Counter()
    for span in spans:
        seen.update({n for f in span for n in _name_runs(f.text, language, known)})
    return frozenset(n for n, c in seen.items() if c / len(spans) > TITLE_NAME_MAX_SPAN_SHARE)


def _spans(facts: list[VerifiedFact], minimum: int) -> list[list[VerifiedFact]]:
    """Facts by window and by at most :data:`SPAN_MAX_MS` of it, in time;
    a span with fewer than ``minimum`` facts joins the span before it (or
    after, at the start)."""
    by_part: dict[tuple[int, int], list[VerifiedFact]] = {}
    for fact in sorted(facts, key=lambda f: f.start_ms):
        by_part.setdefault((fact.window_index, fact.start_ms // SPAN_MAX_MS), []).append(fact)
    spans: list[list[VerifiedFact]] = []
    for part in sorted(by_part):
        group = by_part[part]
        if spans and len(spans[-1]) < minimum:
            spans[-1].extend(group)
        else:
            spans.append(list(group))
    if len(spans) > 1 and len(spans[-1]) < minimum:
        tail = spans.pop()
        spans[-1].extend(tail)
    return spans


def chapters(
    facts: list[VerifiedFact], *, language: str, known: frozenset[str] = frozenset()
) -> list[tuple[str, list[tuple[str, list[str], list[tuple[str, list[str]]]]], list[str]]]:
    """§2.6: topics-shaped chapters — ``[(title, bullets, fact ids)]``,
    headed "07:40 — Alex Karp". Within a chapter a fact that names, counts
    or dates nothing is written only when nothing beside it does."""
    usable = [f for f in facts if not f.evidence_only and f.figure is None and f.person is None]
    out: list[tuple[str, list[tuple[str, list[str], list[tuple[str, list[str]]]]], list[str]]] = []
    spans = _spans(usable, CHAPTER_MIN_FACTS)
    common = _common_names(spans, language, known)
    for span in spans:
        if len(span) < CHAPTER_MIN_FACTS:
            continue
        specific = [f for f in span if _specific(f, language, known) > 0]
        shown = specific if specific else span
        name = _top_name(span, language, known, common)
        title = f"{mmss(span[0].start_ms)} — {name}" if name else mmss(span[0].start_ms)
        out.append(
            (
                title,
                [(f.text, [f.item_key], []) for f in shown],
                [f.item_key for f in span],
            )
        )
    return out


def reduce_blocks(facts: list[VerifiedFact]) -> list[list[VerifiedFact]]:
    """A-12: time-contiguous blocks of ≥ 4 facts, at most 8, for the
    two-stage topics pass."""
    blocks = _spans(facts, REDUCE_MIN_BLOCK_FACTS)
    while len(blocks) > REDUCE_MAX_BLOCKS:
        # Merge the smallest adjacent pair.
        k = min(range(len(blocks) - 1), key=lambda i: len(blocks[i]) + len(blocks[i + 1]))
        blocks[k : k + 2] = [blocks[k] + blocks[k + 1]]
    return blocks
