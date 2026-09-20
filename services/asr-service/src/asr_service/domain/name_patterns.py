"""Self-introduction patterns per transcript language (Sprint 32 B-1).

Rule-based and precision-first: a phrase like "this is Anna" only
PROPOSES a name; `name_suggestions` requires it to match a calendar
candidate before anything is shown. So these patterns may be generous —
"ich bin Arzt" extracts "Arzt" (German capitalises nouns) and the
candidate list throws it away.

Safety: every quantifier is bounded (a name is at most 3 tokens of at
most 40 characters), so a 10 kB adversarial turn cannot backtrack
catastrophically. Names are checked for capitalisation in code, not in
the regex, so the prefixes can be case-insensitive and Unicode-aware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 1–3 word tokens; letters, apostrophes and hyphens inside a token.
_TOKEN = r"[^\W\d_][^\W\d_'’\-]{0,39}(?:[\-'’][^\W\d_]{1,39}){0,2}"
_NAME = rf"(?P<name>{_TOKEN}(?:[ \t]+{_TOKEN}){{0,2}})"

_PREFIXES: dict[str, tuple[str, ...]] = {
    "en": (r"\b(?:this is|i am|i'm|i’m|my name is|it's|it’s)[ \t]+",),
    "de": (r"\b(?:hier ist|ich bin|mein name ist|ich heiße|ich heisse)[ \t]+",),
    # Not after an apostrophe either: "ім'я Олена" ("the name is Olena", said
    # ABOUT someone) must not read as "я Олена".
    "uk": (r"(?<![\w'’ʼ])(?:це|мене звати|я)[ \t]+",),
}
# "Anna here." is an introduction only as a clause of its own: it must
# START a clause (text start or after . ! ? , ; :) and END one (. ! , ; : —
# or end of text). "Is Anna here?", "wait, Anna speaking next" and
# "ob Anna hier ist" mention someone else and are rejected.
_CLAUSE_START = r"(?:^|(?<=[.!?,;:—–]))[ \t]*"
_CLAUSE_END = r"(?=[ \t]*(?:[.!,;:—–]|$))"
_SUFFIXES: dict[str, tuple[str, ...]] = {
    "en": (r"[ \t]+(?:here|speaking)\b" + _CLAUSE_END,),
    "de": (r"[ \t]+hier\b" + _CLAUSE_END,),
    "uk": (r"[ \t]+на[ \t]+зв['’ʼ]язку(?!\w)" + _CLAUSE_END,),
}

# Capitalised words that are not names (sentence starts, weekdays, fillers).
STOP_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {
            "here",
            "back",
            "sorry",
            "fine",
            "good",
            "great",
            "ready",
            "done",
            "not",
            "just",
            "also",
            "really",
            "sure",
            "okay",
            "ok",
            "yes",
            "no",
            "the",
            "a",
            "an",
            "it",
            "i",
            "we",
            "you",
            "he",
            "she",
            "they",
            "that",
            "this",
            "what",
            "so",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "today",
            "tomorrow",
            "everyone",
            "everybody",
            "all",
            "going",
            "happy",
            "glad",
        }
    ),
    "de": frozenset(
        {
            "hier",
            "müde",
            "zurück",
            "dabei",
            "fertig",
            "da",
            "auch",
            "ja",
            "nein",
            "so",
            "gerade",
            "noch",
            "schon",
            "wieder",
            "froh",
            "bereit",
            "der",
            "die",
            "das",
            "ein",
            "eine",
            "ich",
            "wir",
            "sie",
            "er",
            "es",
            "montag",
            "dienstag",
            "mittwoch",
            "donnerstag",
            "freitag",
            "samstag",
            "sonntag",
            "heute",
            "morgen",
            "alle",
        }
    ),
    "uk": frozenset(
        {
            "добре",
            "тут",
            "готовий",
            "готова",
            "так",
            "ні",
            "вже",
            "теж",
            "також",
            "знову",
            "радий",
            "рада",
            "це",
            "я",
            "ми",
            "ви",
            "він",
            "вона",
            "вони",
            "понеділок",
            "вівторок",
            "середа",
            "четвер",
            "пʼятниця",
            "п'ятниця",
            "субота",
            "неділя",
            "сьогодні",
            "завтра",
            "всі",
        }
    ),
}


@dataclass(frozen=True)
class Introduction:
    name: str  # as the transcript spells it
    start: int  # character offsets of the match in the scanned text
    end: int


def _compile(language: str) -> list[tuple[re.Pattern[str], bool]]:
    """(pattern, name_is_before_the_phrase)."""
    flags = re.IGNORECASE | re.UNICODE
    return [(re.compile(p + _NAME, flags), False) for p in _PREFIXES.get(language, ())] + [
        (re.compile(_CLAUSE_START + _NAME + s, flags), True) for s in _SUFFIXES.get(language, ())
    ]


_PATTERNS: dict[str, list[tuple[re.Pattern[str], bool]]] = {
    lang: _compile(lang) for lang in _PREFIXES
}


def supported(language: str) -> bool:
    return language in _PATTERNS


def find_introductions(text: str, language: str) -> list[Introduction]:
    """Self-introductions in ``text``: the capitalised name tokens right
    after an intro phrase (or right before "here"/"speaking")."""
    stop = STOP_WORDS.get(language, frozenset())
    found: list[Introduction] = []
    for pattern, before in _PATTERNS.get(language, []):
        for match in pattern.finditer(text):
            raw = match.group("name")
            # "Good morning, Anna here": the name is the run just BEFORE the
            # phrase, so read those tokens from the end.
            name = _capitalised_suffix(raw, stop) if before else _capitalised_prefix(raw, stop)
            if name:
                found.append(Introduction(name=name, start=match.start(), end=match.end()))
    return found


def _capitalised_prefix(raw: str, stop: frozenset[str]) -> str | None:
    """The leading run of capitalised, non-stop-word tokens (1–3)."""
    tokens: list[str] = []
    for token in raw.split():
        token = token.strip("'’-")
        if not token or not token[0].isupper() or token.casefold() in stop:
            break
        tokens.append(token)
    return " ".join(tokens) if tokens else None


def _capitalised_suffix(raw: str, stop: frozenset[str]) -> str | None:
    """The trailing run of capitalised, non-stop-word tokens (1–3)."""
    tokens: list[str] = []
    for token in reversed(raw.split()):
        token = token.strip("'’-,.")
        if not token or not token[0].isupper() or token.casefold() in stop:
            break
        tokens.insert(0, token)
    return " ".join(tokens) if tokens else None
