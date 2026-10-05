"""Sprint D1 — the document linter (docs/eval/document-standard.md,
meeting_doc/doclint.py, ADR-0065). Tests follow the work order's tasks."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import date
from typing import Any

import pytest

from note_service.domain.meeting_doc import doclint, pipeline, roles, schema, support
from note_service.domain.meeting_doc.doclint import LintContext
from note_service.domain.meeting_doc.render import Line, RenderedSection
from note_service.domain.meeting_doc.verify import VerifiedFact

from .meeting_doc_fakes import REPO, ScriptedProvider, as_result, load_fixture

MIN = 60_000
FIXTURES = REPO / "tests" / "fixtures" / "meeting_doc" / "doclint"


def _fact(text: str, start_ms: int, quote: str | None = None, **kw: Any) -> VerifiedFact:
    return VerifiedFact(
        kind=kw.pop("kind", schema.KEY_POINT),
        text=text,
        # A quote that is not the text: the text restates it (F2).
        quote=quote or "so wurde es in dem Gespräch erzählt",
        turn=0,
        start_ms=start_ms,
        end_ms=start_ms + 1_000,
        speaker_label="SPEAKER_1",
        speaker_name=None,
        **kw,
    )


def _load(name: str) -> tuple[list[RenderedSection], LintContext, dict]:
    data = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
    facts = {f["id"]: _fact(f["text"], f["start_ms"], f["quote"]) for f in data["facts"]}
    key = {fid: f.item_key for fid, f in facts.items()}
    sections = doclint.as_rendered(
        data["sections"],
        [
            {**ln, "section_key": s["section_key"], "fact_ids": [key[i] for i in ln["fact_ids"]]}
            for s in data["sections"]
            for ln in s["lines"]
        ],
    )
    ctx = LintContext(
        language=data["language"],
        speech_ms=data["speech_ms"],
        recording_type=data["recording_type"],
        facts={f.item_key: f for f in facts.values()},
        brief=data["brief"],
    )
    return sections, ctx, data


def _rules(findings: list[doclint.Finding]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in findings:
        out.setdefault(f.rule, set()).add(f.detail)
    return out


# ── Acceptance 1: r03's notes as rendered documents ─────────────────


def test_r03_note_1_is_rejected_for_what_it_is() -> None:
    sections, ctx, data = _load("r03_note1")
    found = _rules(doclint.check(sections, ctx))
    for rule, detail in data["expect"].items():
        assert detail in found.get(rule, set()), (rule, found)


def test_r03_note_2_is_rejected_for_labels_type_guest_and_volume() -> None:
    sections, ctx, data = _load("r03_note2")
    findings = doclint.check(sections, ctx)
    found = _rules(findings)
    for rule, detail in data["expect"].items():
        assert detail in found.get(rule, set()), (rule, found)
    assert set(data["expect_p1"]) <= found["orient.p1"]
    # "Er ist genervt …" and "Speaker 1 ist genervt …": a pronoun and a label.
    subjects = {(f.code, f.detail) for f in findings if f.rule == "line.subject"}
    assert subjects == {("F-SUBJ", "pronoun"), ("D-LABEL", "label")}


def test_the_comparison_notes_structure_has_no_structural_finding() -> None:
    sections, ctx, _data = _load("r03_comparison")
    findings = doclint.check(sections, ctx)
    assert [f for f in findings if f.code == "D-STRUCT"] == []
    # Its six headings meet every heading rule.
    assert [f for f in findings if f.rule.startswith("heading.")] == []
    # It has no prose top: the standard's orientation is ours to add.
    assert "orient.present" in _rules(findings)


# ── T1 structure and volume ─────────────────────────────────────────


def _topic(title: str, facts: list[VerifiedFact], key: str | None = None) -> RenderedSection:
    lines = tuple(Line(f"- {f.text}", "bullet", (f.item_key,)) for f in facts)
    return RenderedSection(
        key or roles.generated_key(title), roles.TOPICS, "\n".join(ln.text for ln in lines),
        facts=tuple(facts), title=title, lines=lines,
    )  # fmt: skip


def _ctx(facts: list[VerifiedFact], minutes: float = 30, **kw: Any) -> LintContext:
    return LintContext(
        language=kw.pop("language", "de"),
        speech_ms=int(minutes * MIN),
        recording_type=kw.pop("recording_type", "podcast_broadcast"),
        facts={f.item_key: f for f in facts},
        **kw,
    )


PEOPLE = ["Peter Thiel", "Alex Karp", "Felix Holtermann", "Jürgen Habermas"]


CLAIMS = [
    "gründet {y} mit {k} Programmierern eine Firma in Palo Alto",
    "verkauft {y} Anteile im Wert von {k} Millionen Dollar an Investoren",
    "promoviert {y} nach {k} Jahren Forschung in Frankfurt",
    "berichtet {y} über {k} Verträge mit der amerikanischen Armee",
    "eröffnet {y} ein Büro mit {k} Angestellten in London",
    "kritisiert {y} öffentlich {k} Programme zur Überwachung",
    "reist {y} für {k} Wochen nach Washington zu Gesprächen",
    "schreibt {y} ein Buch mit {k} Kapiteln über Technologie",
    "leitet {y} eine Abteilung von {k} Analysten beim Militär",
    "gewinnt {y} einen Preis für {k} Patente zur Datenanalyse",
    "unterrichtet {y} an {k} Universitäten das Fach Philosophie",
    "kauft {y} insgesamt {k} Grundstücke in Neuseeland",
    "trifft {y} genau {k} Senatoren im amerikanischen Kongress",
    "gibt {y} rund {k} Interviews im deutschen Fernsehen",
    "spendet {y} etwa {k} Millionen an politische Kampagnen",
    "entwickelt {y} mit {k} Ingenieuren eine neue Plattform",
]


def _specific(n: int, start_ms: int) -> VerifiedFact:
    who = PEOPLE[n % len(PEOPLE)]
    claim = CLAIMS[n % len(CLAIMS)].format(y=1990 + n, k=n + 3)
    return _fact(f"{who} {claim}", start_ms)


def test_twelve_one_bullet_sections_merge_to_at_most_eight_of_two_or_more() -> None:
    facts = [_specific(n, n * 150_000) for n in range(12)]
    sections = [
        _topic(f"Thema {n}: {PEOPLE[n % 4]} im Jahr {1990 + n}", [f], f"gen:t{n}")
        for n, f in enumerate(facts)
    ]
    ctx = _ctx(facts)
    assert "sections.size" in _rules(doclint.check(sections, ctx))
    repaired, done = doclint.repair(sections, ctx)
    topics = [s for s in repaired if s.role == roles.TOPICS]
    assert 3 <= len(topics) <= 8
    assert all(doclint._points(s) >= 2 for s in topics)
    assert done["D-STRUCT"] >= 1


def test_sections_are_reordered_by_time_and_a_long_one_split_at_its_gap() -> None:
    early = [_specific(n, n * 20_000) for n in range(3)]
    late = [_specific(n + 3, 20 * MIN + n * 20_000) for n in range(3)]
    long_facts = [_specific(n + 6, 40 * MIN + n * 10_000) for n in range(4)] + [
        _specific(n + 10, 50 * MIN + n * 10_000) for n in range(4)
    ]
    sections = [
        _topic("Peter Thiel und die Idee", late),
        _topic("Gründung von Palantir", early),
        _topic("Alex Karp und Jürgen Habermas", long_facts),
    ]
    # 12 minutes of speech: three to five sections is the band.
    ctx = _ctx([*early, *late, *long_facts], minutes=12)
    repaired, _done = doclint.repair(sections, ctx)
    topics = [s for s in repaired if s.role == roles.TOPICS]
    assert topics[0].title == "Gründung von Palantir"
    assert len(topics) == 4 and all(2 <= doclint._points(s) <= 6 for s in topics)
    assert (topics[3].title or "").startswith("50:00")  # split at the 10-minute gap


def test_volume_below_the_floor_renders_more_specific_facts() -> None:
    shown = [_specific(n, n * 60_000) for n in range(4)]
    spare = [_specific(n + 4, n * 60_000 + 30_000) for n in range(12)]
    sections = [
        _topic("Palantir und Peter Thiel", shown[:2]),
        _topic("Alex Karp und Habermas", shown[2:]),
    ]
    ctx = _ctx([*shown, *spare], minutes=10)
    assert doclint.body_words(sections) < doclint.volume_band(10)[0]
    repaired, done = doclint.repair(sections, ctx)
    assert doclint.body_words(repaired) > doclint.body_words(sections)
    assert done["D-VOL"] >= 1


def test_volume_above_the_ceiling_drops_the_least_specific_never_below_two() -> None:
    facts = [_specific(n, n * 10_000) for n in range(6)]
    long = [
        dataclasses.replace(f, text=f.text + " " + " ".join(["und weitere Einzelheiten"] * 4))
        for f in facts
    ]
    sections = [
        _topic("Palantir und Peter Thiel", long[:3]),
        _topic("Alex Karp und Habermas", long[3:]),
    ]
    repaired, done = doclint.repair(sections, _ctx(long, minutes=3))
    assert all(doclint._points(s) >= 2 for s in repaired if s.role == roles.TOPICS)
    assert done["D-VOL"] >= 1


def test_a_duplicated_bullet_is_one() -> None:
    facts = [_specific(n, n * 10_000) for n in range(4)]
    twin = _fact(facts[0].text, 50_000, quote="anders gesagt")
    sections = [
        _topic("Palantir und Peter Thiel", [*facts[:2], twin]),
        _topic("Alex Karp und Habermas", facts[2:]),
    ]
    repaired, done = doclint.repair(sections, _ctx([*facts, twin], minutes=2))
    texts = [ln.text for s in repaired for ln in s.lines]
    assert texts.count(f"- {facts[0].text}") == 1
    # SQ3: the composed ladder repeats the bullets and goes too (also D-RED).
    assert done["D-RED"] >= 1


# ── T2 headings and title ───────────────────────────────────────────


def test_diskussion_fails_generic_and_caps_and_takes_the_fallback() -> None:
    facts = [_specific(n, (3 + n) * MIN) for n in range(3)]
    ctx = _ctx(facts, minutes=3)
    generic = _topic("DISKUSSION", facts)
    found = _rules(doclint.check([generic], ctx))
    assert "generic" in found["heading.generic"]
    [fixed] = [s for s in doclint.repair([generic], ctx)[0] if s.role == roles.TOPICS]
    assert (fixed.title or "").startswith("03:00 — ")
    caps = _topic("DISKUSSION ÜBER DIE GRÜNDUNG", facts)
    assert "caps" in _rules(doclint.check([caps], ctx))["heading.form"]
    [recased] = [s for s in doclint.repair([caps], ctx)[0] if s.role == roles.TOPICS]
    assert recased.title == "Diskussion über die Gründung"


def test_a_repeated_phrase_in_a_title() -> None:
    ctx = _ctx([], minutes=3, language="en")
    assert "repeat" in doclint.title_faults("Pardo 65 GT Pardo 65 GT world debut in Cannes", ctx)
    ok = "Pardo 65 GT walkthrough: specifications and the Great Lakes dealer"
    assert doclint.title_faults(ok, ctx) == []


def test_a_heading_naming_a_person_absent_from_its_section_fails() -> None:
    facts = [_specific(0, 0), _specific(4, 60_000)]  # Peter Thiel twice
    section = _topic("Peter Thiel und Elon Musk", facts)
    found = _rules(doclint.check([section], _ctx(facts, minutes=3)))
    assert found["heading.nouns"] == {"name"}


def test_the_six_comparison_headings_pass() -> None:
    sections, ctx, _data = _load("r03_comparison")
    for s in sections:
        assert doclint.heading_faults(s.title or "") == [], s.title
    assert not [f for f in doclint.check(sections, ctx) if f.rule.startswith("heading.")]


# ── T3 lines ────────────────────────────────────────────────────────


def test_a_label_as_subject_is_not_rendered_and_goes_to_d2_once() -> None:
    fact = _fact("Thiel muss am Flughafen die Schuhe ausziehen", 60_000)
    others = [_specific(n, (2 + n) * MIN) for n in range(3)]
    bad = Line(
        "- Speaker 1 ist genervt, dass er am Flughafen 2001 die Schuhe ausziehen muss",
        "bullet",
        (fact.item_key,),
    )
    section = _topic("Peter Thiel und die Idee", others)
    section = dataclasses.replace(section, lines=(bad, *section.lines))
    document = pipeline.DocumentResult(
        sections=[section],
        facts=[fact, *others],
        stats={"language": "de", "speech_ms": 3 * MIN, "recording_type": "podcast_broadcast"},
    )
    asked: list[list[doclint.RegenRequest]] = []

    async def hook(
        requests: list[doclint.RegenRequest], sections: list[RenderedSection]
    ) -> list[RenderedSection] | None:
        asked.append(requests)
        return None  # D2 could not do better: the fallback stands

    asyncio.run(doclint.enforce(document, regenerate=hook))
    [requests] = asked
    assert any(r.rule == "line.subject" and r.fact_ids == (fact.item_key,) for r in requests)
    assert all("Speaker 1" not in ln.text for s in document.sections for ln in s.lines)
    assert document.stats["lint"]["regenerated"] == 0


@pytest.mark.parametrize(
    ("text", "fault"),
    [
        (
            "- Alex Karp hatte einen ungewöhnlichen Lebenslauf für einen Tech-CEO",
            "line.descriptive",
        ),
        ("- Ein riesiger Feuerball entsteht über den Wolkenkratzern der Stadt", "line.descriptive"),
        ("- Es gibt sehr viel Zustimmung für die neue Politik", "line.specific"),
        ("- Er gründet Palantir im Jahr 2004 mit Programmierern", "line.subject"),
        ("- Wir gründen Palantir im Jahr 2004 mit Programmierern", "line.person"),
        ("- The goal is to instill fear in every single person in Silicon Valley", "line.language"),
        ("- 90 % Zustimmung für Bush", None),
        ("- Es gibt 3000 Tote bei den Anschlägen vom 11. September 2001", None),
    ],
)
def test_line_rules(text: str, fault: str | None) -> None:
    fact = _fact("irgendein Satz", 0, quote="völlig andere Worte hier")
    ctx = _ctx([fact], known=frozenset({"Alex", "Karp", "Bush", "Palantir"}))
    got = doclint.line_fault(Line(text, "bullet", (fact.item_key,)), ctx)
    assert (got[0] if got else None) == fault


def test_a_copy_and_an_uncited_line_are_not_rendered_and_a_glyph_is_stripped() -> None:
    fact = _fact("Peter Thiel gründet 2004 Palantir", 0, quote="Peter Thiel gründet 2004 Palantir")
    other = _specific(1, 30_000)
    lines = (
        Line("- Peter Thiel gründet 2004 Palantir", "bullet", (fact.item_key,)),  # the quote
        Line("- Alex Karp nennt 2004 genau 4 Gründe", "bullet"),  # no row
        Line(f"- {other.text} ❝", "bullet", (other.item_key,)),
        Line(
            "- Jürgen Habermas nennt 1995 genau 9 Gründe für Palantir", "bullet", (other.item_key,)
        ),
    )
    section = RenderedSection(
        "gen:x", roles.TOPICS, "", title="Palantir und Peter Thiel", lines=lines
    )
    repaired, done = doclint.repair([section], _ctx([fact, other], minutes=0.5))
    [fixed] = [s for s in repaired if s.role == roles.TOPICS]
    assert [ln.text for ln in fixed.lines][0] == f"- {other.text}"
    assert all("❝" not in ln.text and ln.fact_ids for ln in fixed.lines)
    assert done["F-COPY"] == 1 and done["D-REF"] == 1 and done["D-FORM"] == 1


def test_an_evaluation_of_a_person_is_descriptive_unless_a_claim_follows() -> None:
    assert support.descriptive("Alex Karp hatte einen ungewöhnlichen Lebenslauf", "de")
    assert not support.descriptive(
        "Karps Lebenslauf ist ungewöhnlich, weil er 2002 bei Habermas promovierte", "de"
    )
    assert not support.descriptive("Das Boot ist mit 20 Metern ungewöhnlich lang", "de")


# ── T4 orientation ──────────────────────────────────────────────────


def test_r03_note_2_first_paragraph_fails_length_label_and_guest() -> None:
    sections, ctx, _data = _load("r03_note2")
    first = [ln for ln in sections[0].lines if ln.kind == "framing"]
    assert {"length", "label", "guest"} <= set(doclint.p1_faults(first, ctx))


def test_a_compliant_first_paragraph_passes() -> None:
    fact = _fact(
        "Alex Karp leitet Palantir seit 2004", 0, quote="Palantir Felix Holtermann Handelsblatt"
    )
    ctx = _ctx(
        [fact],
        brief={
            "orientation": {
                "speakers": ["Erzähler/in"],
                "guests": ["Felix Holtermann (Handelsblatt)"],
            }
        },
    )
    text = (
        "Podcast-Folge über Palantir und die Anfänge der Datenanalyse nach 2001. Es sprechen "
        "Erzähler/in und als Gast Felix Holtermann (Handelsblatt). Themen sind der 11. September, "
        "die Gründung von Palantir, Alex Karp und Überwachung."
    )
    assert doclint.p1_faults([Line(text, "framing", (fact.item_key,))], ctx) == []


def test_the_type_word_is_mapped_to_the_classified_type() -> None:
    ctx = _ctx([], recording_type="podcast_broadcast")
    assert doclint.type_word_fault("Vortrag über Palantir.", ctx)
    assert doclint._map_type_word("Vortrag über Palantir.", ctx) == "Podcast-Folge über Palantir."
    assert doclint.type_word_fault("podcast_broadcast über Palantir.", ctx)
    assert not doclint.type_word_fault("Podcast-Folge über Palantir.", ctx)


def test_a_missing_second_paragraph_takes_the_composed_rung() -> None:
    facts = [_specific(n, n * MIN) for n in range(8)]
    framing = Line("Podcast-Folge über Palantir.", "framing", (facts[0].item_key,))
    top = RenderedSection(roles.OVERVIEW_KEY, roles.SUMMARY, framing.text, lines=(framing,))
    ctx = _ctx(facts, minutes=3, known=frozenset({"Peter", "Thiel", "Alex", "Karp", "Palantir"}))
    repaired, done = doclint.repair([top], ctx)
    summary = [ln for ln in repaired[0].lines if ln.kind == "summary"]
    assert len(summary) >= 3 and done["D-ORIENT"] >= 1


# ── T5 wiring, failure, one module ──────────────────────────────────


def test_a_linter_that_raises_leaves_the_document_and_says_so(monkeypatch: Any) -> None:
    document = pipeline.DocumentResult(sections=[], stats={"language": "de"})

    def boom(*_a: Any, **_k: Any) -> list[doclint.Finding]:
        raise RuntimeError("unexpected shape")

    monkeypatch.setattr(doclint, "check", boom)
    out = asyncio.run(doclint.enforce(document))
    assert out.stats["lint"] == {"error": True}


def test_findings_carry_no_text() -> None:
    assert set(doclint.Finding.__slots__) == {
        "rule", "code", "severity", "section_key", "line_index", "detail"
    }  # fmt: skip


def test_every_rule_code_is_a_taxonomy_code_with_its_severity() -> None:
    import importlib.util

    path = REPO / "scripts" / "eval" / "taxonomy.py"
    spec = importlib.util.spec_from_file_location("taxonomy", path)
    assert spec and spec.loader
    taxonomy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(taxonomy)
    for rule in doclint.RULES.values():
        assert rule.code in taxonomy.CODES and rule.code in doclint.SEVERITY
        assert doclint.SEVERITY[rule.code] == taxonomy.CODES[rule.code][1]


def test_production_and_eval_use_the_same_module() -> None:
    """Acceptance 3: the worker and the harness both call doclint.enforce."""
    root = REPO / "services" / "note-service" / "src" / "note_service"
    worker = (root / "jobs" / "generate_note.py").read_text("utf-8")
    harness = (REPO / "scripts" / "eval" / "notes_eval.py").read_text("utf-8")
    scorer = (REPO / "scripts" / "eval" / "notes_scoring.py").read_text("utf-8")
    assert "doclint.enforce(" in worker and "doclint.enforce(" in harness
    assert "meeting_doc import doclint" in scorer


def test_the_pipeline_output_is_enforced_and_recorded() -> None:
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
    assert "orientation" in document.brief
    asyncio.run(doclint.enforce(document))
    lint = document.stats["lint"]
    assert set(lint) >= {"findings_by_code", "repaired_by_code", "regenerated", "unresolved"}
    assert lint["regenerated"] == 0
    ctx = doclint.context_of(document)
    for section in document.sections:
        for line in section.lines:
            assert line.fact_ids or line.kind in ("heading", "note")
            assert doclint.line_fault(line, ctx) is None


def test_an_orientation_sentence_may_name_a_fact_but_not_repeat_its_bullet() -> None:
    """§2: paragraph 2 names the most specific facts, which the sections
    carry too. §7 / SQ3 T3: not in the same words — a sentence that says
    what a bullet says is redundancy, and the repair keeps one of them."""
    facts = [_specific(n, n * MIN) for n in range(4)]
    framing = Line("Podcast-Folge über Palantir.", "framing", (facts[0].item_key,))
    named = Line("Palantir entsteht 1990 aus einer kleinen Gründung.", "summary",
                 (facts[0].item_key,))  # fmt: skip
    top = RenderedSection(roles.OVERVIEW_KEY, roles.SUMMARY, "", lines=(framing, named))
    sections = [
        top,
        _topic("Palantir und Peter Thiel", facts[:2]),
        _topic("Alex Karp und Habermas", facts[2:]),
    ]
    assert "redundancy" not in _rules(doclint.check(sections, _ctx(facts, minutes=1)))
    repeated = Line(f"{facts[0].text}.", "summary", (facts[0].item_key,))
    sections[0] = RenderedSection(roles.OVERVIEW_KEY, roles.SUMMARY, "", lines=(framing, repeated))
    assert "orientation" in _rules(doclint.check(sections, _ctx(facts, minutes=1)))["redundancy"]
    repaired, _done = doclint.repair(sections, _ctx(facts, minutes=1))
    texts = [ln.text for s in repaired for ln in s.lines]
    assert sum(facts[0].text in t for t in texts) == 1
