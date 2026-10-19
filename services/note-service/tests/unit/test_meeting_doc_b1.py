"""B1 — every fallback meets the standard: rung 3 writes plain sentences with one
certainty clause, a chapter heading is the block's claim (no timestamp, no bare
name), a narrated recording carries no meeting furniture, paragraph 1 names the
medium and invents no year, attribution is grammatical.
"""

from __future__ import annotations

import re
from decimal import Decimal

from note_service.domain.meeting_doc import (
    compose,
    doclint,
    overview,
    render,
    roles,
    schema,
    support,
)
from note_service.domain.meeting_doc.doclint import LintContext
from note_service.domain.meeting_doc.render import Line, RenderedSection
from note_service.domain.meeting_doc.verify import Figure, VerifiedFact


def _vf(text: str, start_ms: int = 0, **kw: object) -> VerifiedFact:
    fields = {
        "kind": schema.KEY_POINT,
        "text": text,
        "quote": text,
        "turn": 0,
        "start_ms": start_ms,
        "end_ms": start_ms + 1_000,
        "speaker_label": "SPEAKER_1",
        "speaker_name": None,
    }
    fields.update(kw)
    return VerifiedFact(**fields)  # type: ignore[arg-type]


# ── T1 rung 3: plain sentences, one certainty clause ─────────────────


def test_composed_overview_is_plain_sentences_one_period_each() -> None:
    facts = [
        _vf("Die Midterm-Wahlen finden am 3. November statt", 0),
        _vf("Die Demokraten brauchen vier zusätzliche Senatssitze", 60_000),
        _vf("Die Republikaner haben in beiden Kammern eine knappe Mehrheit", 120_000),
    ]
    out = overview.composed_sentences(facts, language="de")
    assert len(out) == 3
    for sentence, ids in out:
        assert sentence[:1].isupper() and sentence.endswith(".") and not sentence.endswith("..")
        assert len(ids) == 1
    assert out[0][0] == "Die Midterm-Wahlen finden am 3. November statt."
    assert not any(s.startswith(("Zunächst", "Anschließend", "Schließlich")) for s, _i in out)


def test_a_proposal_with_a_holder_is_marked_once_as_a_clause() -> None:
    facts = [
        _vf("Die Rente mit 63 wird abgeschafft", 0, certainty="proposal", attributed_to="Söder"),
        _vf("Der Tankrabatt endet im Dezember", 60_000),
        _vf("Die PKV bleibt bestehen", 120_000),
    ]
    out = overview.composed_sentences(facts, language="de")
    first = out[0][0]
    assert first == "Die Rente mit 63 wird abgeschafft — laut Söder."
    assert first.count("laut") == 1 and "Vorschlag" not in first


def test_a_text_already_labelled_is_not_labelled_twice() -> None:
    facts = [
        _vf("Vorschlag — Die Rente mit 63 wird abgeschafft", 0, certainty="proposal"),
        _vf("Vorwurf: Die Behörde hat Akten vernichtet", 60_000, certainty="allegation"),
        _vf("Die PKV bleibt bestehen", 120_000),
    ]
    out = overview.composed_sentences(facts, language="de")
    assert out[0][0] == "Vorgeschlagen wurde, Die Rente mit 63 wird abgeschafft."
    assert out[1][0] == "Ein Vorwurf lautet, Die Behörde hat Akten vernichtet."
    for sentence, _ids in out[:2]:
        assert sentence.count("Vorschlag") + sentence.count("Vorwurf") <= 1
        assert "—" not in sentence  # no stacked label, no connective
        assert support.has_marker(sentence, "de")


def test_certainty_clauses_in_english_and_ukrainian() -> None:
    assert (
        support.certainty_clause("proposal", "The team moves the launch to June", "en")
        == "It was proposed that the team moves the launch to June"
    )
    assert (
        support.certainty_clause("estimate", "Costs reach 2 million", "en", actor="Reinbold")
        == "Costs reach 2 million — according to Reinbold"
    )
    assert (
        support.certainty_clause("proposal", "Команда переносить запуск", "uk")
        == "Запропоновано, що Команда переносить запуск"
    )
    # Every clause carries a word the line gate reads as a marker.
    for language, table in support.CERTAINTY_CLAUSES.items():
        for kind, template in table.items():
            assert support.has_marker(template.format(text="x"), language), (language, kind)
    # A sure fact, or one that already hedges, is returned as it is.
    assert support.certainty_clause("fact", "Die Wahl ist am 3. November", "de") == (
        "Die Wahl ist am 3. November"
    )
    assert support.certainty_clause("prediction", "Die Rente bleibt wahrscheinlich", "de") == (
        "Die Rente bleibt wahrscheinlich"
    )


# ── T2 chapter heading = the block's claim ─────────────────────────


