"""D1 — the document lint (docs/eval/error-taxonomy.md, ADR-0065)."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from note_service.domain.meeting_doc import lint, pipeline, roles
from note_service.domain.meeting_doc.lint import LintLine, LintSection

from .meeting_doc_fakes import ScriptedProvider, as_result, load_fixture

MIN = 60_000


def _overview(*lines: LintLine) -> LintSection:
    return LintSection(
        roles.OVERVIEW_KEY, roles.SUMMARY, None, "\n".join(ln.text for ln in lines), lines
    )


def _topic(title: str, *texts: str, ids: tuple[str, ...] = ("a",)) -> LintSection:
    lines = tuple(LintLine(t, "bullet", ids) for t in texts)
    return LintSection(f"gen:{title}", roles.TOPICS, title, "\n".join(texts), lines)


FRAMING = LintLine("Podcast-Folge über Palantir. Es sprechen Erzähler/in.", "framing", ("a",))
SUMMARY = LintLine("Peter Thiel gründet Palantir im Jahr 2004.", "summary", ("a",))
GOOD = (
    "- Peter Thiel gründet Palantir 2004",
    "- Alex Karp wird 2004 Chef von Palantir",
)


def _rules(sections: list[LintSection], minutes: float = 3, **kw: object) -> dict[str, int]:
    return lint.lint(
        sections,
        language=kw.pop("language", "de"),  # type: ignore[arg-type]
        duration_ms=int(minutes * MIN),
        known=frozenset({"Peter", "Thiel", "Alex", "Karp", "Palantir"}),
        **kw,  # type: ignore[arg-type]
    ).by_rule()


def test_a_well_formed_note_has_no_findings() -> None:
    assert _rules([_overview(FRAMING, SUMMARY), _topic("Gründung von Palantir", *GOOD)]) == {}


def test_every_rule_has_a_taxonomy_code() -> None:
    assert set(lint.RULES.values()) <= {
        "D-ORIENT", "D-STRUCT", "D-HEAD", "D-SPEC", "D-VOL", "D-REF", "D-LABEL", "D-LANG",
        "D-FORM",
    }  # fmt: skip


def test_orientation() -> None:
    assert _rules([_topic("Gründung", *GOOD)]) == {"no_overview": 1}
    listed = _overview(SUMMARY, LintLine("- ein Punkt mit 2004", "key_point", ("a",)))
    assert _rules([listed, _topic("Gründung", *GOOD)]) == {
        "overview_no_framing": 1,
        "overview_list": 1,
    }


def test_structure() -> None:
    top = _overview(FRAMING, SUMMARY)
    assert _rules([top], minutes=30)["no_headings_long"] == 1
    assert _rules([top, _topic("Gründung", *GOOD)], minutes=31) == {
        "too_few_headings": 1,
        "volume_low": 1,  # and far too little for half an hour
    }
    assert _rules([top, _topic("Gründung", GOOD[0])]) == {"thin_section": 1}
    early = _topic("Karp", *GOOD, ids=("early",))
    late = _topic("Thiel", *GOOD, ids=("late",))
    starts = {"early": 1_000, "late": 9_000}
    assert _rules([top, late, early], fact_start_ms=starts) == {"out_of_order": 1}
    assert _rules([top, early, late], fact_start_ms=starts) == {}


@pytest.mark.parametrize(
    ("title", "rule"),
    [
        ("Diskussion", "heading_generic"),
        ("GRÜNDUNG VON PALANTIR", "heading_all_caps"),
        ("Wie Peter Thiel nach dem elften September eine Firma für Daten gründet", "heading_long"),
        ("Gründung:", "heading_punctuation"),
    ],
)
def test_headings(title: str, rule: str) -> None:
    assert _rules([_overview(FRAMING, SUMMARY), _topic(title, *GOOD)]) == {rule: 1}


def test_a_heading_twice_and_an_acronym_heading() -> None:
    top = _overview(FRAMING, SUMMARY)
    twice = [top, _topic("Palantir", *GOOD), _topic("Palantir", *GOOD)]
    assert _rules(twice) == {"heading_duplicate": 1}
    assert _rules([top, _topic("NATO", *GOOD)]) == {}


def test_lines() -> None:
    top = _overview(FRAMING, SUMMARY)
    bad = _topic(
        "Gründung",
        *GOOD,
        "- Ein riesiger Feuerball entsteht",  # D-SPEC
        "- Speaker 1 sagt, Palantir sei 2004 gegründet",  # D-LABEL
        "- Wir gründen Palantir 2004",  # D-LANG
        "- Palantir 2004 ❝",  # D-FORM
    )
    assert _rules([top, bad]) == {
        "bullet_unspecific": 1,
        "label_in_prose": 1,
        "first_person": 1,
        "marks": 1,
    }
    uncited = _topic("Gründung", *GOOD, ids=())
    assert _rules([top, uncited]) == {"uncited_line": 2}


def test_the_framing_may_name_the_narrator_but_a_sentence_may_not() -> None:
    top = _overview(FRAMING, LintLine("Erzähler/in beschreibt Palantir 2004.", "summary", ("a",)))
    assert _rules([top, _topic("Gründung", *GOOD)]) == {"label_in_prose": 1}


def test_a_said_date_makes_a_bullet_specific() -> None:
    top = _overview(FRAMING, SUMMARY)
    dated = _topic("Anons", "- Анонс для користувачів буде до п'ятниці", *GOOD[:1])
    assert "bullet_unspecific" not in _rules([top, dated], language="uk")


def test_volume() -> None:
    top = _overview(FRAMING, SUMMARY)
    assert _rules([top, _topic("Gründung", *GOOD)], minutes=30)["volume_low"] == 1
    long_lines = [f"- Palantir {n} " + "wort " * 40 for n in range(6)]
    assert _rules([top, _topic("Gründung", *long_lines)], minutes=3) == {"volume_high": 1}


def test_findings_carry_no_text() -> None:
    top = _overview(FRAMING, SUMMARY)
    result = lint.lint(
        [top, _topic("Gründung", *GOOD, "- Wir gründen")], language="de", duration_ms=3 * MIN
    )
    for finding in result.findings:
        assert set(vars(finding) if hasattr(finding, "__dict__") else finding.__slots__) == {
            "code", "rule", "section_key", "line"
        }  # fmt: skip


def test_the_pipeline_records_lint_counts() -> None:
    meeting = load_fixture("m01_en_product_sync")
    document = asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=ScriptedProvider(),
            role_by_key={},
            language="en",
            meeting_date=date(2026, 9, 22),
        )
    )
    assert isinstance(document.stats["lint"], dict)
    assert set(document.stats["lint_rules"]) <= set(lint.RULES)
    assert sum(document.stats["lint"].values()) == sum(document.stats["lint_rules"].values())
