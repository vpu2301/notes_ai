"""Name suggestions from self-introductions (Sprint 32 B-1). Pure.

"Hi, this is Anna from Acme" on an unnamed speaker whose meeting invited
"Anna Keller" → suggest "Anna Keller" for that speaker, with the quote as
evidence. A person accepts; nothing is ever applied automatically.

Precision first, by construction:

* **Candidate match is mandatory.** The introduced name must match
  exactly one calendar invitee (casefolded, whole name — or first name
  when that first name is unique among the invitees). No invitee list →
  no suggestions. ASR misspells names; the list is what makes this safe,
  and the suggestion uses the CALENDAR spelling.
* **Ambiguity suggests nothing.** A speaker matching two invitees, or two
  speakers claiming one invitee, gets no suggestion.
* **Only unnamed speakers**, only invitees not already used as a name,
  never a dismissed (label, name) pair.

Where to look: a speaker's first two turns and any of its turns in the
first three minutes, first 400 characters of each — introductions happen
at the start. No model call, no stored state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .name_patterns import find_introductions, supported

SCAN_CHARS = 400
EARLY_MS = 180_000
QUOTE_CHARS = 160


@dataclass(frozen=True)
class NameSuggestion:
    label: str
    name: str
    quote: str
    start_ms: int
    end_ms: int
    segment_indices: list[int]
    source: str = "self_introduction"
    # Sprint F3: what the person said they do, verbatim, or None.
    role_text: str | None = None


def suggest(
    turns: Sequence[object],
    *,
    language: str,
    candidates: Sequence[str],
    custom_names: dict[str, str],
    dismissed: Iterable[tuple[str, str]] = (),
) -> list[NameSuggestion]:
    """Suggestions for the unnamed speakers of ``turns`` (result-view turns:
    ``speaker``, ``paragraphs``, ``start_ms``, ``end_ms``, ``segment_indices``)."""
    lang = (language or "")[:2].lower()
    if not candidates or not supported(lang):
        return []
    pool = [c for c in candidates if not _taken(c, custom_names.values())]
    if not pool:
        return []
    dismissed_pairs = {(label, _norm(name)) for label, name in dismissed}

    found: dict[str, dict[str, NameSuggestion]] = {}  # label → candidate → evidence
    seen_turns: dict[str, int] = {}
    for turn in turns:
        label = getattr(turn, "speaker", None)
        if not label or label in custom_names:
            continue
        seen_turns[label] = seen_turns.get(label, 0) + 1
        if seen_turns[label] > 2 and int(getattr(turn, "start_ms", 0)) >= EARLY_MS:
            continue
        text = " ".join(getattr(turn, "paragraphs", []) or [])[:SCAN_CHARS]
        for intro in find_introductions(text, lang):
            # Uniqueness is judged against ALL invitees: with "Anna Keller"
            # already named and "Anna Schmidt" left, "I'm Anna" is still
            # ambiguous (an over-split Anna Keller says it too).
            candidate = _match(intro.name, candidates)
            if candidate is not None and candidate not in pool:
                continue
            if candidate is None or (label, _norm(candidate)) in dismissed_pairs:
                continue
            found.setdefault(label, {}).setdefault(
                candidate,
                NameSuggestion(
                    label=label,
                    name=candidate,
                    quote=_quote(text, intro.start, intro.end),
                    start_ms=int(getattr(turn, "start_ms", 0)),
                    end_ms=int(getattr(turn, "end_ms", 0)),
                    segment_indices=list(getattr(turn, "segment_indices", []) or []),
                    role_text=intro.role_text,
                ),
            )

    # Every label that matched an invitee claims it — also a label that
    # matched several (and so gets nothing itself).
    claims: dict[str, int] = {}
    for per_label in found.values():
        for candidate in per_label:
            claims[candidate] = claims.get(candidate, 0) + 1
    out: list[NameSuggestion] = []
    for per_label in found.values():
        if len(per_label) != 1:
            continue  # one speaker, two invitees: say nothing
        ((candidate, suggestion),) = per_label.items()
        if claims[candidate] == 1:  # two speakers, one invitee: say nothing
            out.append(suggestion)
    return out


_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})


def _norm(name: str) -> str:
    """Casefolded, one kind of apostrophe (Дарʼя = Дар'я, O’Neil = O'Neil)."""
    name = name.translate(_APOSTROPHES)
    return " ".join(re.sub(r"[^\w\s'-]", " ", name).casefold().split())


def _taken(candidate: str, names: Iterable[str]) -> bool:
    """A person already used this invitee as a name — in full, or by a
    one-word name that is this invitee's first name ("Anna" for "Anna Keller")."""
    cand = _norm(candidate)
    for name in names:
        chosen = _norm(name)
        if chosen == cand or (" " not in chosen and cand.split()[:1] == [chosen]):
            return True
    return False


def _match(introduced: str, candidates: Sequence[str]) -> str | None:
    """The one invitee this introduction names, else None."""
    said = _norm(introduced)
    if not said:
        return None
    exact = [c for c in candidates if _norm(c) == said]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    said_first = said.split()[0]
    if len(said.split()) > 1:
        return None  # "Anna Schmidt" is not "Anna Keller"
    firsts = [c for c in candidates if _norm(c).split()[:1] == [said_first]]
    return firsts[0] if len(firsts) == 1 else None


def _quote(text: str, start: int, end: int) -> str:
    """≤ QUOTE_CHARS around the match, cut at word boundaries."""
    if len(text) <= QUOTE_CHARS:
        return text.strip()
    pad = max(0, (QUOTE_CHARS - (end - start)) // 2)
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    if lo > 0 and " " in text[lo:start]:
        lo = text.index(" ", lo) + 1
    if hi < len(text) and " " in text[end:hi]:
        hi = text.rindex(" ", end, hi)
    snippet = text[lo:hi].strip()
    return snippet[:QUOTE_CHARS].rstrip()
