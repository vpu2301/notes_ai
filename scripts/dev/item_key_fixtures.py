#!/usr/bin/env python3
"""Regenerate ``web/tests/fixtures/item-keys.json`` (Summary Engine v2, Q5).

The web finds a generated line's evidence row by hashing the line it
displays the way the server keys it (``lines.key_of`` after
``lines.strip_marker``). Both test suites read this file, so the two
implementations cannot drift apart unnoticed.

    uv run --project services/note-service python scripts/dev/item_key_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

from note_service.domain import lines

OUT = Path(__file__).resolve().parents[2] / "web" / "tests" / "fixtures" / "item-keys.json"

LINES = [
    "- Anna: send the pricing proposal — by Tuesday",
    "- Tom: book the room",
    "- send the deck.",
    "The union calls a strike.",
    "Passenger numbers fell by 12 percent.",
    "- Das Aus für die Rente mit 63 wird abgeschwächt — laut Reinbold",
    "- Die Mütterrente soll vorgezogen werden (Vorschlag: Söder)",
    "- Voraussichtlich: Das Aus wird abgeschwächt",
    "- 23.09.2026 00:00 — Der Warnstreik soll bis Mittwoch 0 Uhr dauern",
    "- 01.10.2026 — Ab 1. Oktober gilt die neue Regel",
    "- Mira: Publish the timetable by Friday",
    "* Засідання перенесли на середу",
    "1. Check https://example.com: it loads",
    "  -   Spaces   and   CASE  ",
    "- Laut Fabian Reinbold wird die Mehrheit knapp",
    "- Emil (?) kommentiert die Entscheidung",
    "- A 3-year term was proposed",
    "- One two three four five: not an owner",
]


def main() -> None:
    cases = [{"line": line, "key": lines.key_of(lines.strip_marker(line)[1])} for line in LINES]
    OUT.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
