"""The workspace glossary: names this workspace spells a particular way, opt-in
one term at a time; used as the capture vocabulary hint, in the generation
prompt and to canonicalise owner labels. Quotes are never touched. Pure.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

MIN_TERM: Final = 2
MAX_TERM: Final = 80
MAX_HEARD_AS: Final = 8
# A workspace vocabulary past this is not a vocabulary.
MAX_TERMS: Final = 500
# `POST /asr/jobs` takes at most this much vocabulary hint.
MAX_HINT_CHARS: Final = 2000
# How many terms the generation prompt may carry (the window-relevant ones).
MAX_PROMPT_TERMS: Final = 60

KINDS: Final = ("person", "company", "product", "term")

# A term whose tokens are ALL role words or ordinals is a voice label ("Moderator II"),
# not vocabulary. Mirrored in the native apps and the web; every copy is asserted
# against tests/fixtures/glossary/role_words.json.
ROLE_WORDS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset(
        {
            "speaker",
            "moderator",
            "host",
            "narrator",
            "guest",
            "interviewer",
            "interviewee",
            "presenter",
            "caller",
            "background",
            "unknown",
            "voice",
            "participant",
            "translator",
            "announcer",
        }
    ),
    "de": frozenset(
        {
            "sprecher",
            "sprecherin",
            "moderator",
            "moderatorin",
            "gast",
            "gastgeber",
            "erzähler",
            "erzählerin",
            "hintergrund",
            "unbekannt",
            "stimme",
            "teilnehmer",
            "teilnehmerin",
            "übersetzer",
        }
    ),
    "uk": frozenset(
        {
            "спікер",
            "ведучий",
            "ведуча",
            "гість",
            "гостя",
            "оповідач",
            "фон",
            "невідомий",
            "голос",
            "учасник",
            "учасниця",
            "перекладач",
        }
    ),
}
ROLE_WORDS_ALL: Final[frozenset[str]] = frozenset().union(*ROLE_WORDS.values())
ORDINALS: Final[frozenset[str]] = frozenset(
    {
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "1",
        "2",
        "3",
        "4",
        "5",
        "one",
        "two",
        "three",
        "eins",
        "zwei",
        "drei",
        "один",
        "два",
        "три",
        "first",
        "second",
        "erste",
        "zweite",
        "перший",
        "другий",
    }
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def is_vocabulary(term: str, kind: str) -> bool:
    """Whether a term belongs in the transcriber's vocabulary: not when every token
    is a role word or ordinal, nor a person with no capital letter."""
    tokens = [tok.casefold() for tok in _WORD.findall(term)]
    if not tokens:
        return False
    if all(tok in ROLE_WORDS_ALL or tok in ORDINALS for tok in tokens):
        return False
    # A person is capitalised somewhere; "moderatorin" is not a person.
    return kind != "person" or any(part[:1].isupper() for part in term.split())


# What the hint sends first: the kinds the transcriber mishears most.
_HINT_ORDER: Final = {"person": 0, "company": 1, "product": 2, "term": 3}

# Forbidden code points as RANGES (a literal bidi override in source is unreviewable):
# C0/C1 controls and DEL, U+200B..200F (zero-width, LRM/RLM), U+2028..202E
# (separators, bidi embedding), U+2066..2069 (bidi isolates).
_FORBIDDEN_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0x0000, 0x001F),
    (0x007F, 0x009F),
    (0x200B, 0x200F),
    (0x2028, 0x202E),
    (0x2066, 0x2069),
)
_CONTROL = re.compile(
    "[" + "".join(f"\\u{lo:04x}-\\u{hi:04x}" for lo, hi in _FORBIDDEN_RANGES) + "]"
)


class GlossaryError(ValueError):
    """A term that cannot be stored, with the code the route returns."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def clean_term(raw: str) -> str:
    """A storable term, or raise: whitespace collapsed, NFKC-normalised (look-alike
    letters), control characters refused rather than stripped."""
    if _CONTROL.search(raw):
        raise GlossaryError("term_invalid", "a term cannot contain control characters")
    term = " ".join(unicodedata.normalize("NFKC", raw).split())
    if not (MIN_TERM <= len(term) <= MAX_TERM):
        raise GlossaryError(
            "term_invalid", f"a term is between {MIN_TERM} and {MAX_TERM} characters"
        )
    return term


def clean_heard_as(raw: list[str], *, term: str) -> list[str]:
    """The misspellings worth keeping: cleaned, de-duplicated, never equal
    to the term itself, at most eight."""
    out: list[str] = []
    seen = {term.casefold()}
    for value in raw:
        try:
            candidate = clean_term(value)
        except GlossaryError:
            continue  # one bad variant does not cost the term
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) == MAX_HEARD_AS:
            break
    return out


@dataclass(frozen=True, slots=True)
class Term:
    term: str
    kind: str
    heard_as: tuple[str, ...]


def hint_text(terms: list[Term], *, limit: int = MAX_HINT_CHARS) -> str:
    """The capture form's vocabulary hint: canonical spellings only, comma-separated,
    truncated at a term boundary."""
    out: list[str] = []
    length = 0
    for entry in hint_terms(terms):
        addition = len(entry.term) + (2 if out else 0)
        if length + addition > limit:
            break
        out.append(entry.term)
        length += addition
    return ", ".join(out)


def hint_terms(terms: list[Term]) -> list[Term]:
    """The terms that go to the transcriber: only vocabulary, people and companies first, stable within a kind."""
    kept = [entry for entry in terms if is_vocabulary(entry.term, entry.kind)]
    return sorted(kept, key=lambda entry: _HINT_ORDER.get(entry.kind, 9))


def terms_in(text: str, terms: list[Term], *, limit: int = MAX_PROMPT_TERMS) -> list[Term]:
    """The terms that occur in this text (canonical or mishearing, case-insensitive);
    the prompt gets these, not the whole glossary."""
    haystack = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    out: list[Term] = []
    for entry in terms:
        needles = (entry.term, *entry.heard_as)
        if any(needle.casefold() in haystack for needle in needles):
            out.append(entry)
            if len(out) == limit:
                break
    return out


def prompt_block(terms: list[Term]) -> str:
    """The block the generation prompt carries: data, not instruction (inside the data delimiters)."""
    if not terms:
        return ""
    lines = [
        f"- {entry.term}" + (f" (heard as: {', '.join(entry.heard_as)})" if entry.heard_as else "")
        for entry in terms
    ]
    return "Known names and terms (spell exactly):\n" + "\n".join(lines)
