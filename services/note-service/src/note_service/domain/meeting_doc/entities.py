"""Names spelled the way the workspace knows them, in the LINE only (the quote
keeps what was heard; the fact records the ``Correction``). Tiers: (a) glossary
and known people by similarity >= ``THRESHOLD`` with no close second; (b) the
model, once per generation, never onto a person already present; (c) too far:
marked ``(?)``. Pure; names are person data, nothing here logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from ..glossary import Term
from .support import CAPITALISED

THRESHOLD: Final = 0.8
MODEL_THRESHOLD: Final = 0.6
# A second candidate this close to the best one makes the choice a guess.
AMBIGUITY_MARGIN: Final = 0.05
MIN_TOKEN_CHARS: Final = 4
UNSURE_MARK: Final = " (?)"

SOURCE_GLOSSARY: Final = "glossary"
SOURCE_CANDIDATE: Final = "candidate"
SOURCE_MODEL: Final = "model"
# A name the recording itself says three times or more.
SOURCE_RECORDING: Final = "recording"


@dataclass(frozen=True, slots=True)
class Correction:
    surface: str
    canonical: str
    source: str
    """F2-02: ``person`` only with entity evidence (a known person, a person term in the
    glossary); anything else is ``term`` — never offered to be saved as a name."""
    entity: str = "term"


# F2-02 — what changed between what was heard and the proposed spelling. Only a spelling
# change is an ASR correction; an article, an ending or capitals are grammar and format.
SPELLING: Final = "spelling"
ARTICLE: Final = "article"
INFLECTION: Final = "inflection"
CAPITALISATION: Final = "capitalisation"
_ARTICLES: Final = frozenset(
    {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer",
     "eines", "the", "a", "an"}
)  # fmt: skip
# Grammatical endings ("Menschen", "Hauses", "Trumps", "України"/"Україні"). Any other
# difference at the end is spelling: "Sonnenfeld" → "Sonnenfeldt" is a misheard name.
_ENDINGS: Final = frozenset(
    {"e", "en", "er", "es", "em", "ern", "n", "s", "ns", "nen", "'s", "’s",
     "а", "я", "у", "ю", "і", "и", "ї", "ові", "еві", "ом", "ем", "ою", "ею", "ам", "ям",
     "ами", "ями", "ах", "ях", "ів", "їв", "ей"}
)  # fmt: skip


def change_kind(surface: str, canonical: str) -> str:
    """``spelling``, ``article``, ``inflection`` or ``capitalisation``: "Das
    Repräsentantenhaus" → "Repräsentantenhaus" is an article, "Menschen" → "Mensch" an
    ending, "trump" → "Trump" capitals; "Reinbolt" → "Reinbold" is spelling."""
    a, b = " ".join(surface.split()), " ".join(canonical.split())
    if a == b or a.casefold() == b.casefold():
        return CAPITALISATION
    words_a, words_b = a.split(), b.split()
    while words_a and words_a[0].casefold() in _ARTICLES:
        words_a = words_a[1:]
    while words_b and words_b[0].casefold() in _ARTICLES:
        words_b = words_b[1:]
    bare_a, bare_b = " ".join(words_a).casefold(), " ".join(words_b).casefold()
    if bare_a == bare_b:
        return ARTICLE
    stem = 0
    while stem < min(len(bare_a), len(bare_b)) and bare_a[stem] == bare_b[stem]:
        stem += 1
    tail_a, tail_b = bare_a[stem:], bare_b[stem:]
    if stem >= MIN_TOKEN_CHARS and all(t == "" or t in _ENDINGS for t in (tail_a, tail_b)):
        return INFLECTION
    return SPELLING


def is_correction(surface: str, canonical: str) -> bool:
    """A misheard spelling put right — never grammar or formatting (F2-02)."""
    return change_kind(surface, canonical) == SPELLING


def _norm(text: str) -> str:
    from .verify import normalise_quote  # verify imports this module

    return normalise_quote(text)


def similarity(a: str, b: str) -> float:
    """``difflib.SequenceMatcher`` ratio on the normalised forms — pinned:
    "Reinbolt" / "Reinbold" = 0.875, "Uschmanow" / "Usmanow" = 0.875."""
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def candidates_in(text: str) -> list[str]:
    """Capitalised tokens of ``text``, and each two-token capitalised span
    ("Fabian Reinbolt"), longest first, once each. Sentence-initial words
    are included: a name opens sentences too; a span never opens with an
    article ("Das Repräsentantenhaus" is not a name)."""
    tokens = [(m.group(1), m.start(), m.end()) for m in CAPITALISED.finditer(text)]
    out: list[str] = []
    for (a, _sa, ea), (b, sb, _eb) in zip(tokens, tokens[1:], strict=False):
        if text[ea:sb] == " " and a.casefold() not in _ARTICLES:
            out.append(f"{a} {b}")
    out.extend(token for token, _s, _e in tokens)
    return list(dict.fromkeys(out))


def _people(glossary: tuple[Term, ...], known_people: frozenset[str]) -> frozenset[str]:
    """Spellings with entity evidence of a person, whole and word by word."""
    names = {t.term for t in glossary if t.kind == "person"} | set(known_people)
    return frozenset(
        {n.casefold() for n in names} | {w.casefold() for n in names for w in n.split()}
    )


def _pool(
    glossary: tuple[Term, ...],
    known_people: frozenset[str],
    recording_names: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """``{spelling: source}`` — every name this recording may mean, as a
    whole and, for people, surname by surname."""
    pool: dict[str, str] = {}
    for term in glossary:
        pool.setdefault(term.term, SOURCE_GLOSSARY)
    for person in known_people:
        pool.setdefault(person, SOURCE_CANDIDATE)
    for name in recording_names:
        pool.setdefault(name, SOURCE_RECORDING)
    for name, source in list(pool.items()):
        parts = name.split()
        if len(parts) > 1:
            for part in parts:
                if len(part) >= MIN_TOKEN_CHARS:
                    pool.setdefault(part, source)
    return pool


def resolve(
    surfaces: list[str],
    *,
    glossary: tuple[Term, ...] = (),
    known_people: frozenset[str] = frozenset(),
    threshold: float = THRESHOLD,
    recording_names: frozenset[str] = frozenset(),
) -> tuple[dict[str, Correction], set[str]]:
    """``(corrections, marked)`` for these surfaces.

    A ``heard_as`` spelling is corrected to its term outright. Otherwise
    the closest known spelling at ``threshold`` or above, unless another is
    within ``AMBIGUITY_MARGIN`` of it. ``marked`` are full names (two
    tokens) that came near a known name without being close enough — the
    line says "(?)" rather than guess. A single word near a name is not
    marked: German capitalises its nouns, and "Sommer" is not a misheard
    "Sommerfeld".
    """
    # A heard_as that is only an article or an ending of its term (saved before F2-02)
    # teaches nothing: it is never applied.
    heard = {h.casefold(): t.term for t in glossary for h in t.heard_as if is_correction(h, t.term)}
    pool = _pool(glossary, known_people, recording_names)
    people = _people(glossary, known_people)

    def entity_of(spelling: str) -> str:
        return "person" if spelling.casefold() in people else "term"

    exact = {spelling.casefold() for spelling in pool}
    out: dict[str, Correction] = {}
    marked: set[str] = set()
    for surface in surfaces:
        folded = surface.casefold()
        if folded in heard:
            if heard[folded] != surface:
                out[surface] = Correction(
                    surface, heard[folded], SOURCE_GLOSSARY, entity_of(heard[folded])
                )
            continue
        if folded in exact or len(surface) < MIN_TOKEN_CHARS:
            continue
        scored = sorted(
            ((similarity(surface, spelling), spelling) for spelling in pool), reverse=True
        )
        if not scored:
            continue
        best, spelling = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if pool[spelling] == SOURCE_RECORDING and _inflected(surface, spelling):
            continue  # "Mensch" / "Menschen": grammar, not a mishearing
        if (
            pool[spelling] == SOURCE_RECORDING
            and best < threshold
            and _one_substitution(surface, spelling)
            and best - runner_up > AMBIGUITY_MARGIN
        ):
            out[surface] = Correction(surface, spelling, SOURCE_RECORDING, entity_of(spelling))
            continue
        if not is_correction(surface, spelling):
            continue  # "Die Behauptung" / "Behauptung": grammar, never a correction
        if best >= threshold and best - runner_up > AMBIGUITY_MARGIN:
            out[surface] = Correction(surface, spelling, pool[spelling], entity_of(spelling))
        elif MODEL_THRESHOLD <= best < threshold and _aligned(surface, spelling):
            marked.add(surface)
    # A span corrected — or doubted — as a whole wins over its parts: half a
    # corrected name is a different name.
    for span in [s for s in out if " " in s] + list(marked):
        for part in span.split():
            out.pop(part, None)
    return out, marked


def _inflected(a: str, b: str) -> bool:
    x, y = a.casefold(), b.casefold()
    return x.startswith(y) or y.startswith(x)


def _one_substitution(a: str, b: str) -> bool:
    """Same length (≥ 4), one letter different: "Carp" / "Karp"."""
    x, y = a.casefold(), b.casefold()
    return (
        len(x) == len(y) >= MIN_TOKEN_CHARS and sum(c != d for c, d in zip(x, y, strict=True)) == 1
    )


def _aligned(surface: str, name: str) -> bool:
    """A misheard full name, word for word: as many words as the name, each
    one near its counterpart. "Der Sommer" is not "Karla Sommerfeld"."""
    mine, theirs = surface.split(), name.split()
    return len(mine) == len(theirs) > 1 and all(
        similarity(a, b) >= 0.5 for a, b in zip(mine, theirs, strict=True)
    )


def apply(text: str, corrections: dict[str, Correction], marked: set[str] = frozenset()) -> str:
    """``text`` with each corrected surface spelled canonically and each
    marked one followed by "(?)". Whole words only; longest first."""
    for surface in sorted(corrections, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(surface)}(?!\w)", corrections[surface].canonical, text)
    for surface in sorted(marked, key=len, reverse=True):
        text = re.sub(
            rf"(?<!\w){re.escape(surface)}(?!\w)(?!\s\(\?\))", surface + UNSURE_MARK, text
        )
    return text


def correct(
    text: str | None,
    *,
    glossary: tuple[Term, ...] = (),
    known_people: frozenset[str] = frozenset(),
    recording_names: frozenset[str] = frozenset(),
) -> tuple[str | None, list[Correction], set[str]]:
    """One string through tier (a): ``(corrected, applied, marked)``."""
    if not text:
        return text, [], set()
    table, marked = resolve(
        candidates_in(text),
        glossary=glossary,
        known_people=known_people,
        recording_names=recording_names,
    )
    applied = [c for s, c in table.items() if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", text)]
    return apply(text, table, marked), applied, marked
