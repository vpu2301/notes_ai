"""Sprint F3 — figures, presenter, contact.

T1 number words and the `figure` kind, T2 the specifications table, T3 the
presenter line, T4 the Contact section, the recording type and the family
wiring.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from note_service.domain import client_view
from note_service.domain.action_items import ACTION_SECTION_KEYS
from note_service.domain.meeting_doc import (
    classify,
    numbers,
    pipeline,
    prompts,
    render,
    roles,
    schema,
    support,
    types,
    verify,
)
from note_service.domain.meeting_doc.verify import VerifiedFact
from note_service.domain.meeting_doc.windows import Turn, Window
from note_service.jobs.generate_note import line_row

from .meeting_doc_fakes import ScriptedProvider, as_result, step_of

DAY = date(2026, 9, 25)
ROLE_BY_KEY = {"decisions": roles.DECISIONS, "action_items": roles.ACTION_ITEMS}
BROADCAST = types.family_for_recording_type("presentation_demo")

# The shape of the 2026-09-25 walkthrough's figures: what was said, and what
# the table must say. Wording invented; values and qualifiers as spoken.
PARDO_FIGURES = [
    ("the length overall is sixty six feet", "length overall", "sixty six", "feet", "", "66 feet"),
    ("the beam is a little over eighteen and a half feet", "beam", "eighteen and a half", "feet",
     "a little over", "a little over 18.5 feet"),
    ("we carry just under three hundred gallons of water", "water capacity", "three hundred",
     "gallons", "just under", "just under 300 gallons"),
    ("the fuel tank takes about eight hundred gallons", "fuel capacity", "eight hundred",
     "gallons", "about", "about 800 gallons"),
    ("twin engines at nine hundred horsepower each", "engine power", "nine hundred",
     "horsepower", "", "900 horsepower"),
    ("she cruises at twenty eight knots", "cruising speed", "twenty eight", "knots", "",
     "28 knots"),
    ("top speed is up to thirty four knots", "top speed", "thirty four", "knots", "up to",
     "up to 34 knots"),
    ("there are three cabins below deck", "cabins", "three", "", "", "3"),
]  # fmt: skip


def _window(*texts: str, speaker: str = "Mitchell") -> Window:
    return Window(
        index=0,
        turns=tuple(
            Turn(i, "SPEAKER_1", speaker, t, i * 10_000, i * 10_000 + 9_000, line=i + 1)
            for i, t in enumerate(texts)
        ),
    )


def _figure_fact(quote: str, name: str, value: str, unit: str, qualifier: str, turn: int = 1):
    return schema.Fact(
        kind=schema.FIGURE,
        text=f"The {name} is {qualifier} {value} {unit}".replace("  ", " "),
        quote=quote,
        turn=turn,
        name=name,
        value=value,
        unit=unit,
        qualifier=qualifier or None,
    )


def _verify(facts: list[schema.Fact], window: Window, **kw: Any) -> list[VerifiedFact]:
    return verify.verify_facts(
        facts,
        window=window,
        meeting_date=DAY,
        allowed_kinds=frozenset(
            {*schema.FACT_KINDS, schema.FIGURE, schema.INTRODUCTION, schema.NEXT_STEP}
        ),
        **kw,
    )


def _pardo_figures() -> list[VerifiedFact]:
    window = _window(*(q for q, *_ in PARDO_FIGURES))
    return _verify(
        [
            _figure_fact(q, n, v, u, ql, turn=i + 1)
            for i, (q, n, v, u, ql, _w) in enumerate(PARDO_FIGURES)
        ],
        window,
    )


# ── T1: number words and the figure kind ────────────────────────────


@pytest.mark.parametrize(
    ("text", "language", "value"),
    [
        ("eighteen and a half", "en", "18.5"),
        ("eighteen point five", "en", "18.5"),
        ("two thousand five hundred", "en", "2500"),
        ("achthundert Liter", "de", "800"),
        ("achtzehneinhalb", "de", "18.5"),
        ("вісімнадцять з половиною", "uk", "18.5"),
        ("півтора", "uk", "1.5"),
        ("1,200", "en", "1200"),
        ("18,5", "de", "18.5"),
    ],
)
def test_numbers_are_read_as_digits_and_as_words(text: str, language: str, value: str) -> None:
    assert numbers.numbers_in(text, language) == [Decimal(value)]


def test_the_eight_walkthrough_figures_verify_with_their_qualifiers() -> None:
    kept = _pardo_figures()
    assert len(kept) == 8
    assert [f.figure.value_text for f in kept] == [w for *_, w in PARDO_FIGURES]


def test_a_figure_whose_value_was_not_said_is_dropped() -> None:
    stats = verify.VerifyStats()
    quote = "the beam is a little over eighteen and a half feet"
    assert (
        _verify([_figure_fact(quote, "beam", "19", "feet", "")], _window(quote), stats=stats) == []
    )
    assert stats.figures_dropped_value == 1


def test_a_figure_whose_unit_was_not_said_is_dropped() -> None:
    stats = verify.VerifyStats()
    quote = "we carry just under three hundred gallons of water"
    out = _verify([_figure_fact(quote, "water", "300", "litres", "")], _window(quote), stats=stats)
    assert out == [] and stats.figures_dropped_unit == 1


def test_a_qualifier_that_was_not_said_is_cleared() -> None:
    stats = verify.VerifyStats()
    quote = "we carry just under three hundred gallons of water"
    [fact] = _verify(
        [_figure_fact(quote, "water", "300", "gallons", "roughly")], _window(quote), stats=stats
    )
    assert fact.figure.qualifier == "" and stats.qualifiers_cleared == 1


def test_a_german_figure_in_words() -> None:
    quote = "der Wassertank fasst achthundert Liter"
    fact = schema.Fact(
        kind=schema.FIGURE, text="Wassertank: 800 l", quote=quote, turn=1,
        name="Wassertank", value="achthundert", unit="l",
    )  # fmt: skip
    [kept] = _verify([fact], _window(quote), language="de")
    assert kept.figure.value_text == "800 l"


def test_a_number_said_in_words_is_not_unverified() -> None:
    quote = "the beam is a little over eighteen and a half feet"
    window = _window(quote)
    text, flags = verify.check_numbers("The beam is 18.5 feet", quote=quote, turn=window.turns[0])
    assert text == "The beam is 18.5 feet" and flags == []


def test_the_schema_offers_figure_fields_only_to_families_with_figures() -> None:
    offered = tuple(types.fact_kinds(BROADCAST))
    props = schema.extract_schema(offered)["properties"]["facts"]["items"]["properties"]
    assert {"name", "value", "unit", "qualifier", "role", "organisation"} <= set(props)
    plain = schema.extract_schema(("key_point", "action"))["properties"]["facts"]["items"][
        "properties"
    ]
    assert "value" not in plain and "role" not in plain


# ── T2: the specifications table ────────────────────────────────────


def test_eight_figures_are_one_table_with_a_source_per_row() -> None:
    figures = _pardo_figures()
    sections = render.render_sections(
        figures, role_by_key=ROLE_BY_KEY, kind_roles=types.fact_kinds(BROADCAST)
    )
    [spec] = [s for s in sections if s.role == roles.SPECIFICATIONS]
    assert spec.section_key == "specifications" and spec.title == "Specifications"
    rows = spec.text.splitlines()
    assert rows[:2] == ["| Quantity | Value |", "|---|---|"]
    assert rows[2] == "| Length overall | 66 feet |"
    assert rows[4] == "| Water capacity | just under 300 gallons |"
    assert len(rows) == 10
    figure_lines = [line for line in spec.lines if line.kind == "figure"]
    assert len(figure_lines) == 8 and all(line.fact_ids for line in figure_lines)
    by_id = {f.item_key: f for f in figures}
    row = line_row(figure_lines[1], spec.section_key, "written", by_id)
    assert row is not None and row["kind"] == "figure"
    assert row["payload"] == {
        "name": "Beam",
        "value": "18.5",
        "unit": "feet",
        "qualifier": "a little over",
    }
    assert (
        line_row(spec.lines[0], spec.section_key, "written", by_id) is None
    )  # the head cites nothing


def test_two_figures_are_bullets() -> None:
    figures = _pardo_figures()[:2]
    [spec] = [
        s
        for s in render.render_sections(figures, role_by_key=ROLE_BY_KEY)
        if s.role == roles.SPECIFICATIONS
    ]
    assert spec.text.splitlines() == [
        "- Length overall: 66 feet",
        "- Beam: a little over 18.5 feet",
    ]


def test_a_duplicate_merges_and_a_conflict_shows_both_flagged() -> None:
    quotes = [
        "the fuel tank takes about eight hundred gallons",
        "again the fuel tank is eight hundred gallons",
        "sorry the fuel tank is actually seven hundred gallons",
        "she cruises at twenty eight knots",
    ]
    facts = _verify(
        [
            _figure_fact(quotes[0], "fuel capacity", "800", "gallons", "about", turn=1),
            _figure_fact(quotes[1], "fuel capacity", "800", "gallons", "", turn=2),
            _figure_fact(quotes[2], "fuel capacity", "700", "gallons", "", turn=3),
            _figure_fact(quotes[3], "cruising speed", "28", "knots", "", turn=4),
        ],
        _window(*quotes),
    )
    [spec] = [
        s
        for s in render.render_sections(facts, role_by_key=ROLE_BY_KEY)
        if s.role == roles.SPECIFICATIONS
    ]
    rows = [line for line in spec.lines if line.kind == "figure"]
    assert [line.text for line in rows] == [
        "| Fuel capacity | about 800 gallons |",
        "| Fuel capacity | 700 gallons |",
        "| Cruising speed | 28 knots |",
    ]
    assert len(rows[0].fact_ids) == 2  # the repeat is a second source, not a second row
    by_id = {f.item_key: f for f in facts}
    assert render.FIGURE_CONFLICT in by_id[rows[1].fact_ids[0]].flags
    assert render.FIGURE_CONFLICT not in by_id[rows[2].fact_ids[0]].flags


def test_a_table_in_a_topic_replaces_the_bullets_that_restate_its_figures() -> None:
    figures = _pardo_figures()
    extra = [
        VerifiedFact(kind="key_point", text=t, quote=f"so, {t.lower()}, and that was it", turn=0,
                     start_ms=s, end_ms=s + 1, speaker_label="SPEAKER_1", speaker_name="Mitchell")
        for t, s in (("The hull is laid up in one piece", 500_000), ("The yard is in Italy", 501_000),
                     ("The saloon has the galley aft", 900_000), ("The helm is forward", 901_000))
    ]  # fmt: skip
    ids = [f.item_key for f in figures]
    topics = [
        (
            "Build",
            [(extra[0].text, [extra[0].item_key]), (extra[1].text, [extra[1].item_key])],
            [extra[0].item_key],
        ),
        (
            "Dimensions and performance",
            [
                ("The boat is 66 feet long", [ids[0]]),
                ("Water capacity is under 300 gallons", [ids[2]]),
            ],
            ids,
        ),
        (
            "Layout",
            [(extra[2].text, [extra[2].item_key]), (extra[3].text, [extra[3].item_key])],
            [extra[2].item_key],
        ),
    ]
    sections = render.render_sections([*figures, *extra], role_by_key=ROLE_BY_KEY, topics=topics)
    assert not [s for s in sections if s.role == roles.SPECIFICATIONS]
    dims = next(s for s in sections if s.title == "Dimensions and performance")
    assert "The boat is 66 feet long" not in dims.text
    assert "| Length overall | 66 feet |" in dims.text


def test_no_action_item_is_read_from_a_table() -> None:
    assert "specifications" not in ACTION_SECTION_KEYS
    assert "call_to_action" not in ACTION_SECTION_KEYS
    assert roles.role_of("call_to_action") == roles.CONTACT
    assert roles.role_of("specifications") == roles.SPECIFICATIONS


def test_the_client_version_keeps_the_specifications() -> None:
    assert types.SPECIFICATIONS in client_view.CLIENT_ROLES


# ── T3: the presenter ───────────────────────────────────────────────

INTRO = (
    "my name is Mitchell. I am a broker with Springbrook Marine Group, the Pardo dealer for "
    "the Great Lakes"
)


def _intro(quote: str, **fields: Any) -> schema.Fact:
    return schema.Fact(kind=schema.INTRODUCTION, text="Introduction", quote=quote, turn=1, **fields)


def test_the_walkthrough_introduction_is_the_presenter_line() -> None:
    [fact] = _verify(
        [_intro(INTRO, name="Mitchell", role="a broker", organisation="Springbrook Marine Group",
                qualifier="Pardo dealer for the Great Lakes")],
        _window(INTRO),
    )  # fmt: skip
    sections = render.render_sections([fact], role_by_key=ROLE_BY_KEY, presenter_lines=True)
    assert sections[0].lines[0].text == (
        "Presenter: Mitchell, broker with Springbrook Marine Group (Pardo dealer for the Great Lakes)"
    )
    row = line_row(sections[0].lines[0], sections[0].section_key, "written", {fact.item_key: fact})
    assert row is not None and row["kind"] == "introduction"


def test_a_role_word_not_in_the_quote_is_cleared() -> None:
    stats = verify.VerifyStats()
    [fact] = _verify(
        [_intro(INTRO, name="Mitchell", role="sales director")], _window(INTRO), stats=stats
    )
    assert fact.person.role == "" and stats.introduction_fields_cleared == 1
    assert render.presenter_text(fact.person) == "Presenter: Mitchell"


def test_a_meeting_writes_no_presenter_line() -> None:
    [fact] = _verify([_intro(INTRO, name="Mitchell", role="broker")], _window(INTRO))
    sections = render.render_sections([fact], role_by_key=ROLE_BY_KEY, presenter_lines=False)
    assert all("Presenter" not in line.text for s in sections for line in s.lines)
    assert "introduction" not in types.fact_kinds(types.FALLBACK)


def test_somebody_else_introduced_is_introduced_not_the_presenter() -> None:
    quote = "and next to me this is Anna from sales who runs the sea trials"
    [fact] = _verify([_intro(quote, name="Anna", organisation="sales")], _window(quote))
    assert not fact.person.self_introduction
    assert render.presenter_text(fact.person) == "Introduced: Anna, sales"


def test_the_extractor_is_told_which_lines_introduce_somebody() -> None:
    window = _window("Welcome aboard everybody.", INTRO, "The hull is laid up in one piece.")
    assert pipeline.introduction_lines(window, []) == [2]
    assert pipeline.introduction_lines(window, ["the hull is laid up in one piece"]) == [2, 3]
    prompt = prompts.extract_prompt("x", "en", introduction_lines=[2])
    assert "[2] contain an introduction" in prompt


# ── T4: contact, recording type, family ─────────────────────────────


def test_a_call_to_action_is_the_contact_section() -> None:
    quote = "if you have any questions just shoot me an email or leave a comment below"
    stats = verify.VerifyStats()
    [fact] = _verify(
        [schema.Fact(kind=schema.NEXT_STEP, text="Questions go to the presenter by email or as a comment",
                     quote=quote, turn=1)],
        _window(quote),
        stats=stats,
    )  # fmt: skip
    assert fact.kind == schema.NEXT_STEP and stats.contact_steps == 1
    sections = render.render_sections(
        [fact], role_by_key=ROLE_BY_KEY, kind_roles=types.fact_kinds(BROADCAST)
    )
    [contact] = [s for s in sections if s.role == roles.CONTACT]
    assert contact.section_key == "call_to_action" and contact.title == "Contact"


def test_a_next_step_not_addressed_to_the_listener_is_a_plain_point() -> None:
    quote = "the next hull goes into the mould in the spring at the yard"
    [fact] = _verify(
        [
            schema.Fact(
                kind=schema.NEXT_STEP,
                text="The next hull is moulded in spring",
                quote=quote,
                turn=1,
            )
        ],
        _window(quote),
    )
    assert fact.kind == schema.KEY_POINT


def test_presentation_demo_is_a_broadcast_with_figures_presenter_and_contact() -> None:
    assert (
        "presentation_demo" in types.RECORDING_TYPES
        and "presentation_demo" in classify.OFFERED_ORDER
    )
    assert BROADCAST.meeting_type == "broadcast"
    kinds = types.fact_kinds(BROADCAST)
    assert kinds["figure"] == roles.SPECIFICATIONS and kinds["next_step"] == roles.CONTACT
    assert "introduction" in kinds and "action" not in kinds
    assert "figure" in types.fact_kinds(types.FALLBACK)  # every family verifies figures
    assert types.detected_value("presentation_demo") == "presentation_demo"


def test_the_classifier_can_answer_presentation_demo() -> None:
    provider = ScriptedProvider(
        overrides={"classify": lambda _f: {"recording_type": "presentation_demo"}}
    )
    got = asyncio.run(
        classify.classify(provider, head="x", language="en", speakers=1, minutes=12.0,
                          calendar_title=None, attendees=0)
    )  # fmt: skip
    assert got == ("presentation_demo", classify.SOURCE_CLASSIFIER)
    assert "presentation_demo" in prompts.classify_system("en")


class _Walkthrough(ScriptedProvider):
    """Extracts the walkthrough's figures, introduction and call to action
    from the lines it is shown; everything else is the scripted default."""

    async def complete(self, prompt: str, schema_: Any = None, **kw: Any):  # type: ignore[override]
        if step_of(schema_) != "extract":
            return await super().complete(prompt, schema_, **kw)
        self.calls.append(("extract", prompt, kw.get("system") or ""))
        facts: list[dict[str, Any]] = []
        for n, (quote, name, value, unit, qualifier, _w) in enumerate(PARDO_FIGURES, 2):
            if quote in prompt:
                facts.append({"kind": "figure", "text": f"{name} {value}", "quote": quote, "turn": n,
                              "name": name, "value": value, "unit": unit, "qualifier": qualifier or None,
                              "explicit": False})  # fmt: skip
        if INTRO in prompt:
            facts.append({"kind": "introduction", "text": "Mitchell introduces himself", "quote": INTRO,
                          "turn": 0, "name": "Mitchell", "role": "broker",
                          "organisation": "Springbrook Marine Group",
                          "qualifier": "Pardo dealer for the Great Lakes", "explicit": False})  # fmt: skip
        cta = "if you have any questions just shoot me an email or leave a comment below"
        if cta in prompt:
            facts.append({"kind": "next_step", "text": "Questions by email or comment", "quote": cta,
                          "turn": 10, "explicit": False})  # fmt: skip
        return type("A", (), {"text": json.dumps({"facts": facts, "noise": []})})()


def test_the_walkthrough_end_to_end() -> None:
    lines = [INTRO, "welcome aboard everybody this is the world debut", *(q for q, *_ in PARDO_FIGURES),
             "if you have any questions just shoot me an email or leave a comment below"]  # fmt: skip
    result = as_result({"language": "en", "transcript": [
        {"speaker": "SPEAKER_1", "t_start_ms": i * 10_000, "t_end_ms": i * 10_000 + 9_000, "text": t}
        for i, t in enumerate(lines)]})  # fmt: skip
    provider = _Walkthrough()
    document = asyncio.run(
        pipeline.run(
            result, provider=provider, role_by_key=ROLE_BY_KEY, meeting_date=DAY, family=BROADCAST
        )
    )
    first_extract = next(p for step, p, _s in provider.calls if step == "extract")
    assert "[0] contain an introduction" in first_extract
    text = "\n".join(s.text for s in document.sections)
    assert (
        "Presenter: Mitchell, broker with Springbrook Marine Group (Pardo dealer for the Great Lakes)"
        in text
    )
    assert "| Beam | a little over 18.5 feet |" in text
    assert any(s.role == roles.CONTACT for s in document.sections)
    assert document.stats["figures_kept"] == 8 and document.stats["introductions_kept"] == 1
    for section in document.sections:
        for line in section.lines:
            if line.kind in ("figure", "presenter", "next_step"):
                assert line.fact_ids, line.text


# ── F3 follow-ups from the first stack-model run ────────────────────


def test_a_figure_quoted_by_its_number_words_is_checked_against_its_line() -> None:
    line = "The beam is a little over sixteen and a half feet, which gives a wide saloon."
    fact = schema.Fact(
        kind=schema.FIGURE, text="beam", quote="sixteen and a half feet", turn=1,
        name="beam", value="sixteen and a half", unit="feet", qualifier="a little over",
    )  # fmt: skip
    [kept] = _verify([fact], _window(line))
    assert kept.figure.value_text == "a little over 16.5 feet"


def test_bare_figures_get_their_details_in_one_required_field_call() -> None:
    line = "We carry just under two hundred and fifty gallons of fresh water on board."
    extracted = schema.ExtractOut(
        facts=[
            schema.Fact(kind=schema.FIGURE, text="x", quote="two hundred and fifty gallons", turn=0)
        ]
    )
    window = Window(index=0, turns=(Turn(0, "SPEAKER_1", None, line, 0, 5_000, line=0),))
    seen: list[Any] = []

    def details(_facts: Any, system: str) -> dict[str, Any]:
        seen.append(system)
        return {"figures": [{"index": 1, "name": "fresh water", "value": "two hundred and fifty",
                             "unit": "gallons", "qualifier": "just under"}]}  # fmt: skip

    provider = ScriptedProvider(overrides={"figures": details})
    asked, _twins = asyncio.run(pipeline._figure_details(provider, window, extracted, "en"))
    assert asked == 1 and seen and "Never compute" in seen[0]
    schema_sent = provider.schemas[0]["properties"]["figures"]["items"]
    assert set(schema_sent["required"]) == {"index", "name", "value", "unit", "qualifier"}
    [kept] = _verify(extracted.facts, window)
    assert kept.figure.value_text == "just under 250 gallons"


def test_figures_with_their_fields_cost_no_extra_call() -> None:
    provider = ScriptedProvider()
    extracted = schema.ExtractOut(
        facts=[
            _figure_fact(
                "she cruises at twenty six knots", "cruising speed", "twenty six", "knots", ""
            )
        ]
    )
    assert asyncio.run(pipeline._figure_details(provider, _window("x"), extracted, "en")) == (0, [])
    assert provider.calls == []


def test_a_short_one_voice_presentation_is_not_a_voice_memo() -> None:
    def said(answer: str) -> tuple[str, str]:
        provider = ScriptedProvider(overrides={"classify": lambda _f: {"recording_type": answer}})
        return asyncio.run(
            classify.classify(provider, head="x", language="en", speakers=1, minutes=1.5,
                              calendar_title=None, attendees=0)
        )  # fmt: skip

    assert said("presentation_demo") == ("presentation_demo", classify.SOURCE_CLASSIFIER)
    assert said("podcast_broadcast") == ("voice_memo", classify.SOURCE_RULE)  # Q3 unchanged


def test_a_number_filed_as_a_key_point_becomes_a_figure_when_it_verifies() -> None:
    line = "The fuel tank takes about seven hundred gallons, so the range is serious."
    window = Window(index=0, turns=(Turn(0, "SPEAKER_1", None, line, 0, 5_000, line=0),))
    point = schema.Fact(kind="key_point", text="The fuel tank holds about seven hundred gallons",
                        quote="seven hundred gallons", turn=0)  # fmt: skip
    extracted = schema.ExtractOut(facts=[point])
    provider = ScriptedProvider(overrides={"figures": lambda _f: {"figures": [
        {"index": 1, "name": "fuel tank", "value": "seven hundred", "unit": "gallons", "qualifier": "about"}]}})  # fmt: skip
    asked, twins = asyncio.run(
        pipeline._figure_details(provider, window, extracted, "en", promote=True)
    )
    assert asked == 1 and len(twins) == 1 and len(extracted.facts) == 1
    kept = pipeline._without_figure_twins(_verify([*extracted.facts, *twins], window))
    assert [f.kind for f in kept] == ["figure"] and kept[0].figure.value_text == "about 700 gallons"


def test_a_product_named_in_a_welcome_is_not_an_introduction() -> None:
    line = "Good afternoon and welcome to the first showing of the Tessaline 58 here."
    fact = schema.Fact(kind=schema.INTRODUCTION, text="x", quote=line, turn=1, name="Tessaline 58")
    assert _verify([fact], _window(line)) == []


def test_a_short_introduction_quote_is_checked_against_its_line() -> None:
    line = "My name is Corvin Aldmere. I am a broker with Harbourline Yachts, the dealer."
    fact = schema.Fact(
        kind=schema.INTRODUCTION, text="x", quote="[1] Corvin Aldmere (00:07): is Corvin Aldmere",
        turn=1, name="Corvin Aldmere", role="broker", organisation="Harbourline Yachts",
    )  # fmt: skip
    [kept] = _verify([fact], _window(line))
    assert kept.person.self_introduction and kept.person.role == "broker"


def test_the_line_header_never_vouches_for_a_name() -> None:
    line = "Down below there are three cabins and two heads for the guests."
    fact = schema.Fact(
        kind=schema.INTRODUCTION, text="x", quote=f"[8] Corvin Aldmere (00:59): {line}", turn=1,
        name="Corvin Aldmere",
    )  # fmt: skip
    assert _verify([fact], _window(line)) == []


def test_the_qualifier_is_read_from_the_words_before_the_value() -> None:
    line = "The beam is a little over sixteen and a half feet, which gives a wide saloon."
    fact = schema.Fact(kind=schema.FIGURE, text="x", quote=line, turn=1, name="beam",
                       value="sixteen and a half", unit="feet")  # fmt: skip
    [kept] = _verify([fact], _window(line))
    assert kept.figure.qualifier == "a little over"


def test_small_topic_groups_pool_into_one_table_and_sentences_that_restate_them_go() -> None:
    figures = _pardo_figures()[:4]
    ids = [f.item_key for f in figures]
    topics = [
        ("Deck", [("Two points on deck", [ids[0]]), ("More on deck", [ids[1]])], ids[:2]),
        ("Water", [("Tank facts", [ids[2]]), ("Fuel facts", [ids[3]])], ids[2:]),
    ]
    sections = render.render_sections(
        figures, role_by_key=ROLE_BY_KEY, topics=topics,
        summary=[("The boat is 66 feet long.", [ids[0]])],
    )  # fmt: skip
    [spec] = [s for s in sections if s.role == roles.SPECIFICATIONS]
    assert sum(1 for line in spec.lines if line.kind == "figure") == 4
    assert all("66 feet long" not in line.text for s in sections for line in s.lines)


def test_a_call_to_action_nobody_stated_is_stated_once() -> None:
    line = "If you have any questions, just email me or leave a comment below this video."
    window = Window(index=0, turns=(Turn(0, "SPEAKER_1", None, line, 0, 5_000, line=0),))
    provider = ScriptedProvider(overrides={"steps": lambda _f: {"steps": [
        {"index": 1, "text": "Questions go to the presenter by email or as a comment below the video"}]}})  # fmt: skip
    made = asyncio.run(pipeline._contact_details(provider, window, [], "en", [0]))
    assert [f.kind for f in made] == ["next_step"] and made[0].quote == line
    [kept] = _verify(made, window)
    assert kept.kind == schema.NEXT_STEP and not kept.copied
    assert asyncio.run(pipeline._contact_details(provider, window, made, "en", [0])) == []


def test_a_number_inside_a_name_or_a_bare_year_is_not_a_figure() -> None:
    line = "The world debut of the Pardo 65 GT here in 2026 at the festival."
    model = schema.Fact(kind=schema.FIGURE, text="x", quote=line, turn=1, name="Pardo", value="65")
    year = schema.Fact(kind=schema.FIGURE, text="x", quote=line, turn=1, name="year", value="2026")
    assert _verify([model, year], _window(line)) == []


def test_a_line_with_a_number_that_no_fact_covers_is_asked_about() -> None:
    lines = ("Welcome aboard everybody.", "So length overall, we're at sixty six feet here.")
    window = _window(*lines)
    extracted = schema.ExtractOut(
        facts=[schema.Fact(kind="key_point", text="Welcome", quote=lines[0], turn=1)]
    )
    provider = ScriptedProvider(overrides={"figures": lambda _f: {"figures": [
        {"index": 1, "name": "length overall", "value": "sixty six", "unit": "feet", "qualifier": ""}]}})  # fmt: skip
    asked, twins = asyncio.run(
        pipeline._figure_details(provider, window, extracted, "en", promote=True)
    )
    assert asked == 1 and [t.quote for t in twins] == [lines[1]]
    [kept] = _verify(twins, window)
    assert kept.figure.value_text == "66 feet"


def test_the_presenter_qualifier_may_be_the_next_sentence_and_keeps_its_casing() -> None:
    lines = (
        "For those that don't know, my name is Mitchell, I'm a broker with Springbrook Marine Group.",
        "We are the Pardo dealer for all of the Great Lakes.",
    )
    fact = schema.Fact(kind=schema.INTRODUCTION, text="x", quote=lines[0], turn=1, name="Mitchell",
                       role="Broker", organisation="Springbrook Marine Group",
                       qualifier="Pardo dealer for the Great Lakes")  # fmt: skip
    [kept] = _verify([fact], _window(*lines))
    assert render.presenter_text(kept.person) == (
        "Presenter: Mitchell, broker with Springbrook Marine Group (Pardo dealer for the Great Lakes)"
    )


@pytest.mark.parametrize(
    ("line", "name", "value", "kept"),
    [
        (
            "is the standard IPS 1200s or the optional IPS 1350s on this boat",
            "engines",
            "1200",
            False,
        ),
        ("just like on a 52 gt, the centre part is submersible", "gt", "52", False),
    ],
)
def test_numbers_that_name_a_model_are_not_figures(
    line: str, name: str, value: str, kept: bool
) -> None:
    fact = schema.Fact(kind=schema.FIGURE, text="x", quote=line, turn=1, name=name, value=value)
    out = _verify([fact], _window(line))
    assert bool(out) is kept


def test_a_unit_said_but_not_taken_is_unit_lost_and_a_unit_taken_is_kept() -> None:
    line = "hull length again 65 feet your max beam is wide"
    stats = verify.VerifyStats()
    lost = schema.Fact(
        kind=schema.FIGURE, text="x", quote=line, turn=1, name="hull length", value="65"
    )
    assert (
        _verify([lost], _window(line), stats=stats) == [] and stats.figures_dropped_unit_lost == 1
    )
    taken = lost.model_copy(update={"unit": "feet"})
    [kept] = _verify([taken], _window(line))
    assert kept.figure.value_text == "65 feet"


def test_a_unit_is_not_a_quantity_name() -> None:
    line = "just under three hundred gallons here, you're drafting a little over five foot"
    fact = schema.Fact(
        kind=schema.FIGURE, text="x", quote=line, turn=1, name="gallons", value="three hundred"
    )
    assert _verify([fact], _window(line)) == []


def test_i_am_mid_sentence_is_the_speakers_voice() -> None:
    assert support.first_person("For those that don't know, my name is Mitchell, I am a broker.")
    assert not support.first_person("The broker is with Springbrook Marine Group.")


# ── F3 amendment (r03) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("line", "name", "value", "unit", "why"),
    [
        (
            "Zwanzig Jahre später ist die Firma an der Börse",
            "Zwanzig Jahre",
            "zwanzig",
            "Jahre",
            "name",
        ),
        ("Er gründet eine Software für Geheimdienste", "Software", "eine", "", "value"),
        ("Das Gespräch dauerte über zwei Stunden", "Gespräch", "zwei", "", "unit_lost"),
    ],
)
def test_the_r03_figures_are_not_figures(
    line: str, name: str, value: str, unit: str, why: str
) -> None:
    fact = schema.Fact(
        kind=schema.FIGURE, text="x", quote=line, turn=1, name=name, value=value, unit=unit or None
    )
    figure, reason = verify.verify_figure(fact, language="de", context=line)
    assert figure is None and reason == why


def test_a_distance_with_its_unit_is_a_figure_and_one_said_as_one_counts() -> None:
    line = "Das Büro liegt über viertausend Kilometer entfernt"
    fact = schema.Fact(kind=schema.FIGURE, text="x", quote=line, turn=1, name="Entfernung",
                       value="viertausend", unit="Kilometer", qualifier="über")  # fmt: skip
    figure, _why = verify.verify_figure(fact, language="de", context=line)
    assert figure is not None and figure.value_text == "über 4,000 Kilometer"
    one = "Es gab nur ein einziges Büro in der Stadt"
    fact = schema.Fact(
        kind=schema.FIGURE, text="x", quote=one, turn=1, name="Anzahl Büro", value="ein"
    )
    assert verify.verify_figure(fact, language="de", context=one)[0] is not None


def test_a_narrative_recording_writes_a_table_only_for_measured_quantities() -> None:
    figures = _pardo_figures()
    sections = render.render_sections(figures, role_by_key=ROLE_BY_KEY, figure_tables=False)
    assert [s for s in sections if s.role == roles.SPECIFICATIONS]  # ≥ 3, ≥ 2 names with units
    two = figures[:2]
    sections = render.render_sections(two, role_by_key=ROLE_BY_KEY, figure_tables=False)
    assert not [s for s in sections if s.role == roles.SPECIFICATIONS]


def _turn(i: int, label: str, text: str, start: int, end: int) -> Turn:
    return Turn(i, label, None, text, start, end)


def test_a_trailer_at_the_start_is_cut_as_an_advertisement() -> None:
    from note_service.domain.meeting_doc import windows

    turns = [
        _turn(0, "UNKNOWN", "Ich bin Chris Hansen von Dateline NBC.", 5_000, 9_000),
        _turn(1, "UNKNOWN", "Prime Time. Jetzt im Kino.", 9_000, 33_000),
        _turn(2, "SPEAKER_1", "Willkommen zu dieser Folge über Palantir.", 34_000, 40_000),
        _turn(3, "SPEAKER_1", "Heute geht es um Peter Thiel.", 40_000, 44_000),
    ]
    prepared = windows.prepare_turns(turns)
    assert prepared.adverts == [(5_000, 33_000)]
    assert prepared.turns[0].text.startswith("Willkommen")


def test_a_mid_roll_between_two_turns_of_one_speaker_is_cut() -> None:
    from note_service.domain.meeting_doc import windows

    turns = [
        _turn(0, "SPEAKER_1", "Wir sprechen über Palantir.", 200_000, 260_000),
        _turn(1, "SPEAKER_4", "Diese Folge wird unterstützt von einer Bank.", 261_000, 290_000),
        _turn(2, "SPEAKER_1", "Zurück zu Alex Karp.", 291_000, 330_000),
        _turn(3, "SPEAKER_1", "Er studierte in Frankfurt.", 330_000, 900_000),
    ]
    assert windows.advert_runs(turns) == [(1, 1)]


def test_a_micro_turn_inside_a_sentence_is_merged() -> None:
    from note_service.domain.meeting_doc import windows

    turns = [
        _turn(0, "SPEAKER_2", "Wie", 0, 800),
        _turn(1, "SPEAKER_1", "Kann", 800, 1_200),
        _turn(2, "SPEAKER_2", "man Terrorismus bekämpfen?", 1_200, 3_000),
        _turn(3, "SPEAKER_3", "Gute Frage", 3_000, 4_000),
        _turn(4, "SPEAKER_1", "Ja", 4_000, 4_500),
    ]
    merged, n = windows.merge_micro_turns(turns)
    assert n == 1 and merged[0].text == "Wie Kann man Terrorismus bekämpfen?"
    assert [t.speaker_label for t in merged] == ["SPEAKER_2", "SPEAKER_3", "SPEAKER_1"]


def _person(label: str, start: int) -> VerifiedFact:
    return VerifiedFact(
        kind=schema.INTRODUCTION, text="x", quote="x y z", turn=0, start_ms=start, end_ms=start + 1,
        speaker_label=label, speaker_name=None,
        person=verify.Person(name="Felix Holtermann", role="Büroleiter", organisation="Handelsblatt",
                             self_introduction=True, joiner="beim"),
    )  # fmt: skip


def test_a_guest_is_a_guest_and_a_trailer_voice_is_nobody() -> None:
    turns = (
        [_turn(i, "SPEAKER_1", "Erzählung", i * 10_000, i * 10_000 + 9_000) for i in range(10)]
        + [
            _turn(10 + i, "SPEAKER_3", "Antwort", 200_000 + i * 5_000, 204_000 + i * 5_000)
            for i in range(4)
        ]
        + [_turn(20, "SPEAKER_9", "Ich bin Chris Hansen. Jetzt im Kino.", 400_000, 405_000)]
    )
    assert pipeline.standing_of(_person("SPEAKER_3", 200_000), turns) == "guest"
    assert pipeline.standing_of(_person("SPEAKER_9", 400_000), turns) == "clip"
    assert pipeline.standing_of(_person("SPEAKER_1", 0), turns) == "presenter"
    guest = dataclasses.replace(_person("SPEAKER_3", 0).person, standing="guest")
    assert (
        render.presenter_text(guest, "de") == "Gast: Felix Holtermann, Büroleiter beim Handelsblatt"
    )
