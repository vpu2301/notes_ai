"""The action-line grammar and the due-date rules (Sprint 20, G-1).

Deterministic by construction: the same section text yields the same
items, keys and dates every time, which is what lets responses attach
across amendments. The fixture covers en/uk/de, with and without owner
and date, bulleted, numbered and glued lines.
"""

from __future__ import annotations

from datetime import date

import pytest

from note_service.domain.action_items import (
    item_key,
    normalise_text,
    parse_action_lines,
    parse_due,
)

# The note was finalized on a Wednesday.
ANCHOR = date(2026, 9, 16)

LINES: list[tuple[str, str | None, float | None, str, date | None]] = [
    # (line, owner, owner_conf, text, due)
    (
        "Anna: send the pricing proposal — by 18 Sep",
        "Anna",
        1.0,
        "send the pricing proposal",
        date(2026, 9, 18),
    ),
    (
        "- Anna: send the pricing proposal — by 18 Sep",
        "Anna",
        1.0,
        "send the pricing proposal",
        date(2026, 9, 18),
    ),
    ("• Tom: share brand assets – due 20 Sep", "Tom", 1.0, "share brand assets", date(2026, 9, 20)),
    (
        "1. Tom: share brand assets - 2026-09-20",
        "Tom",
        1.0,
        "share brand assets",
        date(2026, 9, 20),
    ),
    ("2) Anna Koval: book the venue", "Anna Koval", 1.0, "book the venue", None),
    ("Send the deck to legal", None, None, "Send the deck to legal", None),
    ("Send the deck to legal — Friday", None, None, "Send the deck to legal", date(2026, 9, 18)),
    ("Send the deck to legal by Friday", None, None, "Send the deck to legal", date(2026, 9, 18)),
    ("Send the deck to legal — next week", None, None, "Send the deck to legal", date(2026, 9, 23)),
    ("Send the deck to legal — tomorrow", None, None, "Send the deck to legal", date(2026, 9, 17)),
    ("Send the deck to legal — today", None, None, "Send the deck to legal", ANCHOR),
    ("Send the deck to legal — Wednesday", None, None, "Send the deck to legal", date(2026, 9, 23)),
    ("Send the deck to legal — Sep 18", None, None, "Send the deck to legal", date(2026, 9, 18)),
    (
        "Send the deck to legal — September 18, 2026",
        None,
        None,
        "Send the deck to legal",
        date(2026, 9, 18),
    ),
    (
        "Send the deck to legal — 18.09.2026",
        None,
        None,
        "Send the deck to legal",
        date(2026, 9, 18),
    ),
    ("Send the deck to legal — 18.09", None, None, "Send the deck to legal", date(2026, 9, 18)),
    ("Send the deck to legal — 5 Jan", None, None, "Send the deck to legal", date(2027, 1, 5)),
    ("Send the deck to legal — end of quarter", None, None, "Send the deck to legal", None),
    ("Send the deck to legal — 31 Feb", None, None, "Send the deck to legal", None),
    (
        "Marta Lange prepares the budget draft",
        "Marta Lange",
        0.5,
        "Marta Lange prepares the budget draft",
        None,
    ),
    ("Prepare the budget draft", None, None, "Prepare the budget draft", None),
    ("Tom: fix the invoice — by 1st Oct", "Tom", 1.0, "fix the invoice", date(2026, 10, 1)),
    (
        "Ops team: rotate the keys — 2026-10-01",
        "Ops team",
        1.0,
        "rotate the keys",
        date(2026, 10, 1),
    ),
    (
        "* Review the contract with a 3-year term",
        None,
        None,
        "Review the contract with a 3-year term",
        None,
    ),
    (
        "Follow up on Q3 numbers — 2026-12-31",
        None,
        None,
        "Follow up on Q3 numbers",
        date(2026, 12, 31),
    ),
    ("Draft note: check the numbers", "Draft note", 1.0, "check the numbers", None),
    ("http://example.com/spec: read it", None, None, "http://example.com/spec: read it", None),
    # Ukrainian
    (
        "Оксана: надіслати комерційну пропозицію — до 18 вересня",
        "Оксана",
        1.0,
        "надіслати комерційну пропозицію",
        date(2026, 9, 18),
    ),
    ("- Ігор: підготувати макети — завтра", "Ігор", 1.0, "підготувати макети", date(2026, 9, 17)),
    ("Підготувати макети — у п’ятницю", None, None, "Підготувати макети", date(2026, 9, 18)),
    ("Підготувати макети — наступного тижня", None, None, "Підготувати макети", date(2026, 9, 23)),
    (
        "Оксана Іванюк надсилає рахунок",
        "Оксана Іванюк",
        0.5,
        "Оксана Іванюк надсилає рахунок",
        None,
    ),
    ("Надіслати рахунок — 20.09.2026", None, None, "Надіслати рахунок", date(2026, 9, 20)),
    ("Надіслати рахунок — 1 жовтня", None, None, "Надіслати рахунок", date(2026, 10, 1)),
    # German
    (
        "Jonas: Angebot schicken — bis 18. September",
        "Jonas",
        1.0,
        "Angebot schicken",
        date(2026, 9, 18),
    ),
    ("- Jonas: Angebot schicken — Freitag", "Jonas", 1.0, "Angebot schicken", date(2026, 9, 18)),
    ("Angebot schicken — nächste Woche", None, None, "Angebot schicken", date(2026, 9, 23)),
    ("Angebot schicken — morgen", None, None, "Angebot schicken", date(2026, 9, 17)),
    ("Angebot schicken — übermorgen", None, None, "Angebot schicken", date(2026, 9, 18)),
    ("Angebot schicken — 5. März 2027", None, None, "Angebot schicken", date(2027, 3, 5)),
    ("Angebot schicken — am Montag", None, None, "Angebot schicken", date(2026, 9, 21)),
    ("Lena Bauer prüft den Vertrag", "Lena Bauer", 0.5, "Lena Bauer prüft den Vertrag", None),
    ("Vertrag prüfen — 18.9.", None, None, "Vertrag prüfen", date(2026, 9, 18)),
    ("   ", None, None, "", None),  # blank: dropped
]


