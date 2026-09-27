"""D1 — the document standard in code (docs/eval/document-standard.md,
meeting_doc/doclint.py, ADR-0065).

Every test starts from one note that meets the standard and breaks one
rule of it.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import date

import pytest

from note_service.domain.meeting_doc import doclint, pipeline, render, roles
from note_service.domain.meeting_doc.doclint import LintFact, LintLine, LintSection

from .meeting_doc_fakes import ScriptedProvider, as_result, load_fixture

MIN = 60_000
KNOWN = frozenset({"Peter", "Thiel", "Alex", "Karp", "Palantir", "Holtermann", "Felix", "PayPal"})

PARA1 = (
    "Podcast-Folge über Palantir und Peter Thiel. Es sprechen Erzähler/in und als Gast "
    "Felix Holtermann (Handelsblatt). Themen sind der 11. September, die Gründung von "
    "Palantir, Alex Karp und Überwachung."
)
PARA2 = [
    "Nach dem 11. September 2001 sucht Peter Thiel nach einer Antwort auf das Versagen der Geheimdienste.",
    "Im Jahr 2004 gründet er mit Programmierern aus seiner Zeit bei PayPal die Firma Palantir.",
    "Das Startkapital kommt von Thiel selbst, der Rest von der CIA über In-Q-Tel.",
    "Alex Karp wird Chef und verkauft die Vision der Firma mit Habermas und Hegel im Gepäck.",
]
SECTIONS = {
    "Der 11. September als Auslöser": [
        "- Fast 3000 Menschen sterben bei den Anschlägen vom 11. September 2001",
        "- Der Untersuchungsbericht nennt 2004 das Versagen der Geheimdienste als Ursache",
    ],
    "Gründung von Palantir 2004": [
        "- Peter Thiel gründet Palantir 2004 mit Programmierern aus seiner PayPal-Zeit",
        "- Das Startkapital für Palantir kommt zu großen Teilen von Thiel selbst",
    ],
    "Alex Karp als Chef von Palantir": [
        "- Alex Karp spricht fast perfekt Deutsch und promovierte bei Habermas in Frankfurt",
        "- Karp erklärt die Mission von Palantir in Interviews gern mit deutschen Philosophen",
    ],
}
FACTS = {
    "f0": LintFact(0, "Peter Thiel gründet Palantir 2004", "Thiel gründet Palantir"),
    "f1": LintFact(60_000, "Fast 3000 Menschen sterben", "Fast 3000 Menschen sterben"),
    "f2": LintFact(120_000, "Der Bericht nennt das Versagen der Geheimdienste 2004", "Bericht"),
    "f3": LintFact(180_000, "Peter Thiel gründet Palantir 2004 mit PayPal-Leuten", "PayPal"),
    "f4": LintFact(240_000, "Das Startkapital für Palantir kommt von Thiel", "Startkapital"),
    "f5": LintFact(300_000, "Alex Karp spricht Deutsch, Habermas", "Karp Habermas Frankfurt"),
    "f6": LintFact(360_000, "Karp erklärt die Mission von Palantir", "Karp Mission"),
}
IDS = [("f1", "f2"), ("f3", "f4"), ("f5", "f6")]


def _overview(para1: str = PARA1, para2: list[str] | None = None) -> LintSection:
    sentences = PARA2 if para2 is None else para2
    lines = (
        LintLine(para1, "framing", ("f0",)),
        *(LintLine(t, "summary", ("f0",)) for t in sentences),
    )
    text = para1 + ("\n\n" + "\n".join(sentences) if sentences else "")
    return LintSection(roles.OVERVIEW_KEY, roles.SUMMARY, None, text, lines)


def _topic(title: str, bullets: list[str], ids: tuple[str, ...]) -> LintSection:
    lines = tuple(LintLine(b, "bullet", (ids[n % len(ids)],)) for n, b in enumerate(bullets))
    return LintSection(f"gen:{title}", roles.TOPICS, title, "\n".join(bullets), lines)


def _note(**changes: object) -> list[LintSection]:
    sections = dict(SECTIONS)
    sections.update(changes.pop("sections", {}))  # type: ignore[arg-type]
    out = [changes.pop("overview", None) or _overview()]
    for n, (title, bullets) in enumerate(sections.items()):
        out.append(_topic(title, bullets, IDS[n % len(IDS)]))
    return out  # type: ignore[return-value]


def _rules(sections: list[LintSection], minutes: float = 10, **kw: object) -> dict[str, int]:
    return doclint.lint(
        sections,
        language=kw.pop("language", "de"),  # type: ignore[arg-type]
        speech_ms=int(minutes * MIN),
        recording_type=kw.pop("recording_type", "podcast_broadcast"),  # type: ignore[arg-type]
        facts=kw.pop("facts", FACTS),  # type: ignore[arg-type]
        known=KNOWN,
        **kw,  # type: ignore[arg-type]
    ).by_rule()


def test_a_note_that_meets_the_standard_has_no_findings() -> None:
    assert _rules(_note()) == {}


def test_every_rule_has_a_taxonomy_code() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "scripts" / "eval" / "taxonomy.py"
    spec = importlib.util.spec_from_file_location("taxonomy", path)
    assert spec and spec.loader
    taxonomy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(taxonomy)
    assert set(doclint.RULES.values()) <= set(taxonomy.CODES)


def test_section_count_follows_the_length_of_the_recording() -> None:
    assert doclint.target_sections(10) == 3
    assert doclint.target_sections(30) == 8
    assert doclint.target_sections(60) == 8
    # 30 minutes: 6–8 sections; three is too few.
    found = _rules(_note(), minutes=30)
    assert found["too_few_sections"] == 1


# §1
@pytest.mark.parametrize(
    ("title", "rule"),
    [
        ("Palantir", "title_length"),
        ("Meeting notes — 2026-09-26 und noch etwas mehr Text", "title_generic"),
        ("Palantir: Thiel: Karp: die Anfänge der Datenanalyse", "title_colons"),
        ("Palantir und Palantir: Gründung und die Anfänge 2004", "title_repeats"),
        ("Palantir-Gründung: Peter Thiel und Elon Musk im Jahr 2004", "title_unsupported_name"),
    ],
)
def test_title(title: str, rule: str) -> None:
    assert rule in _rules(_note(), title=title)


def test_a_good_title() -> None:
    title = "Palantir-Gründung: Peter Thiel, 9/11 und die Anfänge der Datenanalyse"
    assert _rules(_note(), title=title) == {}


# §2
def test_orientation() -> None:
    assert _rules(_note(overview=_overview(para1="Podcast-Folge.")))["paragraph1_length"] == 1
    assert _rules(_note(overview=_overview(para2=[])))["paragraph2_missing"] == 1
    short = _rules(_note(overview=_overview(para2=PARA2[:2])))
    assert short["paragraph2_length"] == 1 and short["paragraph2_sentences"] == 1
    listed = _overview(para2=[*PARA2[:3], "- Palantir wird 2004 gegründet"])
    assert _rules(_note(overview=listed))["overview_list"] == 1


# §3
def test_sections() -> None:
    thin = {"Gründung von Palantir 2004": SECTIONS["Gründung von Palantir 2004"][:1]}
    assert _rules(_note(sections=thin))["thin_section"] == 1
    many = [
        f"- Palantir stellt im Jahr {2004 + n} weitere {n + 10} Programmierer ein" for n in range(7)
    ]
    assert _rules(_note(sections={"Gründung von Palantir 2004": many}))["long_section"] == 1


def test_order_and_interleaving() -> None:
    sections = _note()
    late_first = [sections[0], sections[2], sections[1], sections[3]]
    assert _rules(late_first)["out_of_order"] == 1
    mixed = [
        sections[0],
        _topic(
            "Der 11. September als Auslöser",
            SECTIONS["Der 11. September als Auslöser"],
            ("f1", "f4"),
        ),
        _topic("Gründung von Palantir 2004", SECTIONS["Gründung von Palantir 2004"], ("f3", "f5")),
        sections[3],
    ]
    assert _rules(mixed)["interleaved"] == 1


# §4
@pytest.mark.parametrize(
    ("title", "rule"),
    [
        ("Einleitung", "heading_generic"),
        ("Wer gründet Palantir im Jahr 2004?", "heading_question"),
        ("GRÜNDUNG VON PALANTIR 2004", "heading_all_caps"),
        ("Palantir", "heading_length"),
        ("Gründung von Palantir 2004:", "heading_punctuation"),
        ("Gründung von Palantir durch Elon Musk", "heading_unsupported_name"),
    ],
)
def test_headings(title: str, rule: str) -> None:
    sections = _note()
    old = sections[2]
    sections[2] = dataclasses.replace(old, title=title)
    assert rule in _rules(sections)


def test_headings_that_say_the_same() -> None:
    sections = _note()
    sections[3] = dataclasses.replace(sections[3], title="Die Gründung von Palantir 2004")
    assert _rules(sections)["heading_overlap"] == 1
    title = "Die Gründung von Palantir 2004 durch Peter Thiel"
    assert "heading_restates_title" in _rules(_note(), title=title)
    # Sharing words is not restating: "2004" is not in this title.
    good = "Palantir-Gründung: Peter Thiel, 9/11 und die Anfänge der Datenanalyse"
    assert "heading_restates_title" not in _rules(_note(), title=good)


def test_a_chapter_heading_is_a_time_and_a_name() -> None:
    sections = _note()
    sections[1] = dataclasses.replace(sections[1], title="00:34 — Palantir")
    assert "heading_length" not in _rules(sections)


# §5
@pytest.mark.parametrize(
    ("bullet", "rule"),
    [
        ("- Palantir 2004", "bullet_length"),
        ("- Es gibt sehr viel Zustimmung für die neue Politik der Regierung", "bullet_unspecific"),
        (
            "- Er gründet Palantir im Jahr 2004 mit Programmierern aus seiner Zeit",
            "bullet_pronoun_subject",
        ),
        (
            "- Speaker 1 sagt, Palantir sei im Jahr 2004 gegründet worden, mit Geld",
            "label_in_prose",
        ),
        (
            "- Wir gründen Palantir im Jahr 2004 mit Programmierern aus der PayPal-Zeit",
            "first_person",
        ),
        (
            "- Ein riesiger Feuerball entsteht über den Wolkenkratzern der Stadt",
            "bullet_descriptive",
        ),
    ],
)
def test_bullets(bullet: str, rule: str) -> None:
    changed = {"Gründung von Palantir 2004": [bullet, SECTIONS["Gründung von Palantir 2004"][1]]}
    assert rule in _rules(_note(sections=changed))


def test_a_bullet_that_is_its_quote_is_a_copy() -> None:
    line = "- Fast 3000 Menschen sterben"
    changed = {
        "Der 11. September als Auslöser": [line, SECTIONS["Der 11. September als Auslöser"][1]]
    }
    assert _rules(_note(sections=changed))["bullet_copy"] == 1


# §6
def test_sub_bullets() -> None:
    parent = SECTIONS["Gründung von Palantir 2004"][0]
    kids = [f"  - Programmierer Nummer {n} kommt von PayPal nach Palo Alto" for n in range(4)]
    section = _topic(
        "Gründung von Palantir 2004",
        [parent, *kids, SECTIONS["Gründung von Palantir 2004"][1]],
        ("f3",),
    )
    section = dataclasses.replace(
        section,
        lines=tuple(
            dataclasses.replace(ln, child=ln.text.startswith("  ")) for ln in section.lines
        ),
    )
    sections = _note()
    sections[2] = section
    assert _rules(sections)["too_many_children"] == 1
    restated = dataclasses.replace(
        section,
        lines=(
            section.lines[0],
            LintLine(
                "  - Peter Thiel gründet Palantir 2004 mit Programmierern",
                "bullet",
                ("f3",),
                child=True,
            ),
            section.lines[-1],
        ),
    )
    sections[2] = restated
    assert _rules(sections)["child_restates_parent"] == 1


# §7
def test_volume_band_is_eight_to_eighteen_words_per_minute() -> None:
    assert _rules(_note(), minutes=40)["volume_low"] == 1
    assert _rules(_note(), minutes=3)["volume_high"] == 1


def test_redundancy_and_references() -> None:
    same = SECTIONS["Gründung von Palantir 2004"][0]
    changed = {
        "Alex Karp als Chef von Palantir": [same, SECTIONS["Alex Karp als Chef von Palantir"][1]]
    }
    assert _rules(_note(sections=changed))["redundancy"] == 1
    sections = _note()
    sections[1] = dataclasses.replace(
        sections[1], lines=tuple(dataclasses.replace(ln, fact_ids=()) for ln in sections[1].lines)
    )
    assert _rules(sections)["uncited_line"] == 2


def test_a_table_belongs_to_a_demo_or_a_lecture() -> None:
    rows = ("| Größe | Wert |", "|---|---|", "| Mitarbeiter | 3000 |")
    table = LintSection(
        "gen:t",
        roles.TOPICS,
        None,
        "\n".join(rows),
        (
            LintLine(rows[0], "heading"),
            LintLine(rows[1], "heading"),
            LintLine(rows[2], "figure", ("f1",)),
        ),
    )
    assert "table_misplaced" in _rules([*_note(), table])
    assert "table_misplaced" not in _rules([*_note(), table], recording_type="presentation_demo")


# repair
def test_repair_drops_uncited_lines_and_heading_punctuation() -> None:
    section = render.RenderedSection(
        section_key="gen:x",
        role=roles.TOPICS,
        text="- cited 2004\n- not cited",
        title="Gründung:",
        lines=(
            render.Line("- cited 2004", "bullet", ("f1",)),
            render.Line("- not cited", "bullet"),
        ),
    )
    empty = render.RenderedSection(
        section_key="gen:y", role=roles.TOPICS, text="- nothing", title="Leer",
        lines=(render.Line("- nothing", "bullet"),),
    )  # fmt: skip
    fixed, counts = doclint.repair([section, empty])
    assert counts == {"uncited_dropped": 2, "heading_punctuation_stripped": 1}
    [only] = fixed
    assert only.title == "Gründung"  # type: ignore[attr-defined]
    assert only.text == "- cited 2004"  # type: ignore[attr-defined]


def test_findings_carry_no_text() -> None:
    assert set(doclint.Finding.__slots__) == {"code", "rule", "section_key", "line"}


def test_the_pipeline_repairs_lints_and_records() -> None:
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
    assert set(document.stats["lint_rules"]) <= set(doclint.RULES)
    assert sum(document.stats["lint"].values()) == sum(document.stats["lint_rules"].values())
    assert set(document.stats["lint_repairs"]) == {
        "uncited_dropped",
        "heading_punctuation_stripped",
    }
    for section in document.sections:
        assert all(ln.fact_ids or ln.kind in ("heading", "note") for ln in section.lines)
