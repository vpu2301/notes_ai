"""One fact per thing that happened.

Windows overlap by a turn, and people restate what they just agreed, so
the same commitment arrives two or three times: once from each window
that saw it, and again because Anna repeated it at the end. Without this
pass a meeting note lists the same task three times, which reads as
carelessness and makes every count meaningless.

The rules, in order of what matters:

* **Keep the earliest quote.** Where a decision was first made is more
  useful than where it was repeated, and it puts the evidence chip at
  the moment the reader is looking for.
* **Prefer the explicit one.** If one copy has someone taking the task
  on by name and another does not, the first is the truth about it.
* **Union the flags**, so a doubt raised about any copy survives.

Pure.
"""

from __future__ import annotations

import dataclasses
from typing import Final

from . import support
from .verify import CONF_EXPLICIT, VerifiedFact

# Above this, two texts are the same statement in different words.
# Deliberately high: merging two DIFFERENT tasks loses one of them, which
# is worse than listing a near-duplicate.
SAME_FACT_JACCARD: Final = 0.8

# The tokeniser and stop list live in :mod:`support` (Q2), the one place
# the engine and the eval define words. Unchanged: which facts count as
# the same fact depends on them.
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
            # F3 — two figures are one only when they say the same number
            # about the same thing; "300 gallons" and "200 gallons" read
            # alike and are a conflict to show, not a duplicate to fold.
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
        # The earliest quote always wins, because `ordered` is by time and
        # `existing` came first. What the later copy can contribute is a
        # better owner, a real date, and its doubts.
        merged = existing
        if _better(fact, existing):
            # Every field of the earlier copy, including the ones added since
            # (F2's `copied`, F3's payloads), with what the later copy adds.
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


def by_kind(facts: list[VerifiedFact]) -> dict[str, list[VerifiedFact]]:
    out: dict[str, list[VerifiedFact]] = {}
    for fact in facts:
        out.setdefault(fact.kind, []).append(fact)
    return out