def _trump_block(n: int) -> list[VerifiedFact]:
    texts = [
        [
            "Trump hat im September nur 32 Prozent Zustimmung",
            "Trump verliert bei Unabhängigen an Rückhalt",
            "Trump will den Iran-Krieg vor den Midterms beenden",
        ],
        [
            "Trump verspricht jedem Erwachsenen 5000 Dollar",
            "Trump knüpft die Zahlung an beide Kammern",
            "Trump nennt keine Finanzierung für das Versprechen",
        ],
        [
            "Trump verbreitet die Behauptung, die Briefwahl werde manipuliert",
            "Trump hat strengere Regeln für Wählerregister verfügt",
            "Trump lässt die Zertifizierung in Vermont prüfen",
        ],
    ][n]
    return [_vf(t, (n * 3 + k) * 60_000) for k, t in enumerate(texts)]


def test_three_chapters_about_one_name_get_three_different_claim_headings() -> None:
    known = frozenset({"Trump"})
    taken: list[str] = []
    for n in range(3):
        heading = compose.fallback_heading(_trump_block(n), "de", known, taken=taken)
        assert heading and heading != "Trump", heading
        assert not re.match(r"^\d{1,2}:\d{2}", heading)
        assert 3 <= len(heading.split()) <= 8
        assert heading.casefold() not in {t.casefold() for t in taken}
        taken.append(heading)
    assert len(set(taken)) == 3


def test_a_taken_heading_falls_to_the_blocks_next_fact() -> None:
    block = _trump_block(1)
    first = compose.fallback_heading(block, "de", frozenset({"Trump"}))
    second = compose.fallback_heading(block, "de", frozenset({"Trump"}), taken=[first])
    assert first != second and second != "Trump"


def test_a_heading_never_carries_a_timestamp_on_any_fixture_shape() -> None:
    short = [_vf("Es war still", 0), _vf("Niemand sprach", 1_000), _vf("Dann Pause", 2_000)]
    heading = compose.fallback_heading(short, "de", frozenset())
    # Facts under three words: the most named thing, else the stamp alone — never "mm:ss — Name".
    assert not re.match(r"^\d{1,2}:\d{2}\s*—", heading)
    assert support.noun_phrase("Trump", "de") == ""
    assert support.noun_phrase("Die Demokraten brauchen vier zusätzliche Senatssitze", "de") == (
        "Demokraten brauchen vier zusätzliche Senatssitze"
    )
    assert (
        support.noun_phrase(
            "Trump verbreitet die unbelegte Behauptung, die Briefwahl werde manipuliert", "de"
        )
        == "Trump verbreitet die unbelegte Behauptung"
    )


def test_chapter_rank_puts_a_fact_restating_the_framing_below_a_specific_new_one() -> None:
    framing = compose.framing_words(
        "de", "die US-Midterm-Wahlen", "", "der Kongress", "die Kontrolle des Präsidenten"
    )
    restates = _vf("Der Kongress kontrolliert den US-Präsidenten", 0)
    new = _vf("Die Republikaner haben in beiden Kammern eine knappe Mehrheit", 60_000)
    ranked = compose.chapter_rank([restates, new], "de", frozenset(), framing)
    assert ranked[0] is new
    assert compose.novelty(restates, "de", framing) == 0
    assert compose.novelty(new, "de", framing) == 1


def test_heading_distinct_ignores_the_chapter_stamp() -> None:
    facts = [_vf(f"Trump sagt Satz {n} über Wahlen", n * 60_000) for n in range(2)]
    sections = [
        RenderedSection(
            f"gen:t{n}",
            roles.TOPICS,
            "",
            title=f"0{n}:12 — Trump",
            lines=(Line(f"- {facts[n].text}", "bullet", (facts[n].item_key,)),),
            facts=(facts[n],),
        )
        for n in range(2)
    ]
    ctx = LintContext(language="de", speech_ms=600_000, facts={f.item_key: f for f in facts})
    findings = doclint._check_headings(sections, ctx)
    assert any(f.rule == "heading.distinct" for f in findings)


# ── T3 broadcast furniture ───────────────────────────────────────────


def _figure(name: str, value: str, unit: str, start_ms: int, **kw: object) -> VerifiedFact:
    return _vf(
        f"{name} {value} {unit}".strip(),
        start_ms,
        kind=schema.FIGURE,
        figure=Figure(name=name, value=Decimal(value), unit=unit),
        **kw,
    )


def _r02_figures() -> list[VerifiedFact]:
    return [
        _figure("Anzahl weiterer Videos", "2", "", 0),
        _figure("Vermont", "1", "", 10_000),
        _figure("Dollar an alle ausgezahlt", "5000", "Dollar", 20_000, certainty="proposal", attributed_to="Trump"),
        _figure("Dollar an alle versprochen", "5000", "Dollar", 30_000, certainty="proposal", attributed_to="Trump"),
        _figure("Zustimmung zu Trumps Arbeit", "32", "%", 40_000),
    ]  # fmt: skip


def _figure_lines(sections: list[RenderedSection]) -> list[str]:
    return [ln.text for s in sections for ln in s.lines if ln.kind == "figure"]


