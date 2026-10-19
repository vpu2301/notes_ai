"""One fact per thing that happened (windows overlap and people restate):
keep the earliest quote, prefer the explicit owner, union the flags. Pure.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Final

from . import support
from .verify import CONF_EXPLICIT, MERGED, VerifiedFact

# Deliberately high: merging two DIFFERENT tasks loses one of them.
SAME_FACT_JACCARD: Final = 0.8

# Which facts count as the same fact depends on this list; do not change it lightly.
_STOP: Final[frozenset[str]] = support.MERGE_STOP
_tokens = support.merge_tokens


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    return overlap / len(a | b) if overlap else 0.0


def _better(new: VerifiedFact, kept: VerifiedFact) -> bool:
    """Whether ``new`` should replace ``kept`` as the surviving copy."""
    if new.explicit != kept.explicit:
        return new.explicit
    if (new.owner_label is not None) != (kept.owner_label is not None):
        return new.owner_label is not None
    if (new.due_date is not None) != (kept.due_date is not None):
        return new.due_date is not None
    return False


def merge_facts(facts: list[VerifiedFact]) -> list[VerifiedFact]:
    """De-duplicated, in the order things were said."""
    ordered = sorted(facts, key=lambda f: (f.start_ms, f.window_index, f.turn))
    kept: list[tuple[frozenset[str], VerifiedFact]] = []

    for fact in ordered:
        tokens = _tokens(fact.text)
        match_at: int | None = None
        for index, (other_tokens, other) in enumerate(kept):
            if other.kind != fact.kind:
                continue
            # Two figures are one only with the same number: "300" vs "200 gallons" is a conflict to show.
            if (
                fact.figure is not None or other.figure is not None
            ) and fact.figure != other.figure:
                continue
            if (
                fact.item_key == other.item_key
                or _jaccard(tokens, other_tokens) >= SAME_FACT_JACCARD
            ):
                match_at = index
                break

        if match_at is None:
            kept.append((tokens, fact))
            continue

        _, existing = kept[match_at]
        # The earliest quote wins; the later copy may contribute an owner, a date and its doubts.
        merged = existing
        if _better(fact, existing):
            merged = dataclasses.replace(
                existing,
                owner_label=fact.owner_label or existing.owner_label,
                due_text=fact.due_text or existing.due_text,
                due_date=fact.due_date or existing.due_date,
                explicit=fact.explicit or existing.explicit,
                confidence=max(fact.confidence, existing.confidence),
                flags=list(existing.flags),
                certainty=existing.certainty or fact.certainty,
                attributed_to=existing.attributed_to or fact.attributed_to,
            )
        else:
            merged.owner_label = merged.owner_label or fact.owner_label
            merged.due_text = merged.due_text or fact.due_text
            merged.due_date = merged.due_date or fact.due_date

        # A doubt raised about any copy survives the merge.
        for flag in fact.flags:
            if flag not in merged.flags:
                merged.flags.append(flag)
        if merged.explicit and not [f for f in merged.flags if f != "owner_inferred"]:
            merged.confidence = max(merged.confidence, CONF_EXPLICIT)
        kept[match_at] = (_tokens(merged.text), merged)

    return [fact for _, fact in kept]


# ── Fidelity: merge only what says the same thing, and keep every source ──

# Below SAME_FACT_JACCARD but this close: a candidate for the meaning-equivalence check.
CANDIDATE_JACCARD: Final = 0.45
# Two quotes of the same passage: this share of the shorter one's words in common.
SAME_SOURCE_QUOTE: Final = 0.6
_DIGITS: Final = re.compile(r"\d[\d.,]*")


def _figures(text: str) -> frozenset[str]:
    return frozenset(m.replace(",", "").replace(".", "") for m in _DIGITS.findall(text))


def compatible(a: VerifiedFact, b: VerifiedFact) -> bool:
    """Code's veto before any merge: same kind and figure, the same numbers, both or
    neither negated, both or neither conditional. Two amounts or two conditions are
    two statements, however alike their words."""
    if a.kind != b.kind or a.figure != b.figure:
        return False
    if _figures(a.text) != _figures(b.text):
        return False
    if support.negated(a.text) != support.negated(b.text):
        return False
    return support.conditional(a.text) == support.conditional(b.text)


def absorb(survivor: VerifiedFact, copy: VerifiedFact) -> tuple[VerifiedFact, VerifiedFact]:
    """``(survivor, copy as evidence)``: the copy's key joins ``survivor.also`` and its
    own doubts the survivor's flags; the copy stays, flagged ``MERGED``, as a source."""
    flags = list(survivor.flags)
    for flag in copy.flags:
        if flag not in flags:
            flags.append(flag)
    merged = dataclasses.replace(
        survivor,
        also=tuple(dict.fromkeys([*survivor.also, copy.item_key, *copy.also])),
        flags=flags,
        owner_label=survivor.owner_label or copy.owner_label,
        due_text=survivor.due_text or copy.due_text,
        due_date=survivor.due_date or copy.due_date,
        attributed_to=survivor.attributed_to or copy.attributed_to,
    )
    source = dataclasses.replace(copy, flags=[*copy.flags, MERGED], also=())
    return merged, source


