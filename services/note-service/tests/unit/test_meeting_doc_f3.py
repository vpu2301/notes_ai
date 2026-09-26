"""Sprint F3 — figures, presenter, contact.

T1 number words and the `figure` kind, T2 the specifications table, T3 the
presenter line, T4 the Contact section, the recording type and the family
wiring.
"""

from __future__ import annotations

import asyncio
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