def test_a_broadcast_writes_only_cited_held_or_unit_figures_and_keeps_the_promise() -> None:
    figures = _r02_figures()
    cited = figures[4]
    topics = [
        (
            "Trumps Umfragetief",
            [("Nur 32 % Zustimmung im September", [cited.item_key])],
            [cited.item_key],
        )
    ]
    sections = render.render_sections(
        figures, role_by_key={}, topics=topics, language="de", family_type="broadcast",
        figure_tables=False,
    )  # fmt: skip
    written = "\n".join(_figure_lines(sections))
    assert "Anzahl weiterer Videos" not in written and "Vermont" not in written
    assert "ausgezahlt" not in written  # a promise never becomes a payout
    assert "versprochen" in written and "Dollar" in written  # held by Trump, hedge kept
    assert "Technische Daten" not in "\n".join(s.title or "" for s in sections)
    assert any(s.title == "Zahlen" for s in sections if s.role == roles.SPECIFICATIONS)


def test_a_broadcast_with_nothing_written_renders_no_figure_section() -> None:
    figures = _r02_figures()[:2]
    sections = render.render_sections(
        figures, role_by_key={}, language="de", family_type="broadcast", figure_tables=False
    )
    assert not [s for s in sections if s.role == roles.SPECIFICATIONS]


def test_a_meeting_family_renders_figures_exactly_as_before() -> None:
    figures = _r02_figures()
    before = render.render_sections(figures, role_by_key={}, language="de")
    after = render.render_sections(figures, role_by_key={}, language="de", family_type="auto")
    assert before == after


# ── T4 paragraph 1 ───────────────────────────────────────────────────


def test_overview_names_the_medium_never_a_podcast_by_default() -> None:
    assert overview.TYPE_LABELS["de"]["podcast_broadcast"] == "Sendung"
    assert "Podcast" not in overview.TYPE_LABELS["en"]["podcast_broadcast"]
    text = overview.first_paragraph(
        language="de", recording_type="podcast_broadcast", subject="die US-Midterm-Wahlen"
    )
    assert text.startswith("Sendung über die US-Midterm-Wahlen.")


def test_overview_drops_the_speaker_sentence_when_nobody_is_named() -> None:
    unnamed = overview.first_paragraph(
        language="de",
        recording_type="podcast_broadcast",
        subject="die US-Midterm-Wahlen",
        speakers=[overview.NARRATOR["de"]],
        themes=["Briefwahl"],
        named=False,
    )
    assert "Es sprechen" not in unnamed and "Erzähler" not in unnamed
    assert "Themen sind Briefwahl." in unnamed
    named = overview.first_paragraph(
        language="de",
        recording_type="podcast_broadcast",
        speakers=[overview.NARRATOR["de"]],
        guests=["Felix Holtermann"],
    )
    assert "Es sprechen Erzähler/in und als Gast Felix Holtermann." in named


def test_p1_orientation_year_is_stripped_unless_it_is_the_recordings() -> None:
    assert overview.strip_foreign_year("Analyse der US-Politik 2024", 2026) == (
        "Analyse der US-Politik",
        1,
    )
    assert overview.strip_foreign_year("Haushalt 2026", 2026) == ("Haushalt 2026", 0)
    assert overview.strip_foreign_year("Wahlen im Jahr 2024 in Texas", 2026) == (
        "Wahlen in Texas",
        1,
    )
    assert overview.strip_foreign_year("Analyse der US-Politik 2024", None) == (
        "Analyse der US-Politik 2024",
        0,
    )


def test_p1_lint_accepts_no_speaker_sentence_when_nobody_is_named() -> None:
    fact = _vf("Die Midterm-Wahlen finden am 3. November statt", 0)
    ctx = LintContext(
        language="de",
        speech_ms=600_000,
        recording_type="podcast_broadcast",
        facts={fact.item_key: fact},
        brief={"orientation": {"speakers": [], "guests": []}},
    )
    text = (
        "Sendung über die US-Midterm-Wahlen und die Macht des Kongresses. Themen sind "
        "die Briefwahl, der Senat und das Versprechen von 5000 Dollar."
    )
    assert "speakers" not in doclint.p1_faults([Line(text, "framing", (fact.item_key,))], ctx)


# ── T5 attribution grammar ───────────────────────────────────────────


def test_attribution_after_laut_takes_the_dative_for_roles_and_groups() -> None:
    assert support.according_to("politische Beobachter", "de") == "laut politischen Beobachtern"
    assert support.according_to("Experten", "de") == "laut Experten"
    assert support.according_to("die Regierung", "de") == "laut der Regierung"
    assert support.according_to("konservative Politiker", "de") == "laut konservativen Politikern"
    assert support.according_to("Angela Merkel", "de") == "laut Angela Merkel"
    assert support.according_to("Reinbold", "en") == "according to Reinbold"


def test_attribution_in_a_claim_line_is_grammatical() -> None:
    fact = _vf(
        "Die Wahl könnte knapp werden",
        0,
        certainty="opinion",
        attributed_to="politische Beobachter",
    )
    line = render.patch_claim("Die Wahl könnte knapp werden", [fact], "de")
    assert line.endswith("— laut politischen Beobachtern")
    assert "laut politische Beobachter" not in line
