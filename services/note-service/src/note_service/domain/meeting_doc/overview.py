"""The top of the note, and structure when the model gives none: paragraph 1
composed by code from verified values, the summary ladder's third rung, and
time-grouped chapters when the topics pass fails. Pure.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Collection, Mapping
from typing import Final

from . import support
from .verify import MEANING_UNVERIFIED, PARAPHRASE_UNSUPPORTED, VerifiedFact, _has_date_word

# What the recording is, per language.
TYPE_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "meeting": "Meeting",
        "client_call": "Client call",
        "sales_call": "Sales call",
        "interview": "Interview",
        "one_on_one": "One-on-one",
        "podcast_broadcast": "Broadcast",
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
        "podcast_broadcast": "Sendung",
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
        "podcast_broadcast": "Передача",
        "lecture_webinar": "Лекція",
        "voice_memo": "Голосова нотатка",
        "presentation_demo": "Презентація",
    },
}
_ABOUT: Final[dict[str, str]] = {"en": "about", "de": "über", "uk": "про"}
# No colon near the start: "Label: text" reads as a transcript turn (client_view.looks_like_transcript).
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
MAX_THEMES: Final = 5
COMPOSED_MIN: Final = 3
COMPOSED_MAX: Final = 6
CHAPTER_MIN_FACTS: Final = 3
CHAPTERS_AFTER_MS: Final = 10 * 60_000
# A span is at most this long, so a chapter is a part of the story.
SPAN_MAX_MS: Final = 3 * 60_000
# A name said across most of the recording is its subject and heads no chapter.
TITLE_NAME_MAX_SPAN_SHARE: Final = 0.5


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
    others: list[str] | None = None,
    named: bool = True,
) -> str:
    """ "Sendung über Palantir. Es sprechen … Themen sind …". A gated model framing
    replaces the first clause; speakers and themes are always code. ``named=False``
    (nobody on the recording has a name): no sentence about who speaks — a role
    word alone ("Es sprechen Erzähler/in.") tells the reader nothing."""
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
    # The one writer of who speaks (compose.speakers_of).
    who = (
        [w for w in (speakers or []) if w]
        + [f"{guest_label} {g}" for g in (guests or []) if g]
        + [w for w in (others or []) if w]
    )
    if who and named:
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


_YEAR: Final = re.compile(
    r"(?:\s*\b(?:im jahre?|in the year|in|im|seit|ab|von|bis|für|aus|nach|vor|of|since|from|"
    r"until|у|в|з|до|для|після)\s+)?\b((?:19|20)\d\d)\b",
    re.IGNORECASE,
)


def strip_foreign_year(text: str, recording_year: int | None) -> tuple[str, int]:
    """A subject or framing without a year that is not the recording's ("Analyse der
    US-Politik 2024" → "Analyse der US-Politik"), with its preposition; the count of
    years removed. With no recording year nothing is compared, nothing removed."""
    if recording_year is None or not text:
        return text, 0
    removed = 0

    def keep_or_drop(match: re.Match[str]) -> str:
        nonlocal removed
        if int(match.group(1)) == recording_year:
            return match.group(0)
        removed += 1
        return ""

    out = _YEAR.sub(keep_or_drop, text)
    if not removed:
        return text, 0
    out = re.sub(r"\s+([.,;:!?)])", r"\1", " ".join(out.split()))
    return out.strip(), removed


def composed_sentences(
    facts: list[VerifiedFact],
    *,
    language: str,
    known: frozenset[str] = frozenset(),
    key_ids: list[str] | None = None,
) -> list[tuple[str, list[str]]]:
    """Ladder rung 3: 3–6 facts' texts in time order as plain sentences, each citing
    its fact. No connectives (unrelated facts are no sequence); a hedged fact carries
    its certainty once, as a clause (:func:`support.certainty_clause`)."""
    usable = [
        f
        for f in facts
        if not f.evidence_only
        and f.figure is None
        and f.person is None
        and PARAPHRASE_UNSUPPORTED not in f.flags
        and MEANING_UNVERIFIED not in f.flags
    ]
    # A call to action ("write in the comments") is no overview while anything else is.
    substantive = [f for f in usable if f.kind != "next_step"]
    usable = substantive or usable
    if not usable:
        return []
    by_id = {f.item_key: f for f in usable}
    chosen = [by_id[i] for i in (key_ids or []) if i in by_id]
    if len(chosen) < COMPOSED_MIN:
        ordered = sorted(usable, key=lambda f: f.start_ms)
        slices = max(1, min(COMPOSED_MAX, len(ordered)))
        size = max(1, len(ordered) // slices)
        # One specific fact per part; a part with none is passed over unless that leaves under three.
        spare: list[VerifiedFact] = []
        for k in range(0, len(ordered), size):
            part = ordered[k : k + size]
            best = max(part, key=lambda f: _specific(f, language, known))
            if best in chosen:
                continue
            (chosen if _specific(best, language, known) > 0 else spare).append(best)
        while len(chosen) < COMPOSED_MIN and spare:
            chosen.append(spare.pop(0))
    chosen = sorted(chosen[:COMPOSED_MAX], key=lambda f: f.start_ms)
    out: list[tuple[str, list[str]]] = []
    for fact in chosen:
        sentence = _sentence(
            support.certainty_clause(fact.certainty, fact.text, language, actor=fact.attributed_to)
        )
        if sentence:
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


def chapter_heading(
    facts: list[VerifiedFact],
    language: str,
    known: frozenset[str],
    *,
    common: frozenset[str] = frozenset(),
    taken: Collection[str] = (),
    max_words: int = support.HEADING_WORDS_MAX,
) -> str:
    """What a span of facts is about, with no timestamp and never a bare name: the
    first clause of its most specific fact (:func:`support.noun_phrase`), the next
    fact's when that heading is taken, the most named thing only when no fact has
    three words. ``max_words``: a workspace's shorter heading dial."""
    ranked = sorted(facts, key=lambda f: (-_specific(f, language, known), f.start_ms))
    used = {t.casefold() for t in taken}
    for fact in ranked:
        heading = support.noun_phrase(fact.text, language, max_words=max_words)
        if heading and heading.casefold() not in used:
            return heading
    name = _top_name(facts, language, known, common)
    if not name:
        runs = Counter(run for f in facts for run in support.capital_runs(f.text))
        name = runs.most_common(1)[0][0] if runs else ""
    return name


def chapters(
    facts: list[VerifiedFact], *, language: str, known: frozenset[str] = frozenset()
) -> list[tuple[str, list[tuple[str, list[str], list[tuple[str, list[str]]]]], list[str]]]:
    """Topics-shaped chapters ``[(title, bullets, fact ids)]``, each headed by what
    its span says (:func:`chapter_heading`), never by a timestamp."""
    usable = [f for f in facts if not f.evidence_only and f.figure is None and f.person is None]
    out: list[tuple[str, list[tuple[str, list[str], list[tuple[str, list[str]]]]], list[str]]] = []
    spans = _spans(usable, CHAPTER_MIN_FACTS)
    common = _common_names(spans, language, known)
    taken: list[str] = []
    for span in spans:
        if len(span) < CHAPTER_MIN_FACTS:
            continue
        specific = [f for f in span if _specific(f, language, known) > 0]
        shown = specific if specific else span
        title = chapter_heading(span, language, known, common=common, taken=taken)
        if not title:
            title = mmss(span[0].start_ms)
        taken.append(title)
        out.append(
            (
                title,
                [(f.text, [f.item_key], []) for f in shown],
                [f.item_key for f in span],
            )
        )
    return out
