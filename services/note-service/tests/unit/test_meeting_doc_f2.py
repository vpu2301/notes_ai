"""Sprint F2 — statements, not quotes.

T1 copies are evidence, T2 restate once per window, T3 no_information and
first_person in code, T4 sub-points, T5 nothing but text in section text.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from note_service import generation_metrics
from note_service.domain.meeting_doc import (
    pipeline,
    prompts,
    render,
    roles,
    schema,
    support,
    verify,
)
from note_service.domain.meeting_doc.verify import VerifiedFact
from note_service.domain.meeting_doc.windows import Turn, Window
from note_service.jobs.generate_note import line_row, uncited_rows

from .meeting_doc_fakes import (
    _TURN_LINE,
    ScriptedProvider,
    as_result,
    data_blocks,
    load_fixture,
    spoken,
    step_of,
)

DAY = date(2026, 9, 25)


def _window(*texts: str) -> Window:
    turns = tuple(
        Turn(i, "SPEAKER_1", "Mitchell", text, i * 10_000, i * 10_000 + 9_000, line=i + 1)
        for i, text in enumerate(texts)
    )
    return Window(index=0, turns=turns)


def _fact(text: str, quote: str, *, kind: str = schema.KEY_POINT, turn: int = 1) -> schema.Fact:
    return schema.Fact(kind=kind, text=text, quote=quote, turn=turn)


def _verify(facts: list[schema.Fact], window: Window, stats: verify.VerifyStats | None = None):
    return verify.verify_facts(facts, window=window, meeting_date=DAY, stats=stats)


def _vf(text: str, *, start_ms: int = 0, quote: str | None = None, **kw: Any) -> VerifiedFact:
    return VerifiedFact(
        kind=kw.pop("kind", schema.KEY_POINT),
        text=text,
        quote=quote if quote is not None else spoken(text),
        turn=0,
        start_ms=start_ms,
        end_ms=start_ms + 1_000,
        speaker_label="SPEAKER_1",
        speaker_name="Mitchell",
        **kw,
    )


def _all_lines(sections: list[render.RenderedSection]) -> list[str]:
    return [line.text for s in sections for line in s.lines]


ROLE_BY_KEY = {"decisions": roles.DECISIONS, "action_items": roles.ACTION_ITEMS}

# The shape of the 2026-09-25 note's bullets: sentences said at a boat show,
# each written into `text` exactly as it was said.
SHOW_TALK = [
    "This boat is incredible.",
    "Again this is a little bit of a crowded boat right now because the show has just opened.",
    "The platform at the back drops right down into the water so you can use it as a staircase.",
    "It is a hybrid between the seventy five and the fifty two in terms of the design.",
    "You have the fixed platform at the transom exactly like on the seventy five.",
    "And the centre section is submersible like on the fifty two which people love.",
    "The tender garage takes a three metre jet tender with room to spare.",
    "Down below there are three cabins and two heads for the owner and guests.",
]


# ── T1: copies are evidence ─────────────────────────────────────────


def test_quote_bullets_are_all_copied_and_none_is_rendered() -> None:
    window = _window(*SHOW_TALK)
    stats = verify.VerifyStats()
    kept = _verify([_fact(t, t, turn=i + 1) for i, t in enumerate(SHOW_TALK)], window, stats)
    # "This boat is incredible." informs nobody: dropped, not even evidence.
    assert len(kept) == len(SHOW_TALK) - 1 and stats.dropped_no_information == 1
    assert all(f.copied and verify.COPIED in f.flags for f in kept)
    assert stats.copied == len(kept)
    sections = render.render_sections(kept, role_by_key=ROLE_BY_KEY)
    assert _all_lines(sections) == []


def test_a_summary_sentence_citing_a_copied_fact_still_renders() -> None:
    copied = _vf(SHOW_TALK[2], quote=SHOW_TALK[2], copied=True)
    sentence = "The swim platform lowers into the water and doubles as a staircase."
    sections = render.render_sections(
        [copied], role_by_key=ROLE_BY_KEY, summary=[(sentence, [copied.item_key])]
    )
    [line] = [line for s in sections for line in s.lines]
    assert line.text == sentence and line.fact_ids == (copied.item_key,)
    row = line_row(line, "gen:overview", "written", {copied.item_key: copied})
    assert row is not None and row["quote"] == SHOW_TALK[2]


def test_a_decision_that_is_a_copy_is_downgraded_and_not_rendered() -> None:
    quote = "Agreed, we go with the blue hull for the show boat next year."
    window = Window(
        index=0,
        turns=(
            Turn(
                0,
                "SPEAKER_1",
                "Anna",
                "Shall we take the blue hull for the show boat?",
                0,
                5_000,
                line=1,
            ),
            Turn(1, "SPEAKER_2", "Tom", quote, 6_000, 9_000, line=2),
        ),
    )
    [fact] = _verify([_fact(quote, quote, kind=schema.DECISION, turn=2)], window)
    assert fact.kind == schema.KEY_POINT and fact.copied
    sections = render.render_sections([fact], role_by_key=ROLE_BY_KEY)
    assert _all_lines(sections) == []


def test_a_copy_is_stored_as_evidence_cited_or_not() -> None:
    copied = _vf(SHOW_TALK[6], quote=SHOW_TALK[6], copied=True)
    plain = _vf("The tender garage holds a three metre jet tender", start_ms=5_000)
    document = pipeline.DocumentResult(
        facts=[copied, plain],
        sections=render.render_sections(
            [copied, plain],
            role_by_key=ROLE_BY_KEY,
            summary=[("A three metre jet tender fits the garage.", [copied.item_key])],
        ),
    )
    placements = {row["text"]: row["placement"] for row in uncited_rows(document)}
    assert placements[copied.text] == "evidence"
    # No key-point list in the overview any more (F3 amendment §2.9): a
    # plain fact no line cites is a suggested row.
    assert placements[plain.text] == "suggested"


# ── T3: information and voice, in code ──────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind", "kept"),
    [
        ("This boat is incredible.", schema.KEY_POINT, False),
        ("The Pardo 65 GT hull length is 65 feet", schema.KEY_POINT, True),
        ("Show opens in about 30 minutes", schema.KEY_POINT, True),
        ("We should really update the deck", schema.ACTION, True),
    ],
)
def test_information_is_checked_in_code(text: str, kind: str, kept: bool) -> None:
    quote = f"so, well, as I was saying, {text.lower()} and that is where we are"
    window = _window(quote)
    out = _verify([_fact(text, quote, kind=kind)], window)
    assert bool(out) is kept
    if kept:
        assert verify.FIRST_PERSON not in out[0].flags


def test_a_first_person_line_is_evidence_only() -> None:
    quote = "OK so I'll put in here the exact size of the platform for you"
    [fact] = _verify([_fact("I'll put in here the exact size", quote)], _window(quote))
    assert verify.FIRST_PERSON in fact.flags and fact.evidence_only
    assert _all_lines(render.render_sections([fact], role_by_key=ROLE_BY_KEY)) == []


def test_a_leading_again_is_dropped_mechanically() -> None:
    quote = "again, the platform is basically a hybrid of both of those designs we saw"
    stats = verify.VerifyStats()
    [fact] = _verify(
        [_fact("Again, the platform is a hybrid of both designs", quote)], _window(quote), stats
    )
    assert fact.text == "The platform is a hybrid of both designs"
    assert stats.third_person_fixed == 1


def test_a_capitalised_name_on_the_evaluative_list_is_a_name() -> None:
    assert support.carries_information("Office in Nice", "en")
    assert not support.carries_information("Really nice", "en")


def test_the_gate_refuses_copies_chatter_and_first_person() -> None:
    fact = _vf("The platform lowers into the water", quote=SHOW_TALK[2])
    gate = pipeline._Gate()
    assert gate.reason(SHOW_TALK[2], [fact]) == "copied"
    assert gate.reason("Absolutely amazing.", [fact]) == "no_information"
    assert gate.reason("We lower the platform into the water.", [fact]) == "first_person"
    assert gate.reason("The platform lowers into the water.", [fact]) is None


def test_the_small_talk_shot_is_in_every_extract_prompt() -> None:
    for language in ("en", "de", "uk"):
        assert prompts.EXAMPLES[language]["shot_small_talk"] in prompts.extract_prompt(
            "x", language
        )
        assert "Quillhaven" in prompts.EXAMPLES[language]["shot_small_talk"]


# ── T2: restate once per window ─────────────────────────────────────


@dataclass
class _Restating:
    """Extract answers from the window: ``copies`` of the facts copy their
    turn into `text`; told to restate, every fact is restated. Everything
    else is the scripted default."""

    copies: int
    fail_restate: bool = False
    base: ScriptedProvider = field(default_factory=ScriptedProvider)
    extract_calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    backend: str = "scripted"
    model_id: str = "scripted"

    async def complete(
        self, prompt: str, schema_: Any = None, *, system: str | None = None, **kw: Any
    ):
        if step_of(schema_) != "extract":
            return await self.base.complete(prompt, schema_, system=system, **kw)
        self.extract_calls.append((system or "", schema_))
        restating = prompts.restate_suffix("en") in (system or "")
        if restating and self.fail_restate:
            raise RuntimeError("backend down")
        facts = []
        for body in data_blocks(prompt):
            for n, line in enumerate(body.splitlines()):
                match = _TURN_LINE.match(line)
                if not match:
                    continue
                said = match["text"]
                copy = not restating and n < self.copies
                text = said if copy else f"Point {n}: " + " ".join(said.split()[2:8])
                facts.append(
                    {"kind": "key_point", "text": text, "quote": said, "turn": int(match["turn"])}
                )
        return type("A", (), {"text": json.dumps({"facts": facts, "noise": []})})()


_SIX = [
    "the platform at the back lowers into the water for swimming",
    "the tender garage holds a three metre jet tender easily",
    "the saloon has the galley aft and the helm station forward",
    "the hull was laid up in one piece this spring in the yard",
    "there are three cabins and two heads below for the guests",
    "the centre section of the platform is submersible as well",
]


def _six_turn_result() -> dict[str, Any]:
    return as_result(
        {
            "language": "en",
            "transcript": [
                {
                    "speaker": "SPEAKER_1",
                    "t_start_ms": i * 10_000,
                    "t_end_ms": i * 10_000 + 9_000,
                    "text": t,
                }
                for i, t in enumerate(_SIX)
            ],
        }
    )


def _run(provider: Any) -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            _six_turn_result(), provider=provider, role_by_key=ROLE_BY_KEY, meeting_date=DAY
        )
    )


def test_a_window_of_copies_is_asked_once_more_with_the_rule_and_its_budget() -> None:
    provider = _Restating(copies=5)
    document = _run(provider)
    assert len(provider.extract_calls) == 2
    system, schema_ = provider.extract_calls[1]
    assert system.endswith(prompts.restate_suffix("en"))
    assert schema_["properties"]["facts"]["maxItems"] == 6
    assert document.stats["windows_restated"] == 1
    assert document.stats["restate_outcomes"] == {"improved": 1, "unchanged": 0}
    assert document.stats["facts_copied"] == 0
    assert not any(f.copied for f in document.facts)


def test_one_copy_is_enough_to_ask_and_none_is_never_asked() -> None:
    # Tuned from the work order's 40 %: a window of 3 copies in 8 went
    # unasked and lost its key facts (eval 2026-09-26, m04).
    provider = _Restating(copies=1)
    document = _run(provider)
    assert len(provider.extract_calls) == 2
    assert document.stats["restate_outcomes"] == {"improved": 1, "unchanged": 0}
    provider = _Restating(copies=0)
    document = _run(provider)
    assert len(provider.extract_calls) == 1
    assert document.stats["windows_restated"] == 0


def test_a_line_that_is_one_sentence_of_a_longer_quote_is_a_copy() -> None:
    quote = "Fine, extend the pricing test two weeks. Decision made."
    assert verify.is_copied("Extend the pricing test two weeks.", quote)
    assert not verify.is_copied("The pricing test runs two more weeks", quote)


def test_a_failed_restate_keeps_the_originals() -> None:
    provider = _Restating(copies=5, fail_restate=True)
    document = _run(provider)
    assert document.stats["restate_outcomes"] == {"improved": 0, "unchanged": 1}
    assert document.stats["facts_copied"] == 5
    assert document.windows_failed == 0


def test_restate_and_copy_counts_reach_the_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int, dict[str, str]]] = []

    def counter(name: str):
        return type(
            "C", (), {"add": lambda _s, n, labels=None: seen.append((name, n, labels or {}))}
        )()

    for name in ("lines", "noise", "facts", "restate", "entities_counter", "redundant_lines"):
        monkeypatch.setattr(generation_metrics, name, counter(name))
    generation_metrics.record_document(
        {
            "facts_copied": 2,
            "dropped_no_information": 3,
            "dropped_first_person": 1,
            "restate_outcomes": {"improved": 1, "unchanged": 0},
            "lines_unsupported": {"copied": 4, "no_information": 1},
        },
        backend="scripted",
    )
    assert ("facts", 2, {"outcome": "copied"}) in seen
    assert ("facts", 3, {"outcome": "dropped_no_information"}) in seen
    assert ("facts", 1, {"outcome": "dropped_first_person"}) in seen
    assert ("restate", 1, {"outcome": "improved"}) in seen
    assert ("lines", 4, {"outcome": "copied"}) in seen


# ── T4: sub-points ──────────────────────────────────────────────────


def _platform_facts() -> list[VerifiedFact]:
    return [
        _vf("The swim platform is a hybrid of the 75 GT and the 52 designs", start_ms=1_000),
        _vf("A fixed platform sits at the transom, as on the 75 GT", start_ms=2_000),
        _vf("The centre section of the platform is submersible, as on the 52", start_ms=3_000),
        _vf("The tender garage takes a three metre jet tender", start_ms=60_000),
        _vf("The garage door opens hydraulically from the helm", start_ms=61_000),
        _vf("Three cabins and two heads are below deck", start_ms=120_000),
        _vf("The owner cabin is full beam amidships", start_ms=121_000),
    ]


def test_a_bullet_with_two_children_renders_nested_and_as_rows() -> None:
    f = _platform_facts()
    topics = [
        (
            "Swim platform",
            [
                (
                    "The swim platform combines the 75 GT and 52 designs",
                    [f[0].item_key],
                    [
                        ("Fixed platform at the transom, as on the 75 GT", [f[1].item_key]),
                        ("Submersible centre section, as on the 52", [f[2].item_key]),
                    ],
                ),
                ("A three metre jet tender fits the garage", [f[3].item_key], []),
            ],
            [x.item_key for x in f[:4]],
        ),
        (
            "Accommodation",
            [
                ("Three cabins and two heads are below deck", [f[5].item_key], []),
                ("The owner cabin is full beam amidships", [f[6].item_key], []),
            ],
            [f[5].item_key, f[6].item_key],
        ),
    ]
    sections = render.render_sections(f, role_by_key=ROLE_BY_KEY, topics=topics)
    platform = next(s for s in sections if s.title == "Swim platform")
    assert platform.text.splitlines()[:3] == [
        "- The swim platform combines the 75 GT and 52 designs",
        "  - Fixed platform at the transom, as on the 75 GT",
        "  - Submersible centre section, as on the 52",
    ]
    parent, first_child, second_child = platform.lines[:3]
    assert first_child.parent == parent.text and second_child.parent == parent.text
    by_id = {x.item_key: x for x in f}
    parent_row = line_row(parent, platform.section_key, "written", by_id)
    child_row = line_row(first_child, platform.section_key, "written", by_id)
    assert parent_row is not None and child_row is not None
    assert child_row["kind"] == "topic_bullet" and child_row["parent_key"] == parent_row["item_key"]
    assert parent_row["parent_key"] is None


def test_children_that_restate_the_parent_or_cite_nothing_are_dropped() -> None:
    f = _platform_facts()
    by_id = {x.item_key: x for x in f}
    bullet = schema.TopicBullet(
        text="The swim platform combines the 75 GT and 52 designs",
        fact_ids=[f[0].item_key, f[1].item_key],
        children=[
            {
                "text": "The swim platform combines the 75 GT and 52 designs",
                "fact_ids": [f[0].item_key],
            },
            {"text": "Submersible centre section, as on the 52", "fact_ids": []},
            {"text": "Fixed platform at the transom, as on the 75 GT", "fact_ids": [f[1].item_key]},
        ],
    )
    gate = pipeline._Gate()
    kids = pipeline._children(bullet, bullet.text, bullet.fact_ids, by_id, gate)
    assert kids == [("Fixed platform at the transom, as on the 75 GT", [f[1].item_key])]
    assert gate.children_restated == 1


def test_the_topics_schema_allows_three_children_one_level() -> None:
    bullet = schema.REDUCE_TOPICS_SCHEMA["properties"]["topics"]["items"]["properties"]["bullets"][
        "items"
    ]
    children = bullet["properties"]["children"]
    assert children["maxItems"] == 3
    assert "children" not in children["items"]["properties"]
    parsed = schema.TopicBullet.model_validate(
        {
            "text": "x",
            "fact_ids": ["a"],
            "children": [{"text": str(i), "fact_ids": ["a"]} for i in range(5)],
        }
    )
    assert len(parsed.children) == 3


# ── T5: nothing but text in section text ────────────────────────────

_MARKS = re.compile(r"❝|\[↗\]|\b[0-9a-f]{16}\b")


@pytest.mark.parametrize("name", [f"m{n:02d}" for n in range(1, 11)])
def test_no_section_text_carries_a_citation_mark(name: str) -> None:
    from .meeting_doc_fakes import EVAL_FIXTURES

    [path] = sorted(EVAL_FIXTURES.glob(f"{name}_*.json"))
    meeting = load_fixture(path.stem)
    document = asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=ScriptedProvider(),
            role_by_key=ROLE_BY_KEY,
            language=meeting.get("language", "en"),
            meeting_date=DAY,
        )
    )
    for section in document.sections:
        assert not _MARKS.search(section.text), section.section_key
