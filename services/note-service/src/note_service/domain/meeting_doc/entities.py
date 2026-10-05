"""Names spelled the way the workspace knows them (Summary Engine v2, Q4).

The transcriber hears "Friedrich Schmerz" and "Schlesing"; the workspace
knows Friedrich Merz from the calendar and Schwesig from its glossary.
This module turns what was heard into what is meant — in the LINE only.
The quote keeps what the transcriber heard, the fact records the
correction (``Correction``), and the reader can always see both.

Knowledge comes in tiers, each bounded:

* **(a)** the workspace glossary (``heard_as`` spellings, exact), and the
  people this recording is known to involve — speakers, calendar
  attendees, the ASR's name candidates, glossary persons — by similarity
  ≥ ``THRESHOLD``, and only when no second name is nearly as close
  (ambiguity is not a correction).
* **(b)** the model's own knowledge, one bounded call per generation
  (:mod:`pipeline`), accepted at a lower similarity and never onto a
  person already in the recording.
* **(c)** a proposal too far from what was heard is not applied; the
  surface stays and is marked ``(?)``.

Pure. Names are person data: nothing here logs.
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
# F3 amendment §2.8 — a name the recording itself says three times or more.
SOURCE_RECORDING: Final = "recording"


@dataclass(frozen=True, slots=True)
class Correction:
    surface: str
    canonical: str
    source: str


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
    are included: a name opens sentences too."""
    tokens = [(m.group(1), m.start(), m.end()) for m in CAPITALISED.finditer(text)]
    out: list[str] = []
    for (a, _sa, ea), (b, sb, _eb) in zip(tokens, tokens[1:], strict=False):
        if text[ea:sb] == " ":
            out.append(f"{a} {b}")
    out.extend(token for token, _s, _e in tokens)
    return list(dict.fromkeys(out))


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
    heard = {h.casefold(): t.term for t in glossary for h in t.heard_as}
    pool = _pool(glossary, known_people, recording_names)
    exact = {spelling.casefold() for spelling in pool}
    out: dict[str, Correction] = {}
    marked: set[str] = set()
    for surface in surfaces:
        folded = surface.casefold()
        if folded in heard:
            if heard[folded] != surface:
                out[surface] = Correction(surface, heard[folded], SOURCE_GLOSSARY)
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
            out[surface] = Correction(surface, spelling, SOURCE_RECORDING)
            continue
        if best >= threshold and best - runner_up > AMBIGUITY_MARGIN:
            out[surface] = Correction(surface, spelling, pool[spelling])
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