def precise_first(
    a: VerifiedFact, b: VerifiedFact, language: str
) -> tuple[VerifiedFact, VerifiedFact]:
    """``(survivor, copy)``: the more specific wording survives; on a tie, the earlier."""
    sa, sb = support.specificity(a.text, language), support.specificity(b.text, language)
    if sb > sa or (sb == sa and b.start_ms < a.start_ms):
        return b, a
    return a, b


def merge_with_sources(
    facts: list[VerifiedFact], *, language: str
) -> tuple[list[VerifiedFact], list[VerifiedFact]]:
    """``(kept, sources)``: like :func:`merge_facts`, but only :func:`compatible` facts
    merge, the more precise wording survives, and every merged copy is returned as a
    source (``MERGED``) its survivor cites through ``also``."""
    ordered = sorted(facts, key=lambda f: (f.start_ms, f.window_index, f.turn))
    kept: list[VerifiedFact] = []
    sources: list[VerifiedFact] = []
    for fact in ordered:
        tokens = _tokens(fact.text)
        at = next(
            (
                i
                for i, other in enumerate(kept)
                if compatible(fact, other)
                and (
                    fact.item_key == other.item_key
                    or _jaccard(tokens, _tokens(other.text)) >= SAME_FACT_JACCARD
                )
            ),
            None,
        )
        if at is None:
            kept.append(fact)
            continue
        survivor, copy = precise_first(kept[at], fact, language)
        if copy.item_key == survivor.item_key:
            # The same statement twice (overlapping windows): nothing new to cite.
            kept[at] = survivor
            continue
        kept[at], source = absorb(survivor, copy)
        sources.append(source)
    return kept, sources


def same_source(a: VerifiedFact, b: VerifiedFact) -> bool:
    """Both restate the same spoken passage: the same line, and one quote's words mostly
    the other's. Two paraphrases of one promise share few words but this."""
    if a.start_ms != b.start_ms:
        return False
    qa, qb = _tokens(a.quote), _tokens(b.quote)
    return bool(qa and qb) and len(qa & qb) / min(len(qa), len(qb)) >= SAME_SOURCE_QUOTE


def candidates(facts: list[VerifiedFact]) -> list[tuple[int, int]]:
    """Index pairs close in words but under the merge bar, or restating the same spoken
    passage (:func:`same_source`), that :func:`compatible` allows: what the
    meaning-equivalence check decides. Same passage first, then nearest, so a cap keeps
    the likeliest."""
    tokens = [_tokens(f.text) for f in facts]
    scored = []
    for i in range(len(facts)):
        for j in range(i + 1, len(facts)):
            if not compatible(facts[i], facts[j]):
                continue
            score = _jaccard(tokens[i], tokens[j])
            if score >= SAME_FACT_JACCARD:
                continue
            if same_source(facts[i], facts[j]):
                scored.append((1.0 + score, i, j))
            elif score >= CANDIDATE_JACCARD:
                scored.append((score, i, j))
    return [(i, j) for _score, i, j in sorted(scored, reverse=True)]


def by_kind(facts: list[VerifiedFact]) -> dict[str, list[VerifiedFact]]:
    out: dict[str, list[VerifiedFact]] = {}
    for fact in facts:
        out.setdefault(fact.kind, []).append(fact)
    return out
