"""The workspace glossary: names this workspace spells a particular way.

A person fixes "Jon Meyer" to "John Mayer" once. Without this table they
fix it again next week, and the week after — the recording says the same
thing every time and the transcriber hears it the same way. So a
correction can be remembered, **opt-in, one term at a time**, and then
used three ways:

* as the capture form's ``vocabulary_hint`` (:func:`hint_text`), so the
  transcriber has the spelling before it guesses;
* in the generation prompt, so the model writes it the way the workspace
  writes it (blocked on the engine — Sprint 33);
* to canonicalise an owner label that came back as a known mishearing
  (``meeting_doc.entities``, Summary Engine v2 Q4).

Quotes are never touched by any of it. A quote is what was said.

Everything here is pure; the table lives in ``glossary_repository``.
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

# Characters a term may not contain. Written as code-point RANGES rather
# than as a literal character class on purpose: half of these are
# invisible, and a source file that contains a bidi override in order to
# reject bidi overrides is a file nobody can review.
#
#   C0 / C1 controls, DEL      a term is one line of plain text
#   U+200B..U+200F             zero-width space, joiners, LRM/RLM
#   U+2028..U+202E             line/paragraph separators, bidi embedding
#   U+2066..U+2069             bidi isolates
#
# The last three groups are what makes one string RENDER as another, and
# a glossary term is rendered in three clients and put inside a prompt.
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
    """A storable term, or raise.

    Whitespace collapsed, NFKC-normalised (so a look-alike Cyrillic "А"
    and a Latin "A" do not become two entries that shadow each other),
    control characters refused rather than stripped — a term that needed
    stripping is not the term the person typed.
    """
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
    """The capture form's vocabulary hint: the terms, comma-separated,
    truncated at a term boundary so the transcriber never gets half a name.

    Only the canonical spellings go — the point is to teach the
    transcriber the right one, and feeding it the wrong spellings too
    would do the opposite.
    """
    out: list[str] = []
    length = 0
    for entry in terms:
        addition = len(entry.term) + (2 if out else 0)
        if length + addition > limit:
            break
        out.append(entry.term)
        length += addition
    return ", ".join(out)


def terms_in(text: str, terms: list[Term], *, limit: int = MAX_PROMPT_TERMS) -> list[Term]:
    """The terms that actually occur in this text, canonical spelling or
    mishearing, case-insensitively.

    The generation prompt gets these and not the whole glossary: 500 names
    in a prompt is noise that costs accuracy on the 3 that matter.
    """
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
    """The block the generation prompt carries.

    It is **data, not instruction**: the caller puts it inside the prompt's
    data delimiters, and the wording here never tells the model to do
    anything a term could redirect.
    """
    if not terms:
        return ""
    lines = [
        f"- {entry.term}" + (f" (heard as: {', '.join(entry.heard_as)})" if entry.heard_as else "")
        for entry in terms
    ]
    return "Known names and terms (spell exactly):\n" + "\n".join(lines)
