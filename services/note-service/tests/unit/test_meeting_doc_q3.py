"""The document fits the recording (Summary Engine v2, Q3).

A podcast is extracted as a broadcast — no decisions, no tasks — each
fact is written once, nothing the engine writes can be mistaken for a
speaker, and a spoken date is resolved in the tense it was said in.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, time
from types import SimpleNamespace
from typing import Any

import pytest

from note_service.domain.action_items import parse_due, parse_when
from note_service.domain.meeting_doc import (
    classify,
    pipeline,
    render,
    roles,
    schema,
    support,
    types,
    verify,
    windows,
)
from note_service.domain.meeting_doc.verify import VerifiedFact

from .meeting_doc_fakes import ScriptedProvider, as_result, load_fixture, spoken

TUESDAY = date(2026, 9, 22)


# ── T2: recording type → family ─────────────────────────────────────


class _Classifier:
    backend = "fake"
    model_id = "fake"

    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.calls = 0

    async def complete(self, prompt: str, schema: Any = None, **kwargs: Any) -> Any:
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(json={"recording_type": self.answer}, text="")


def _classify(answer: str | Exception, **kw: Any) -> tuple[str, str]:
    args: dict[str, Any] = {
        "head": "[0] A (00:00): Guten Morgen",
        "language": "de",
        "speakers": 2,
        "minutes": 7.0,
        "calendar_title": None,
        "attendees": 0,
    }
    args.update(kw)
    return asyncio.run(classify.classify(_Classifier(answer), **args))


def test_a_podcast_is_a_broadcast_and_is_never_offered_decisions_or_tasks() -> None:
    assert _classify("podcast_broadcast") == ("podcast_broadcast", "classifier")
    family = types.family_for_recording_type("podcast_broadcast")
    assert family.meeting_type == "broadcast"
    kinds = types.fact_kinds(family)
    assert not {"decision", "action", "agenda_item", "completion"} & set(kinds)
    enum = schema.extract_schema(tuple(kinds))["properties"]["facts"]["items"]["properties"]
    assert "decision" not in enum["kind"]["enum"] and "action" not in enum["kind"]["enum"]


def test_a_calendared_call_with_people_is_not_a_broadcast() -> None:
    assert _classify("podcast_broadcast", calendar_title="Weekly sync", attendees=3) == (
        "meeting",
        "rule",
    )


def test_one_voice_for_three_minutes_is_a_memo_whatever_the_model_says() -> None:
    assert _classify("meeting", speakers=1, minutes=3.0) == ("voice_memo", "rule")
    assert _classify("meeting", speakers=1, minutes=40.0) == ("lecture_webinar", "rule")
    assert _classify("podcast_broadcast", speakers=1, minutes=40.0) == (
        "podcast_broadcast",
        "classifier",
    )


def test_a_classifier_that_fails_leaves_a_meeting() -> None:
    assert _classify(RuntimeError("down")) == ("meeting", "template")
    assert _classify("not-a-type") == ("meeting", "template")


def test_the_authors_choice_is_never_second_guessed() -> None:
    from note_service.jobs import generate_note

    provider = _Classifier("podcast_broadcast")
    auto = types.family_for_template("meeting_notes")

    def run(meeting_type: str, template_family: types.Family) -> tuple[str, str]:
        return asyncio.run(
            generate_note._recording_type(
                provider,
                meeting=SimpleNamespace(meeting_type=meeting_type, calendar_context={}),
                template_family=template_family,
                built=[],
                turns=[],
                language="de",
            )
        )

    assert run("sales", auto) == ("sales_call", "user")
    assert run("auto", types.family_for_template("client_call_de")) == ("client_call", "user")
    assert provider.calls == 0
    assert run("auto", auto)[0] == "voice_memo"  # no turns: one voice, zero minutes
    assert provider.calls == 1


def test_the_detected_type_is_stored_in_the_meetings_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib

    from note_service.jobs import generate_note

    stored: list[tuple[str, str]] = []

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: Any):  # noqa: ANN202
        yield object()

    async def _set(conn: Any, *, note_id: Any, detected: str, detected_by: str) -> None:
        stored.append((detected, detected_by))

    monkeypatch.setattr(generate_note, "tenant_connection", _conn)
    monkeypatch.setattr(generate_note.meetings, "set_detected_type", _set)
    deps = SimpleNamespace(app_pool=None)
    for rt, source in (
        ("podcast_broadcast", "classifier"),
        ("sales_call", "user"),
        ("meeting", "rule"),
    ):
        asyncio.run(
            generate_note._store_detected_type(
                deps, "t", note_id="n", recording_type=rt, source=source
            )
        )
    assert stored == [("podcast_broadcast", "model"), ("sales", "user"), ("auto", "model")]

    async def _broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("check constraint")

    monkeypatch.setattr(generate_note.meetings, "set_detected_type", _broken)
    # 0058 not applied: logged, never raised.
    asyncio.run(
        generate_note._store_detected_type(
            deps, "t", note_id="n", recording_type="voice_memo", source="rule"
        )
    )


def _m06(provider: ScriptedProvider) -> pipeline.DocumentResult:
    meeting = load_fixture("m06_de_news_podcast")
    return asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=provider,
            role_by_key={"decisions": roles.DECISIONS, "action_items": roles.ACTION_ITEMS},
            language="de",
            meeting_date=TUESDAY,
            family=types.family_for_recording_type("podcast_broadcast"),
            recording_type="podcast_broadcast",
            recording_type_source="classifier",
        )
    )


def test_m06_as_a_broadcast_has_no_decisions_or_tasks() -> None:
    provider = ScriptedProvider()
    document = _m06(provider)
    assert document.stats["recording_type"] == "podcast_broadcast"
    assert document.stats["recording_type_source"] == "classifier"
    assert not [s for s in document.sections if s.role in (roles.DECISIONS, roles.ACTION_ITEMS)]
    extract = [
        s
        for step, s in zip((c[0] for c in provider.calls), provider.schemas, strict=True)
        if step == "extract"
    ]
    for sent in extract:
        kinds = sent["properties"]["facts"]["items"]["properties"]["kind"]["enum"]
        assert "decision" not in kinds and "action" not in kinds


# ── T4: one fact, once ──────────────────────────────────────────────


def _fact(text: str, start_ms: int, kind: str = schema.KEY_POINT) -> VerifiedFact:
    return VerifiedFact(
        kind=kind,
        text=text,
        quote=spoken(text),
        turn=0,
        start_ms=start_ms,
        end_ms=start_ms + 1_000,
        speaker_label="SPEAKER_1",
        speaker_name=None,
    )


FACTS = [
    _fact("the pension rule is weakened", 1_000),
    _fact("the committee meets on Thursday", 2_000),
    _fact("the union calls a strike", 90_000),
    _fact("the strike lasts until Wednesday", 95_000),
    _fact("parts deliveries may slow down", 99_000),
]
IDS = [f.item_key for f in FACTS]


def _render(topics: list, summary: list | None = None, counters: dict | None = None) -> list:
    return render.render_sections(
        FACTS, role_by_key={}, topics=topics, summary=summary, counters=counters
    )


def _bullets(sections: list) -> list[str]:
    return [line.text for s in sections if s.role == roles.TOPICS for line in s.lines]


def test_the_same_fact_in_two_topics_is_written_once() -> None:
    counters: dict[str, int] = {}
    sections = _render(
        [
            ("Pension", [(FACTS[0].text, [IDS[0]]), (FACTS[1].text, [IDS[1]])], []),
            (
                "Strike",
                [
                    (FACTS[2].text, [IDS[2]]),
                    ("The pension rule is weakened again", [IDS[0]]),
                    (FACTS[3].text, [IDS[3]]),
                ],
                [],
            ),
        ],
        counters=counters,
    )
    bullets = _bullets(sections)
    assert sum("pension rule" in b for b in bullets) == 1
    assert counters["redundant_lines"] == 1


def test_a_bullet_the_summary_already_says_is_dropped() -> None:
    sections = _render(
        [
            ("Pension", [(FACTS[0].text, [IDS[0]]), (FACTS[1].text, [IDS[1]])], []),
            ("Strike", [(FACTS[2].text, [IDS[2]]), (FACTS[3].text, [IDS[3]])], []),
        ],
        summary=[("The union calls a strike.", [IDS[2]])],
    )
    assert "- the union calls a strike" not in _bullets(sections)
    # The topic then has one bullet: it joins the one before it.
    titles = [s.title for s in sections if s.role == roles.TOPICS]
    assert titles == []  # one topic left is no heading: a single list


def test_a_single_bullet_topic_joins_the_topic_before_it() -> None:
    sections = _render(
        [
            ("Pension", [(FACTS[0].text, [IDS[0]]), (FACTS[1].text, [IDS[1]])], []),
            ("Strike", [(FACTS[2].text, [IDS[2]]), (FACTS[3].text, [IDS[3]])], []),
            ("Deliveries", [(FACTS[4].text, [IDS[4]])], []),
        ]
    )
    topics = [s for s in sections if s.role == roles.TOPICS]
    assert [t.title for t in topics] == ["Pension", "Strike"]
    assert topics[-1].lines[-1].text == "- parts deliveries may slow down"


def test_topics_are_in_the_order_of_the_recording() -> None:
    sections = _render(
        [
            ("Strike", [(FACTS[2].text, [IDS[2]]), (FACTS[3].text, [IDS[3]])], []),
            ("Pension", [(FACTS[0].text, [IDS[0]]), (FACTS[1].text, [IDS[1]])], []),
        ]
    )
    assert [s.title for s in sections if s.role == roles.TOPICS] == ["Pension", "Strike"]


def test_m06_is_not_redundant() -> None:
    document = _m06(ScriptedProvider())
    lines = [
        support.merge_tokens(line.text)
        for _key, line in document.lines
        if line.kind not in ("heading", "note")
    ]
    repeated = {
        i
        for i in range(len(lines))
        for j in range(len(lines))
        if i != j
        and lines[i]
        and lines[j]
        and len(lines[i] & lines[j]) / len(lines[i] | lines[j]) >= 0.6
    }
    assert len(repeated) / max(1, len(lines)) < 0.05
    assert document.stats["lines_total"] == len(document.lines)


# ── T5: nothing the web could mistake for a speaker ─────────────────

# `web/src/lib/richText.ts` SPEAKER, ported: a paragraph that opens with
# up to four words and ": " is drawn as a speaker turn with initials.
SPEAKER = re.compile(r"^(?!https?:)([^\s*_`:][^*_`:]{0,39}?):\s+(?=\S)")


def test_no_line_the_engine_writes_reads_as_a_speaker_turn() -> None:
    document = _m06(ScriptedProvider(noise=[{"turn": 2, "reason": "background"}]))
    assert document.lines
    for _key, line in document.lines:
        # The web reads a speaker turn from a PARAGRAPH only; a "- …" list
        # item is never one, so a "- Voraussichtlich: …" record (Q4) is safe.
        if not line.text.startswith(("- ", "### ")):
            assert not SPEAKER.match(line.text), line.text
    assert all(line.kind != "note" for _key, line in document.lines)
    assert not hasattr(render, "transcript_note")


def test_an_action_line_only_opens_with_its_owner() -> None:
    owned = _fact("Send the offer", 1_000, kind=schema.ACTION)
    owned.owner_label = "Mira"
    sections = render.render_sections([owned], role_by_key={})
    (line,) = [line for s in sections for line in s.lines if line.kind == "action"]
    match = SPEAKER.match(line.text.removeprefix("- "))
    assert match and match.group(1) == owned.owner_label


# ── T6: dates with a direction ──────────────────────────────────────


@pytest.mark.parametrize(
    ("quote", "language", "text", "resolved", "clock"),
    [
        (
            "Die Runde ist am Montag in der Sitzung gewesen",
            "de",
            "am montag",
            date(2026, 9, 21),
            None,
        ),
        (
            "Der Streik soll bis Mittwoch 0 Uhr dauern",
            "de",
            "bis mittwoch 0 uhr",
            date(2026, 9, 23),
            time(0, 0),
        ),
        ("Am Montag treffen wir uns wieder", "de", "am montag", date(2026, 9, 28), None),
        ("Seit heute früh wird gestreikt", "de", "seit heute", date(2026, 9, 22), None),
        ("Das klären wir nächste Woche", "de", "nächste woche", date(2026, 9, 29), None),
        ("Das war letzte Woche schon so", "de", "letzte woche", date(2026, 9, 15), None),
        ("Ab 1. Oktober gilt die neue Regel", "de", "ab 1 oktober", date(2026, 10, 1), None),
        ("The round was on Monday in the hall", "en", "on monday", date(2026, 9, 21), None),
        (
            "The strike lasts until Wednesday midnight",
            "en",
            "until wednesday midnight",
            date(2026, 9, 23),
            time(0, 0),
        ),
        ("We meet on Monday again", "en", "on monday", date(2026, 9, 28), None),
        ("That was last week already", "en", "last week", date(2026, 9, 15), None),
        ("Засідання було у понеділок", "uk", "у понеділок", date(2026, 9, 21), None),
        (
            "Страйк триває до середи опівночі",
            "uk",
            "до середи опівночі",
            date(2026, 9, 23),
            time(0, 0),
        ),
        ("Зустрінемося у понеділок", "uk", "у понеділок", date(2026, 9, 28), None),
    ],
)
def test_the_date_unit_set(
    quote: str, language: str, text: str, resolved: date, clock: time | None
) -> None:
    (mention,) = verify.date_mentions(quote, meeting_date=TUESDAY, language=language)
    assert (mention.text, mention.resolved, mention.time) == (text, resolved, clock)


def test_a_date_is_an_annotation_and_the_words_stay() -> None:
    quote = "Seit heute früh wird gestreikt, sagt der Hafenbund"
    window = windows.Window(index=0, turns=(windows.Turn(0, "S1", None, quote, 0, 5_000, line=0),))
    [fact] = verify.verify_facts(
        [schema.Fact(kind="key_point", text="Seit heute wird gestreikt", quote=quote, turn=0)],
        window=window,
        meeting_date=TUESDAY,
        language="de",
    )
    assert "heute" in fact.text and "heute" in fact.quote
    assert [(m.text, m.iso()) for m in fact.mentions] == [("seit heute", "2026-09-22")]


def test_what_is_not_a_date_stays_unresolved() -> None:
    assert verify.date_mentions("Guten Morgen zusammen", meeting_date=TUESDAY, language="de") == []
    assert parse_when("Ende des Jahres", anchor=TUESDAY) is None


def test_a_deadline_said_in_the_past_resolves_backwards() -> None:
    turn = windows.Turn(0, "S1", None, "Das Angebot kam bis Freitag, das war zu spät", 0, 5_000)
    _text, due, _flags = verify.resolve_due(
        "bis Freitag", turn=turn, meeting_date=TUESDAY, quote=turn.text, language="de"
    )
    assert due == date(2026, 9, 18)


def test_parse_due_is_unchanged() -> None:
    """The items projection reads parse_due: forward-looking, as before."""
    assert parse_due("am Montag", anchor=TUESDAY) == date(2026, 9, 28)
    assert parse_due("gestern", anchor=TUESDAY) is None
    assert parse_due("letzte Woche", anchor=TUESDAY) is None
    assert parse_due("bis Mittwoch 0 Uhr", anchor=TUESDAY) == date(2026, 9, 23)


def test_the_classifier_is_never_offered_meeting_first() -> None:
    """A small model picks the first option when unsure; "meeting" first
    labelled the audit's news podcast a meeting."""
    from note_service.domain.meeting_doc import prompts

    offered = classify.CLASSIFY_SCHEMA["properties"]["recording_type"]["enum"]
    assert offered[0] == "podcast_broadcast" and offered[-1] == "meeting"
    for language in ("en", "de", "uk"):
        text = prompts.classify_system(language)
        assert text.index("podcast_broadcast:") < text.index("meeting:"), language
