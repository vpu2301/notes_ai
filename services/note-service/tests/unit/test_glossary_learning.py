"""Sprint TQ3 T3: an accepted spelling teaches the glossary.

The clients send an accepted correction's variants to ``POST /v1/glossary``
as ``heard_as`` of its spelling; for an existing term that merges (the route
answers 200). These pin the merge rules the correction relies on.
"""

from __future__ import annotations

from note_service.domain import glossary as rules


def test_a_corrections_variants_join_the_terms_heard_as() -> None:
    merged = rules.clean_heard_as(["Handler", "Andala", "Handela", "Hand aller"], term="Handala")
    assert merged == ["Handler", "Andala", "Handela", "Hand aller"]


def test_learning_twice_dedupes_never_stores_the_term_and_caps() -> None:
    first = rules.clean_heard_as(["Andala", "Handela"], term="Handala")
    again = rules.clean_heard_as([*first, "andala", "Handala", "Handela"], term="Handala")
    assert again == ["Andala", "Handela"]
    many = rules.clean_heard_as([f"Handal{c}" for c in "bcdefghijkl"], term="Handala")
    assert len(many) == rules.MAX_HEARD_AS


def test_the_hint_still_sends_the_term_only() -> None:
    # The next job's transcriber is told the right spelling; the variants
    # reach the next job through the unifier's glossary read instead.
    term = rules.Term(term="Handala", kind="term", heard_as=("Andala", "Handela"))
    assert rules.hint_text([term]) == "Handala"
