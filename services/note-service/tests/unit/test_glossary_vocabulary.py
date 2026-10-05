"""Only names and terms become vocabulary.

The role-word and ordinal tables are the fixture every client reads;
the hint carries only vocabulary, people and companies first.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from note_service.domain import glossary as rules
from note_service.domain.glossary import Term

REPO = Path(__file__).resolve().parents[4]
FIXTURE = json.loads(
    (REPO / "tests" / "fixtures" / "glossary" / "role_words.json").read_text("utf-8")
)


def test_the_tables_are_the_shared_fixture() -> None:
    for language, words in FIXTURE["role_words"].items():
        assert rules.ROLE_WORDS[language] == frozenset(words), language
    assert set(rules.ROLE_WORDS) == set(FIXTURE["role_words"])
    assert frozenset(FIXTURE["ordinals"]) == rules.ORDINALS


@pytest.mark.parametrize(
    "term",
    [
        "Moderator II",
        "moderatorin",
        "Narrator",
        "speaker background",
        "Sprecher 2",
        "Ведучий",
        "Speaker 3",
        "unknown voice",
        "Гість 2",
        "II",
    ],
)
def test_role_labels_are_not_vocabulary(term: str) -> None:
    assert not rules.is_vocabulary(term, "person")


@pytest.mark.parametrize(
    ("term", "kind"),
    [
        ("Gregor Gysi", "person"),
        ("Springbrook Marine Group", "company"),
        ("Pardo", "product"),
        ("Williams Jet Tender", "product"),
        ("IPS 1350", "product"),
        ("Moderator Gysi", "person"),  # a role word next to a name is a name
        ("moderatorin", "term"),  # not a person: no capital needed... but all role words
    ],
)
def test_names_and_terms_are_vocabulary(term: str, kind: str) -> None:
    expected = term != "moderatorin"
    assert rules.is_vocabulary(term, kind) is expected


def test_a_person_needs_a_capital_letter_somewhere() -> None:
    assert not rules.is_vocabulary("gregor gysi", "person")
    assert rules.is_vocabulary("gregor gysi", "term")
    assert rules.is_vocabulary("van der Berg", "person")


def test_the_hint_carries_only_vocabulary_people_and_companies_first() -> None:
    terms = [
        Term("Moderator II", "person", ()),
        Term("IPS 1350", "product", ()),
        Term("Gregor Gysi", "person", ()),
        Term("speaker background", "person", ()),
        Term("Springbrook Marine", "company", ()),
        Term("Pardo", "product", ()),
    ]
    assert rules.hint_text(terms) == "Gregor Gysi, Springbrook Marine, IPS 1350, Pardo"
    assert [t.term for t in rules.hint_terms(terms)] == [
        "Gregor Gysi",
        "Springbrook Marine",
        "IPS 1350",
        "Pardo",
    ]


def test_the_incident_workspace_sends_nothing() -> None:
    incident = [
        Term(t, "person", ())
        for t in (
            "Moderator",
            "moderatorin",
            "narrator",
            "speaker",
            "speaker background",
            "Moderator II",
        )
    ]
    assert rules.hint_text(incident) == ""
    assert rules.hint_text([*incident, Term("Gregor Gysi", "person", ())]) == "Gregor Gysi"
