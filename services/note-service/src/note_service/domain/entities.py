"""What a name correction is (F2-02): only a spelling change is an ASR correction; an
article, an ending or capitals are grammar and format. Used by the glossary and the
corrections routes. Pure.
"""

from __future__ import annotations

from typing import Final

MIN_TOKEN_CHARS: Final = 4

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