def test_fixture_is_large_enough() -> None:
    assert len([line for line, *_ in LINES if line.strip()]) >= 40


@pytest.mark.parametrize(("line", "owner", "owner_conf", "text", "due"), LINES)
def test_each_line(
    line: str, owner: str | None, owner_conf: float | None, text: str, due: date | None
) -> None:
    items = parse_action_lines(line, anchor=ANCHOR)
    if not line.strip():
        assert items == []
        return
    assert len(items) == 1
    item = items[0]
    assert item.owner_label == owner
    assert item.owner_confidence == owner_conf
    assert item.text == text
    assert item.due_date == due


def test_whole_section_keeps_order_and_is_deterministic() -> None:
    section = "\n".join(line for line, *_ in LINES)
    a = parse_action_lines(section, anchor=ANCHOR)
    b = parse_action_lines(section, anchor=ANCHOR)
    assert [i.item_key for i in a] == [i.item_key for i in b]
    assert [i.text for i in a][:3] == [t for _, _, _, t, _ in LINES[:3]]


def test_key_ignores_owner_date_bullets_and_case() -> None:
    a = parse_action_lines("- Anna: Send the pricing proposal — by 18 Sep", anchor=ANCHOR)[0]
    b = parse_action_lines("Tom: send the pricing proposal.", anchor=ANCHOR)[0]
    c = parse_action_lines("send the pricing proposal", anchor=ANCHOR)[0]
    assert a.item_key == b.item_key == c.item_key
    edited = parse_action_lines("send the pricing proposal to Tom", anchor=ANCHOR)[0]
    assert edited.item_key != a.item_key
    assert len(a.item_key) == 16
    assert item_key(normalise_text("Send the pricing proposal")) == a.item_key


def test_due_text_is_kept_even_when_unparseable() -> None:
    item = parse_action_lines("Ship it — end of quarter", anchor=ANCHOR)[0]
    assert item.due_text == "end of quarter"
    assert item.due_date is None
    assert item.due_confidence == 0.5


def test_parse_due_never_raises() -> None:
    for text in ["", "???", "99.99.9999", "2026-13-40", "\x00", "Monday Tuesday"]:
        assert parse_due(text, anchor=ANCHOR) is None or isinstance(
            parse_due(text, anchor=ANCHOR), date
        )
