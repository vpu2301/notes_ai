"""Review step 2 — one normaliser for every scorer (``scripts/eval/_normalize.py``)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "eval"))

import _normalize as n  # noqa: E402

H = {"Marek Quill", "Wren Ashby", "Марек Квілл"}


def test_en_reporting_clause_and_suffix_fold_away() -> None:
    assert n.fold(
        "Marek Quill warned that the Ferrytale reprint may slip again.", "en", holders=H
    ) == ("the ferrytale reprint may slip again")
    assert n.fold("The reprint may slip again — according to Marek Quill.", "en", holders=H) == (
        "the reprint may slip again"
    )
    assert (
        n.fold("They expect that card stock stays short.", "en", holders=H)
        == "card stock stays short"
    )


def test_de_clause_zufolge_and_laut_fold_away() -> None:
    assert n.fold("Marek Quill sagte, dass der Nachdruck sich verzögert.", "de", holders=H) == (
        "der nachdruck sich verzögert"
    )
    assert (
        n.fold("Marek Quill zufolge bleibt Karton knapp.", "de", holders=H) == "bleibt karton knapp"
    )
    assert n.fold("Karton bleibt knapp — laut Quill.", "de", holders=H) == "karton bleibt knapp"


def test_uk_clause_and_suffix_fold_away() -> None:
    assert n.fold("Марек Квілл сказав, що передрук затримається.", "uk", holders=H) == (
        "передрук затримається"
    )
    assert n.fold("Передрук затримається — за словами Марека Квілла.", "uk", holders=H) == (
        "передрук затримається"
    )


def test_compound_rule_matches_by_suffix() -> None:
    assert n.contains("Die Nachdruckkosten steigen im Frühjahr.", "Druckkosten steigen", "de")
    assert n.contains("Quillhaven fair plans", "Quillhaven fair", "en")
    assert not n.contains("Die Kosten steigen.", "Kosten sinken", "de")
    # A token under COMPOUND_MIN never matches by suffix.
    assert not n.contains("the reprint", "rint", "en")


def test_a_line_not_about_the_holder_is_unchanged() -> None:
    text = "The Lantern edition remains planned for the Quillhaven fair."
    assert (
        n.fold(text, "en", holders=H)
        == "the lantern edition remains planned for the quillhaven fair"
    )
    assert n.fold("Quill Street stays closed.", "en", holders=H) == "quill street stays closed"


def test_the_clause_never_breaks_a_gold_match() -> None:
    gold = "card stock stays short until spring"
    assert n.contains(
        "Marek Quill expects that card stock stays short until spring.", gold, "en", holders=H
    )
    assert n.contains(
        "Marek Quill erwartet, dass Karton bis zum Frühjahr knapp bleibt.",
        "Karton bis zum Frühjahr knapp",
        "de",
        holders=H,
    )
