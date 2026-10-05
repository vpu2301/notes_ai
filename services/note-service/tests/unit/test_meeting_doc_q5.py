"""Every line traceable (Summary Engine v2, Q5).

Every written line becomes a row with the evidence of what it cites; the
key dates a recording named form their own block, each downloadable as a
calendar file; the rows' kinds stay inside what the database accepts.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, time

from note_service.domain import ics_writer, lines
from note_service.domain.meeting_doc import pipeline, render, roles, schema, types
from note_service.domain.meeting_doc.verify import DateMention, VerifiedFact
from note_service.jobs.generate_note import line_row

from .meeting_doc_fakes import REPO, ScriptedProvider, as_result, load_fixture

DAY = date(2026, 9, 22)
MIGRATION = REPO / "infra" / "postgres" / "migrations" / "0059_generated_lines.sql"


def _fact(text: str, start: int, **kw: object) -> VerifiedFact:
    base: dict[str, object] = {
        "kind": schema.KEY_POINT,
        "text": text,
        "quote": f"said: {text}",
        "turn": 0,
        "start_ms": start,
        "end_ms": start + 5_000,
        "speaker_label": "SPEAKER_1",
        "speaker_name": "Jonas Pfeffer",
    }
    base.update(kw)
    return VerifiedFact(**base)  # type: ignore[arg-type]


# ── T1: every written line is a row ─────────────────────────────────


def _document() -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            as_result(load_fixture("m06_de_news_podcast")),
            provider=ScriptedProvider(),
            role_by_key={"decisions": roles.DECISIONS},
            language="de",
            meeting_date=DAY,
            family=types.family_for_recording_type("podcast_broadcast"),
        )
    )


def test_every_written_line_has_a_row_keyed_like_the_corrections_routes() -> None:
    document = _document()
    by_id = {f.item_key: f for f in document.facts}
    written = [(key, line) for key, line in document.lines if line.kind != "heading"]
    assert written
    for section_key, line in written:
        row = line_row(line, section_key, "written", by_id)
        assert row is not None, line
        assert row["item_key"] == lines.key_of(lines.strip_marker(line.text)[1])
        assert row["quote"] and row["cites"] == list(line.fact_ids)


def test_a_sentence_citing_two_facts_carries_both_and_the_first_ones_evidence() -> None:
    a = _fact("the union calls a strike", 1_000, certainty="fact")
    b = _fact("the strike may last until Wednesday", 2_000, certainty="prediction")
    line = render.Line(
        "The union strikes, probably until Wednesday.", "summary", (a.item_key, b.item_key)
    )
    row = line_row(line, roles.OVERVIEW_KEY, "written", {a.item_key: a, b.item_key: b})
    assert row is not None
    assert row["kind"] == "summary_sentence"
    assert row["cites"] == [a.item_key, b.item_key]
    assert row["quote"] == a.quote and row["start_ms"] == 1_000
    # As sure as the weakest fact it rests on; one holder shared by both.
    assert row["certainty"] == "prediction"
    assert row["attributed_to"] is None


def test_a_heading_or_a_line_without_evidence_is_no_row() -> None:
    assert (
        line_row(render.Line("### We do", "heading", ("x",)), "action_items", "written", {}) is None
    )
    assert line_row(render.Line("A line", "summary", ()), roles.OVERVIEW_KEY, "written", {}) is None


def test_every_kind_the_engine_can_write_is_one_the_database_accepts() -> None:
    """The 0059 CHECK lists every kind; a family growing a new one without
    the migration would fail inserts in production."""
    sql = MIGRATION.read_text("utf-8")
    block = sql[sql.index("note_generated_items_kind_vocab_check") :]
    allowed = set(re.findall(r"'([a-z_]+)'", block[: block.index("));")]))
    engine = set(types.GENERIC_KINDS) | set(schema.FACT_KINDS) | {schema.JUDGEMENT}
    for family in types.FAMILIES:
        engine |= set(family.extra_kinds)
    engine |= {"summary_sentence", "framing", "topic_bullet", "date"}
    assert engine <= allowed, engine - allowed


# ── T3: key dates ───────────────────────────────────────────────────


def _dated(
    text: str, start: int, when: date, at: time | None = None, direction: str = "future"
) -> VerifiedFact:
    return _fact(text, start, mentions=(DateMention("x", when, at, direction),))


def test_key_dates_are_what_is_coming_once_each_in_order() -> None:
    facts = [
        _dated(
            "Der Warnstreik soll bis Mittwoch 0 Uhr dauern", 1_000, date(2026, 9, 23), time(0, 0)
        ),
        _dated("Der Streik endet Mittwoch", 2_000, date(2026, 9, 23), time(0, 0)),
        _dated("Ab 1. Oktober gilt die neue Regel", 3_000, date(2026, 10, 1)),
        _dated("Seit heute wird gestreikt", 4_000, DAY),
        _dated("Die Runde am Montag war ohne Ergebnis", 5_000, date(2026, 9, 21), direction="past"),
        _fact("Ende des Jahres wird neu verhandelt", 6_000),
    ]
    sections = render.render_sections(facts, role_by_key={}, language="de", meeting_date=DAY)
    (block,) = [s for s in sections if s.role == roles.KEY_DATES]
    assert block.section_key == "key_dates" and block.title == "Termine & Fristen"
    assert block.text.splitlines() == [
        "- 23.09.2026 00:00 — Der Warnstreik soll bis Mittwoch 0 Uhr dauern",
        "- 01.10.2026 — Ab 1. Oktober gilt die neue Regel",
    ]
    assert [line.kind for line in block.lines] == ["date", "date"]
    assert block.lines[0].dates[0].time == time(0, 0)


def test_no_key_dates_block_without_a_date_to_come() -> None:
    sections = render.render_sections([_fact("Plain point", 0)], role_by_key={}, meeting_date=DAY)
    assert not [s for s in sections if s.role == roles.KEY_DATES]


def test_english_dates_read_the_iso_way() -> None:
    assert render.format_when(date(2026, 10, 1), None, "en") == "2026-10-01"
    assert render.format_when(date(2026, 9, 23), time(0, 0), "uk") == "23.09.2026 00:00"


# ── T3: the calendar file ───────────────────────────────────────────

NOW = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)


def test_an_all_day_date_and_a_timed_one() -> None:
    all_day = ics_writer.event(
        uid="k@n", summary="S", description="D", on=date(2026, 10, 1), now=NOW
    )
    assert "DTSTART;VALUE=DATE:20261001" in all_day and "DTEND;VALUE=DATE:20261002" in all_day
    timed = ics_writer.event(
        uid="k@n", summary="S", description="D", on=date(2026, 9, 23), at=time(0, 0), now=NOW
    )
    assert "DTSTART:20260923T000000" in timed and "DTEND:20260923T010000" in timed
    assert timed.startswith("BEGIN:VCALENDAR\r\n") and timed.endswith("END:VCALENDAR\r\n")
    assert "DTSTAMP:20260922T080000Z" in timed


def test_text_is_escaped_and_long_lines_are_folded() -> None:
    assert ics_writer.escape("a, b; c\nd\\e") == "a\\, b\\; c\\nd\\\\e"
    folded = ics_writer.fold("DESCRIPTION:" + "ü" * 80)
    for part in folded.split("\r\n"):
        assert len(part.encode("utf-8")) <= 75
    assert folded.replace("\r\n ", "") == "DESCRIPTION:" + "ü" * 80


def test_the_summary_is_capped() -> None:
    body = ics_writer.event(uid="k", summary="x" * 300, description="", on=DAY, now=NOW)
    unfolded = body.replace("\r\n ", "").split("\r\n")
    summary = next(row for row in unfolded if row.startswith("SUMMARY:"))
    assert len(summary) == len("SUMMARY:") + ics_writer.MAX_SUMMARY


def test_the_python_item_key_fixtures_are_current() -> None:
    """The web hashes a displayed line to find its row (Q5 T2). Both suites
    read `web/tests/fixtures/item-keys.json`; regenerate it with
    `scripts/dev/item_key_fixtures.py` when the key rule changes."""
    import json

    fixture = REPO / "web" / "tests" / "fixtures" / "item-keys.json"
    cases = json.loads(fixture.read_text("utf-8"))
    assert len(cases) >= 10
    for case in cases:
        assert lines.key_of(lines.strip_marker(case["line"])[1]) == case["key"], case["line"]


def test_facts_no_line_cites_are_kept_for_the_detailed_view() -> None:
    from note_service.jobs.generate_note import uncited_rows

    document = _document()
    cited = {i for s in document.sections for line in s.lines for i in line.fact_ids}
    rows = uncited_rows(document)
    assert {r["cites"][0] for r in rows} == {f.item_key for f in document.facts} - cited
    assert all(r["placement"] == "suggested" for r in rows)
    topic_keys = {s.section_key for s in document.sections} | {roles.OVERVIEW_KEY}
    assert all(r["section_key"] in topic_keys for r in rows)
