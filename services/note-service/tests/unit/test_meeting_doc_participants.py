"""F2-01 — participants need person and participation evidence: an introduction cue counts
only right before a person-shaped name; a weak cue needs the participant check; a voice is
linked to an introduction only by evidence, never because it speaks next; a quoted voice
is not a guest; the framing names nobody the roles table did not accept.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date
from typing import Any

from note_service.domain.meeting_doc import (
    compose,
    pipeline,
    prompts,
    roles_table,
    schema,
    verify,
)
from note_service.domain.meeting_doc.windows import Turn, Window

from .meeting_doc_fakes import ScriptedProvider

HOST_OPENING = (
    "Würdet ihr für 5000 Dollar wählen? Der Kongress ist in zwei Kammern aufgeteilt. "
    "Das ist einmal das Repräsentantenhaus mit 435 Abgeordneten. Und diese Midterm-Wahlen "
    "stehen am 3. November an."
)


def _intro(quote: str, name: str, **fields: Any) -> schema.Fact:
    return schema.Fact(
        kind=schema.INTRODUCTION, text="Introduction", quote=quote, turn=0, name=name, **fields
    )


def _person(quote: str, name: str, *, context: str = "", known: frozenset[str] = frozenset()):
    person, _cleared = verify.verify_introduction(
        _intro(quote, name), language="de", context=context, known=known
    )
    return person


# ── the cue must introduce THIS name ───────────────────────────────


def test_an_event_named_in_a_line_with_a_cue_elsewhere_is_nobody() -> None:
    # "Das ist einmal das …" stands in the line; the name is not introduced by it.
    assert _person("diese Midterm-Wahlen stehen am 3. November an", "Midterm-Wahlen",
                   context=HOST_OPENING) is None  # fmt: skip


def test_a_chamber_after_das_ist_is_not_a_person_introduction() -> None:
    assert _person("Das ist das Repräsentantenhaus", "das Repräsentantenhaus") is None
    # Even named bare, "das ist" is weak: pending, and only the participant check decides.
    pending = _person("Das ist Repräsentantenhaus", "Repräsentantenhaus")
    assert pending is not None and pending.evidence == verify.INTRO_PENDING


def test_bei_uns_ist_introduces_a_person() -> None:
    person = _person("Bei uns ist heute Anna Müller, Ökonomin", "Anna Müller")
    assert person is not None and person.evidence == verify.INTRO_LEXICAL
    assert not person.self_introduction
    welcomed = _person("Anna Müller, herzlich willkommen", "Anna Müller")
    assert welcomed is not None and welcomed.evidence == verify.INTRO_LEXICAL


def test_a_single_word_after_a_strong_cue_needs_the_check_unless_known() -> None:
    assert _person("Bei uns ist Besuch", "Besuch").evidence == verify.INTRO_PENDING
    known = _person("Bei uns ist Felix", "Felix", known=frozenset({"Felix"}))
    assert known.evidence == verify.INTRO_LEXICAL
    named = _person("Mein Name ist Felix", "Felix")
    assert named.evidence == verify.INTRO_LEXICAL and named.self_introduction


def test_without_fidelity_a_pending_introduction_introduces_nobody() -> None:
    window = Window(
        0, (Turn(0, "SPEAKER_1", None, "Das ist Repräsentantenhaus heute.", 0, 5000, line=0),)
    )
    [plain] = verify.verify_facts(
        [_intro("Das ist Repräsentantenhaus heute", "Repräsentantenhaus")],
        window=window,
        meeting_date=date(2026, 10, 18),
        language="de",
        allowed_kinds=frozenset({schema.INTRODUCTION, schema.KEY_POINT}),
    )
    assert plain.person is None and plain.kind == schema.KEY_POINT


def test_person_metadata_is_rejected_even_when_its_words_were_said() -> None:
    assert not verify.person_shaped("das Repräsentantenhaus")
    assert not verify.person_shaped("Midterm 2026")
    assert verify.person_shaped("Ursula von der Leyen")
    assert roles_table.real_name("Das Repräsentantenhaus") is None


# ── a voice is linked only by evidence ─────────────────────────────


def _turns(*spec: tuple[str, str, int, str | None]) -> list[Turn]:
    out, start = [], 0
    for n, (label, text, seconds, language) in enumerate(spec):
        out.append(
            Turn(n, label, None, text, start, start + seconds * 1000, line=n, language=language)
        )
        start += seconds * 1000
    return out


def _fact_at(turn: Turn, person: verify.Person) -> verify.VerifiedFact:
    return verify.VerifiedFact(
        kind=schema.INTRODUCTION,
        text="Introduction",
        quote=turn.text,
        turn=turn.index,
        start_ms=turn.start_ms,
        end_ms=turn.end_ms,
        speaker_label=turn.speaker_label,
        speaker_name=None,
        line=turn.number,
        person=person,
    )


def _broadcast_with_clip() -> list[Turn]:
    """A German explainer: the host talks; an English clip of somebody quoted is inserted."""
    return _turns(
        ("SPEAKER_1", HOST_OPENING, 120, None),
        ("SPEAKER_2", "And here is my promise. I will issue a dividend.", 20, "en"),
        ("SPEAKER_1", "Wie das finanziert werden soll, lässt er offen.", 60, None),
        ("SPEAKER_2", "So I'm asking you to pretend that I'm on the ballot.", 6, "en"),
        ("SPEAKER_1", "Die Strategie ist riskant.", 90, None),
        ("SPEAKER_2", "They call themselves socialists.", 6, "en"),
        ("SPEAKER_1", "Und wie seht ihr das? Schreibt es in die Kommentare.", 60, None),
    )


def test_an_inserted_foreign_clip_is_a_quoted_voice_not_a_guest() -> None:
    turns = _broadcast_with_clip()
    # The extractor's bogus "introduction" of the event, as before F2.
    bogus = _fact_at(turns[0], verify.Person(name="Midterm-Wahlen"))
    table = roles_table.build(turns, [bogus], "podcast_broadcast")
    assert table.role_of("SPEAKER_2") == roles_table.CLIP
    speakers, guests, others = compose.speakers_of(table, "de")
    assert guests == [] and not any("Midterm" in s for s in [*speakers, *others])
    assert not any(s.name == "Midterm-Wahlen" for s in table.speakers.values())


def test_following_an_introduction_is_not_a_link() -> None:
    turns = _turns(
        ("SPEAKER_1", "Bei uns ist heute Anna Müller. Doch zuerst die Nachrichten.", 30, None),
        ("SPEAKER_1", "Der Haushalt wurde beschlossen.", 60, None),
        ("SPEAKER_2", "Danke. Ich sehe das kritisch.", 60, None),
        ("SPEAKER_2", "Erstens die Schulden.", 60, None),
        ("SPEAKER_2", "Zweitens die Zinsen.", 60, None),
    )
    fact = _fact_at(turns[0], verify.Person(name="Anna Müller"))
    table = roles_table.build(turns, [fact], "podcast_broadcast")
    # The host spoke on in between: no handover, so SPEAKER_2 stays unnamed.
    assert table.speakers["SPEAKER_2"].name is None


def test_a_handover_links_the_next_voice() -> None:
    turns = _turns(
        ("SPEAKER_1", "Bei uns ist heute Anna Müller.", 300, None),
        ("SPEAKER_2", "Danke für die Einladung. Ich sehe das kritisch.", 60, None),
        ("SPEAKER_1", "Warum?", 5, None),
        ("SPEAKER_2", "Erstens die Schulden.", 60, None),
        ("SPEAKER_2", "Zweitens die Zinsen.", 60, None),
    )
    fact = _fact_at(turns[0], verify.Person(name="Anna Müller"))
    table = roles_table.build(turns, [fact], "podcast_broadcast")
    assert table.speakers["SPEAKER_2"].name == "Anna Müller"
    assert table.role_of("SPEAKER_2") == roles_table.GUEST


def test_a_quoted_person_or_a_non_person_names_no_voice() -> None:
    turns = _turns(
        ("SPEAKER_1", "Bei uns ist heute Anna Müller.", 30, None),
        ("SPEAKER_2", "Danke. Ich sehe das kritisch.", 60, None),
        ("SPEAKER_2", "Erstens.", 60, None),
        ("SPEAKER_2", "Zweitens.", 60, None),
    )
    quoted = _fact_at(turns[0], verify.Person(name="Anna Müller", participation="quoted"))
    event = _fact_at(turns[0], verify.Person(name="Anna Müller", entity="event"))
    for fact in (quoted, event):
        assert (
            roles_table.build(turns, [fact], "podcast_broadcast").speakers["SPEAKER_2"].name is None
        )


def test_an_unknown_host_stays_unknown() -> None:
    table = roles_table.build(_broadcast_with_clip(), [], "podcast_broadcast")
    host = table.speakers["SPEAKER_1"]
    assert host.role in (roles_table.HOST, roles_table.NARRATOR) and host.name is None
    speakers, guests, _others = compose.speakers_of(table, "de")
    assert guests == [] and all("Midterm" not in s for s in speakers)


# ── the participant check (fidelity) ───────────────────────────────


def _checked(answer: Any, *facts: verify.VerifiedFact, window: Window) -> tuple[list, Counter]:
    provider = ScriptedProvider(overrides={"participants": answer})
    tally: Counter[str] = Counter()
    out = asyncio.run(
        pipeline._confirm_participants(
            provider, list(facts), {0: window}, "de", tally, task=prompts.task("de")
        )
    )
    return out, tally


def _window_of(turns: list[Turn]) -> Window:
    return Window(0, tuple(turns))


def _answer(**fields: Any) -> Any:
    entry = {"item_id": "p1", "entity": "person", "introduced": True, "participation": "guest",
             "speaks_at": None, "evidence_ids": ["0"], **fields}  # fmt: skip
    return lambda _facts: {"participants": [entry]}


def test_the_check_rejects_an_event_and_keeps_it_as_evidence_only() -> None:
    turns = _turns(("SPEAKER_1", "Das ist Repräsentantenhaus heute.", 10, None))
    fact = _fact_at(
        turns[0], verify.Person(name="Repräsentantenhaus", evidence=verify.INTRO_PENDING)
    )
    [out], tally = _checked(
        _answer(entity="institution", introduced=False, participation="unknown"),
        fact,
        window=_window_of(turns),
    )
    assert out.evidence_only and verify.INTRODUCTION_REJECTED in out.flags
    assert out.person.entity == "institution" and tally["rejected_institution"] == 1


def test_the_check_links_the_voice_that_speaks_and_never_the_introducer() -> None:
    turns = _turns(
        ("SPEAKER_1", "Hier ist Anna Müller.", 10, None),
        ("SPEAKER_2", "Danke schön.", 10, None),
    )
    fact = _fact_at(turns[0], verify.Person(name="Anna Müller", evidence=verify.INTRO_PENDING))
    [out], tally = _checked(
        _answer(speaks_at="1", evidence_ids=["0", "1"]), fact, window=_window_of(turns)
    )
    assert out.person.speaker == "SPEAKER_2" and out.person.evidence == verify.INTRO_CHECKED
    assert tally["linked"] == 1
    [same], _ = _checked(_answer(speaks_at="0"), fact, window=_window_of(turns))
    assert same.person.speaker is None


def test_a_quoted_person_is_kept_as_quoted() -> None:
    turns = _turns(("SPEAKER_1", "Hier ist Donald Trump auf einer Kundgebung.", 10, None))
    fact = _fact_at(turns[0], verify.Person(name="Donald Trump"))
    [out], tally = _checked(
        _answer(participation="quoted", introduced=False), fact, window=_window_of(turns)
    )
    assert out.person.participation == "quoted" and not out.evidence_only and tally["quoted"] == 1


def test_an_unanswered_check_makes_a_pending_introduction_nobody() -> None:
    turns = _turns(("SPEAKER_1", "Das ist Anna heute.", 10, None))
    pending = _fact_at(turns[0], verify.Person(name="Anna", evidence=verify.INTRO_PENDING))
    lexical = _fact_at(turns[0], verify.Person(name="Anna Müller"))

    def down(_facts: Any) -> Any:
        raise RuntimeError("provider down")

    out, tally = _checked(down, pending, lexical, window=_window_of(turns))
    assert verify.INTRODUCTION_REJECTED in out[0].flags
    assert out[1].person.evidence == verify.INTRO_LEXICAL and not out[1].flags
    assert tally["unavailable"] == 2


def test_a_check_citing_a_line_it_was_not_shown_decides_nothing() -> None:
    turns = _turns(("SPEAKER_1", "Das ist Anna heute.", 10, None))
    pending = _fact_at(turns[0], verify.Person(name="Anna", evidence=verify.INTRO_PENDING))
    [out], tally = _checked(_answer(evidence_ids=["40"]), pending, window=_window_of(turns))
    assert verify.INTRODUCTION_REJECTED in out.flags and tally["foreign_lines"] == 1


# ── the framing names only accepted participants ───────────────────


def test_the_framing_cannot_name_an_invented_participant() -> None:
    table = roles_table.RolesTable(
        speakers={
            "S1": roles_table.Speaker("S1", 0.8, 10, 0.4, roles_table.HOST),
            "S2": roles_table.Speaker("S2", 0.2, 5, 0.2, roles_table.GUEST, "Anna Müller"),
        }
    )
    assert compose.framing_participants_ok("Ein Gespräch mit Anna Müller über die Wahl", table)
    assert not compose.framing_participants_ok("Ein Gespräch mit Midterm-Wahlen", table)
    assert not compose.framing_participants_ok("Interview with Senate", table)
    assert compose.framing_participants_ok("Erklärvideo über die Midterm-Wahlen", table)
    assert compose.framing_participants_ok("Podcast mit Gästen", table)
