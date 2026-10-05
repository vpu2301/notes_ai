"""Names, attribution, coverage (Summary Engine v2, Q4).

Names the workspace knows come out right — in the line, never in the
quote; every opinion or forecast says whose it is; salient facts are kept
whatever the reduce step wrote; a hedged record keeps its hedge.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from note_service.domain.glossary import Term
from note_service.domain.meeting_doc import (
    entities,
    pipeline,
    render,
    schema,
    verify,
    windows,
)
from note_service.domain.meeting_doc.verify import VerifiedFact

from .meeting_doc_fakes import ScriptedProvider

DAY = date(2026, 9, 22)


def _window(*texts: tuple[str, str | None], start: int = 0) -> windows.Window:
    turns = tuple(
        windows.Turn(
            i, f"SPEAKER_{i}", name, text, start + i * 10_000, start + i * 10_000 + 9_000, line=i
        )
        for i, (text, name) in enumerate(texts)
    )
    return windows.Window(index=0, turns=turns)


def _verify(facts: list[schema.Fact], window: windows.Window, **kw: Any) -> list[VerifiedFact]:
    return verify.verify_facts(facts, window=window, meeting_date=DAY, **kw)


# ── T1/T2: names the workspace knows ────────────────────────────────


def test_a_calendar_attendee_is_accepted_as_owner() -> None:
    quote = "Fabian Reinbold schickt die Zusammenfassung morgen"
    window = _window((quote, "Imre Balzer"))
    [fact] = _verify(
        [
            schema.Fact(
                kind="action",
                text="Zusammenfassung schicken",
                owner="Fabian Reinbold",
                quote=quote,
                turn=0,
            )
        ],
        window,
        name_candidates=frozenset({"Fabian Reinbold"}),
        language="de",
    )
    assert fact.owner_label == "Fabian Reinbold"
    assert verify.OWNER_INFERRED in fact.flags


def test_a_misheard_name_is_spelled_right_in_the_line_and_left_alone_in_the_quote() -> None:
    quote = "sagt Fabian Reinbolt, das wird knapp mit der Mehrheit"
    window = _window((quote, "Imre Balzer"))
    [fact] = _verify(
        [
            schema.Fact(
                kind="key_point",
                text="Laut Fabian Reinbolt wird die Mehrheit knapp",
                quote=quote,
                turn=0,
            )
        ],
        window,
        name_candidates=frozenset({"Fabian Reinbold"}),
        language="de",
    )
    assert "Fabian Reinbold" in fact.text and "Reinbolt" not in fact.text
    assert fact.quote == quote  # byte for byte
    assert fact.corrections == (
        entities.Correction("Fabian Reinbolt", "Fabian Reinbold", "candidate"),
    )
    assert verify.ENTITY_CORRECTED in fact.flags
    # A corrected name is not a new name: no paraphrase flag for it.
    assert verify.PARAPHRASE_UNSUPPORTED not in fact.flags


def test_a_glossary_mishearing_is_corrected() -> None:
    quote = "Schlesing will das so nicht mittragen, heißt es aus Schwerin"
    window = _window((quote, "Imre Balzer"))
    [fact] = _verify(
        [
            schema.Fact(
                kind="key_point", text="Schlesing will das nicht mittragen", quote=quote, turn=0
            )
        ],
        window,
        glossary=(Term("Schwesig", "person", ("Schlesing",)),),
        language="de",
    )
    assert fact.text == "Schwesig will das nicht mittragen"
    assert fact.quote == quote


def test_two_near_candidates_are_no_correction() -> None:
    table, marked = entities.resolve(
        ["Ann Berg"], known_people=frozenset({"Anna Berg", "Anne Berg"})
    )
    assert table == {} and marked == set()


def test_similarity_is_pinned() -> None:
    assert entities.similarity("Reinbolt", "Reinbold") == 0.875
    assert entities.similarity("Uschmanow", "Usmanow") == 0.875


# ── T3: the model tier ──────────────────────────────────────────────


def _named_facts() -> list[VerifiedFact]:
    def fact(text: str, start: int) -> VerifiedFact:
        return VerifiedFact(
            kind=schema.KEY_POINT, text=text, quote=text, turn=0, start_ms=start, end_ms=start + 1,
            speaker_label="SPEAKER_1", speaker_name="Imre Balzer",
        )  # fmt: skip

    return [
        fact("Uschmanow bleibt auf der Sanktionsliste", 1_000),
        fact("Emil kommentiert die Entscheidung", 2_000),
        fact("Balzar moderiert die Sendung", 3_000),
    ]


def _entity_provider(proposals: list[dict] | Exception) -> ScriptedProvider:
    def answer(_facts: Any) -> dict:
        if isinstance(proposals, Exception):
            raise proposals
        return {"corrections": proposals}

    return ScriptedProvider(overrides={"entities": answer})


def _tier_b(provider: ScriptedProvider, facts: list[VerifiedFact], enabled: bool = True) -> dict:
    counts = {"seen": 0, "model_failed": 0, "marked": 0, "model": 0}
    brief = pipeline.Brief(subject="Sanktionen", themes=["Russland"])
    asyncio.run(
        pipeline._model_names(
            provider,
            facts,
            brief,
            people=frozenset({"Imre Balzer"}),
            entity=counts,
            enabled=enabled,
        )
    )
    return counts


def test_the_model_respells_a_near_name_and_is_doubted_on_a_far_one() -> None:
    facts = _named_facts()
    provider = _entity_provider(
        [
            {"surface": "Uschmanow", "canonical": "Usmanow"},
            {"surface": "Emil", "canonical": "Ignaz"},
            {"surface": "Balzar", "canonical": "Imre Balzer"},
        ]
    )
    counts = _tier_b(provider, facts)
    assert facts[0].text == "Usmanow bleibt auf der Sanktionsliste"
    assert facts[0].quote == "Uschmanow bleibt auf der Sanktionsliste"
    assert facts[0].corrections == (entities.Correction("Uschmanow", "Usmanow", "model"),)
    # Far from what was heard: not applied, doubted.
    assert facts[1].text == "Emil (?) kommentiert die Entscheidung"
    # A participant's name is never proposed onto somebody else.
    assert facts[2].text == "Balzar moderiert die Sendung"
    assert counts["model"] == 1 and counts["marked"] == 1
    # The call saw names and the subject — never a transcript window.
    (step, prompt, _system) = next(c for c in provider.calls if c[0] == "entities")
    assert "Uschmanow" in prompt and "Sanktionen" in prompt and "[0]" not in prompt


def test_a_failed_call_corrects_nothing_and_a_switched_off_tier_calls_nothing() -> None:
    facts = _named_facts()
    counts = _tier_b(_entity_provider(RuntimeError("down")), facts)
    assert counts["model_failed"] == 1 and facts[0].text.startswith("Uschmanow")
    provider = _entity_provider([{"surface": "Uschmanow", "canonical": "Usmanow"}])
    _tier_b(provider, facts, enabled=False)
    assert provider.calls == []


# ── T4: attribution ─────────────────────────────────────────────────


def test_a_speakers_own_forecast_is_theirs_and_says_so() -> None:
    quote = "ich glaube, das Aus für die Rente mit 63 wird abgeschwächt"
    window = _window((quote, "Fabian Reinbold"))
    [fact] = _verify(
        [
            schema.Fact(
                kind="key_point", text="Das Aus für die Rente mit 63 wird abgeschwächt",
                quote=quote, turn=0, certainty="prediction",
            )
        ],
        window,
        language="de",
    )  # fmt: skip
    assert fact.attributed_to == "Fabian Reinbold"
    line = render.plain_line(fact, "de")
    assert line == "- Das Aus für die Rente mit 63 wird abgeschwächt — laut Reinbold"


def test_a_reported_position_is_held_by_who_the_speaker_reports() -> None:
    quote = "Söder fordert, die Mütterrente vorzuziehen"
    window = _window((quote, "Fabian Reinbold"))
    [fact] = _verify(
        [
            schema.Fact(
                kind="key_point", text="Die Mütterrente soll vorgezogen werden", quote=quote,
                turn=0, certainty="proposal", attributed_to="Söder",
            )
        ],
        window,
        language="de",
    )  # fmt: skip
    assert fact.attributed_to == "Söder"
    assert (
        render.plain_line(fact, "de")
        == "- Die Mütterrente soll vorgezogen werden (Vorschlag: Söder)"
    )


def test_an_actor_nobody_said_is_not_accepted() -> None:
    quote = "das halte ich für einen Fehler"
    window = _window((quote, "Jonas Pfeffer"))
    [fact] = _verify(
        [
            schema.Fact(
                kind="key_point", text="Die Entscheidung gilt als Fehler", quote=quote, turn=0,
                certainty="opinion", attributed_to="Olaf Scholz",
            )
        ],
        window,
        language="de",
    )  # fmt: skip
    assert fact.attributed_to == "Jonas Pfeffer"


def test_a_clip_has_no_holder_among_the_participants() -> None:
    turns = [
        windows.Turn(
            0, "SPEAKER_1", "Lena", "Die Ministerin sagte dazu gestern Folgendes " * 8, 0, 60_000
        ),
        windows.Turn(
            1,
            "SPEAKER_3",
            "Karla",
            "Das ist für uns nicht verhandelbar, ganz klar.",
            61_000,
            70_000,
        ),
        windows.Turn(
            2,
            "SPEAKER_1",
            "Lena",
            "Danke. Und nun zum Wetter und den Aussichten " * 20,
            71_000,
            400_000,
        ),
    ]
    [clip_turn] = [t for t in windows.mark_clips(turns) if t.clip]
    assert clip_turn.speaker_label == "SPEAKER_3"
    window = windows.Window(index=0, turns=(dataclasses.replace(clip_turn, line=1),))
    stats = verify.VerifyStats()
    [fact] = verify.verify_facts(
        [
            schema.Fact(
                kind="key_point", text="Das ist nicht verhandelbar",
                quote="Das ist für uns nicht verhandelbar", turn=1, certainty="opinion",
            )
        ],
        window=window, meeting_date=DAY, language="de", stats=stats,
    )  # fmt: skip
    assert fact.attributed_to is None
    assert verify.ATTRIBUTION_MISSING in fact.flags and stats.attribution_missing == 1


def test_a_summary_sentence_about_a_forecast_must_name_its_holder() -> None:
    fact = VerifiedFact(
        kind=schema.KEY_POINT, text="Das Aus für die Rente mit 63 wird wahrscheinlich abgeschwächt",
        quote="das Aus für die Rente mit 63 wird wahrscheinlich abgeschwächt", turn=0,
        start_ms=0, end_ms=1, speaker_label="S1", speaker_name="Fabian Reinbold",
        certainty="prediction", attributed_to="Fabian Reinbold",
    )  # fmt: skip
    gate = pipeline._Gate(language="de")
    sentence = "Das Aus für die Rente mit 63 wird wahrscheinlich abgeschwächt."
    assert gate.reason(sentence, [fact], claims=True) == "attribution"
    assert gate.reason(sentence[:-1] + ", sagt Reinbold.", [fact], claims=True) is None


def test_a_summary_sentence_that_drops_the_hedge_is_dropped() -> None:
    fact = VerifiedFact(
        kind=schema.KEY_POINT, text="Die Kosten steigen auf 3.000 Euro", quote="kostet wohl 3.000 Euro",
        turn=0, start_ms=0, end_ms=1, speaker_label="S1", speaker_name=None, certainty="estimate",
    )  # fmt: skip
    gate = pipeline._Gate(language="de")
    assert gate.reason("Die Kosten steigen auf 3.000 Euro.", [fact], claims=True) == "hedge"
    assert gate.reason("Die Kosten steigen auf geschätzt 3.000 Euro.", [fact], claims=True) is None


# ── T5: salience and topics ─────────────────────────────────────────


def _kp(text: str, start: int, **kw: Any) -> VerifiedFact:
    return VerifiedFact(
        kind=schema.KEY_POINT, text=text, quote=text, turn=0, start_ms=start, end_ms=start + 1,
        speaker_label="S1", speaker_name=None, **kw,
    )  # fmt: skip


def test_an_uncited_salient_fact_joins_the_nearest_topic() -> None:
    facts = [
        _kp("A starts", 0),
        _kp("A goes on", 10_000),
        _kp("B starts", 300_000),
        _kp("B goes on", 310_000),
    ]
    salient = _kp("rund 3.000 Beschäftigte streiken", 305_000)
    topics = [
        ("A", [(f.text, [f.item_key]) for f in facts[:2]], [f.item_key for f in facts[:2]]),
        ("B", [(f.text, [f.item_key]) for f in facts[2:]], [f.item_key for f in facts[2:]]),
    ]
    gate = pipeline._Gate()
    pipeline._append_salient(topics, [*facts, salient], gate)
    assert topics[1][1][-1] == (salient.text, [salient.item_key])
    assert gate.salient_appended == 1
    assert salient.salient and not facts[0].salient


def test_two_topics_over_the_same_stretch_are_one() -> None:
    facts = [_kp(f"point {i}", i * 60_000) for i in range(6)]
    by_id = {f.item_key: f for f in facts}
    ids = [f.item_key for f in facts]
    topics = [
        ("One", [("x", [ids[0]])], [ids[0], ids[3]]),
        ("Two", [("y", [ids[1]])], [ids[1], ids[2]]),
        ("Three", [("z", [ids[5]])], [ids[4], ids[5]]),
    ]
    gate = pipeline._Gate()
    merged = pipeline._merge_overlapping(topics, by_id, gate)
    assert [t[0] for t in merged] == ["One", "Three"]
    assert gate.topics_merged == 1


# ── T6: hedges in code ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "certainty", "language", "expected"),
    [
        ("Das Aus für die Rente mit 63 wird abgeschwächt", "prediction", "de",
         "Voraussichtlich: Das Aus für die Rente mit 63 wird abgeschwächt"),
        ("Das Aus wird wahrscheinlich abgeschwächt", "prediction", "de",
         "Das Aus wird wahrscheinlich abgeschwächt"),
        ("Costs reach 3,000", "estimate", "en", "Estimate: Costs reach 3,000"),
        ("Витрати сягнуть 3000", "estimate", "uk", "Оцінка: Витрати сягнуть 3000"),
    ],
)  # fmt: skip
def test_a_hedged_record_without_a_marker_gets_one_in_code(
    text: str, certainty: str, language: str, expected: str
) -> None:
    assert render.patch_claim(text, [_kp(text, 0, certainty=certainty)], language) == expected


def test_a_plain_fact_is_never_patched() -> None:
    assert (
        render.patch_claim("Costs reach 3,000", [_kp("x", 0, certainty="fact")], "en")
        == "Costs reach 3,000"
    )


# ── T1: the worker's names, per tenant ──────────────────────────────


def test_the_glossary_is_read_inside_the_generations_own_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from note_service.jobs import generate_note

    glossaries = {
        "tenant-a": [Term("Schwesig", "person", ("Schlesing",))],
        "tenant-b": [Term("Contoso", "company", ("Con Tozo",))],
    }
    current: dict[str, str] = {}

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: str):  # noqa: ANN202
        current["tenant"] = tenant_id
        yield object()

    async def _terms(conn: Any) -> list[Term]:
        return glossaries[current["tenant"]]

    from note_service.domain import glossary_repository

    monkeypatch.setattr(generate_note, "tenant_connection", _conn)
    monkeypatch.setattr(glossary_repository, "terms_for_matching", _terms)
    result = {
        "name_candidates": ["Fabian Reinbold"],
        "speaker_names": {"SPEAKER_1": "Imre Balzer", "SPEAKER_2": "Speaker 2"},
    }
    meeting = SimpleNamespace(calendar_context={"attendee_names": ["Lena Hartwig"]})
    deps = SimpleNamespace(app_pool=None)
    people, terms = asyncio.run(
        generate_note._known_names(deps, "tenant-b", result=result, meeting=meeting)
    )
    assert [t.term for t in terms] == ["Contoso"]  # never tenant A's Schwesig
    assert people == {"Fabian Reinbold", "Imre Balzer", "Lena Hartwig"}


def test_a_glossary_that_cannot_be_read_costs_only_the_glossary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from note_service.domain import glossary_repository
    from note_service.jobs import generate_note

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: str):  # noqa: ANN202
        yield object()

    async def _broken(conn: Any) -> list[Term]:
        raise RuntimeError("db down")

    monkeypatch.setattr(generate_note, "tenant_connection", _conn)
    monkeypatch.setattr(glossary_repository, "terms_for_matching", _broken)
    people, terms = asyncio.run(
        generate_note._known_names(
            SimpleNamespace(app_pool=None), "t", result={"name_candidates": ["A B"]}, meeting=None
        )
    )
    assert terms == () and people == {"A B"}


def test_a_window_answered_with_line_numbers_is_asked_again() -> None:
    """Found on the Q4 eval: the 4B model answered quote="[0]" for every
    fact of a voice memo, and the note came out empty."""
    from note_service.domain.meeting_doc import prompts

    window = _window(("I need to send the signed purchase order by Friday at the latest", "Nadia"))
    answers = iter(
        [
            {"topic_title": "", "noise": [], "facts": [
                {"kind": "action", "text": "Send the order", "quote": "[0]", "turn": 0, "explicit": True}]},
            {"topic_title": "", "noise": [], "facts": [
                {"kind": "action", "text": "Send the order", "quote": "send the signed purchase order",
                 "turn": 0, "explicit": True}]},
        ]
    )  # fmt: skip
    prompts_seen: list[str] = []

    class _Provider:
        backend = model_id = "fake"

        async def complete(self, prompt: str, schema: Any = None, **kwargs: Any) -> Any:
            import json

            prompts_seen.append(prompt)
            return SimpleNamespace(text=json.dumps(next(answers)))

    out = asyncio.run(pipeline._extract(_Provider(), window, "en"))
    assert out is not None and out.facts[0].quote == "send the signed purchase order"
    assert prompts.quote_reminder("en") in prompts_seen[1]
    assert prompts.quote_reminder("en") not in prompts_seen[0]
