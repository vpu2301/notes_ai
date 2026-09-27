"""Sprint D2 — composition to the standard: blocks, phase headings,
subjects, roles, orientation. Tests follow the work order's tasks."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from typing import Any

from note_service.domain.meeting_doc import (
    classify,
    compose,
    doclint,
    pipeline,
    prompts,
    roles,
    roles_table,
    schema,
    types,
    verify,
)
from note_service.domain.meeting_doc.verify import Person, VerifiedFact
from note_service.domain.meeting_doc.windows import Turn, Window

from .meeting_doc_fakes import REPO, ScriptedProvider, as_result

MIN = 60_000
DAY = date(2026, 9, 26)


def _fact(text: str, start_ms: int, **kw: Any) -> VerifiedFact:
    return VerifiedFact(
        kind=kw.pop("kind", schema.KEY_POINT),
        text=text,
        quote=kw.pop("quote", "so wurde es in dem Gespräch erzählt"),
        turn=kw.pop("turn", 0),
        start_ms=start_ms,
        end_ms=start_ms + 1_000,
        speaker_label=kw.pop("speaker_label", "SPEAKER_1"),
        speaker_name=kw.pop("speaker_name", None),
        **kw,
    )


def _recording(turns: int, voices: tuple[str, ...] = ("SPEAKER_1", "SPEAKER_2")) -> dict:
    return {
        "language": "de",
        "transcript": [
            {
                "speaker": voices[n % len(voices)],
                "t_start_ms": n * 20_000,
                "t_end_ms": n * 20_000 + 19_000,
                "text": f"Im Jahr {2000 + n} traf Peter Thiel in Kalifornien genau {n + 3} "
                "Investoren aus dem Silicon Valley und sprach lange über Daten",
            }
            for n in range(turns)
        ],
    }


def _run(meeting: dict, provider: ScriptedProvider, **kw: Any) -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=provider,
            role_by_key={},
            language="de",
            meeting_date=DAY,
            **kw,
        )
    )


# ── T1 blocks, budget, per-block reduce ─────────────────────────────


def test_84_facts_over_28_minutes_are_7_blocks_in_time_order() -> None:
    facts = [_fact(f"Fakt {n} über Palantir im Jahr {1990 + n}", n * 20_000) for n in range(84)]
    parts = compose.blocks(list(reversed(facts)), minutes=28)
    assert len(parts) == 7
    assert all(len(b.facts) >= compose.MIN_BLOCK_FACTS for b in parts)
    flat = [f for b in parts for f in b.facts]
    assert flat == sorted(facts, key=lambda f: f.start_ms)


def test_blocks_cut_at_the_largest_gaps_and_topic_shifts() -> None:
    facts = [
        _fact(f"Fakt {n} im Jahr {1990 + n}", n * 10_000, window_index=n // 6) for n in range(12)
    ]
    facts += [
        _fact(f"Fakt {n} im Jahr {1990 + n}", 10 * MIN + n * 10_000, window_index=2)
        for n in range(12, 24)
    ]
    parts = compose.blocks(facts, minutes=12)
    assert parts[1].facts[0].start_ms >= 10 * MIN or parts[0].span[1] < 10 * MIN
    shifted = compose.blocks(facts[:12], minutes=12, topic_titles={0: "Gründung", 1: "Kritik"})
    assert shifted[0].facts[-1].window_index == 0 and shifted[1].facts[0].window_index == 1


def test_the_budget_follows_the_length_of_speech() -> None:
    assert compose.VolumeBudget(30, 7).target_words == 360
    assert compose.VolumeBudget(30, 7).bullets_per_block == 2
    assert compose.VolumeBudget(60, 8).bullets_per_block == 5
    assert compose.VolumeBudget(3, 1).bullets_per_block == 2


def test_a_block_whose_call_fails_twice_is_a_chapter_and_the_rest_are_model_headed() -> None:
    def block(facts: list[tuple[str, str, str]]) -> dict:
        if any("2000 " in t for _i, _k, t in facts):
            return {"heading": 5, "bullets": "broken"}  # not the schema
        return {
            "heading": "Peter Thiel und die Investoren in Kalifornien",
            "bullets": [{"text": t, "fact_ids": [i]} for i, _k, t in facts[:3]],
        }

    document = _run(_recording(40), ScriptedProvider(overrides={"block": block}))
    stats = document.stats
    assert stats["block_chapters"] == 1 and stats["blocks"] >= 3
    assert stats["block_failures"] == {"schema_invalid": 2}
    titles = [s.title or "" for s in document.sections if s.role == roles.TOPICS]
    assert re.match(r"^00:00( — .+)?$", titles[0])
    assert any(t == "Peter Thiel und die Investoren in Kalifornien" for t in titles[1:])


def test_bullets_stay_within_the_budget() -> None:
    def block(facts: list[tuple[str, str, str]]) -> dict:
        return {
            "heading": "Peter Thiel und die Investoren in Kalifornien",
            "bullets": [{"text": t, "fact_ids": [i]} for i, _k, t in facts[:6]],
        }

    document = _run(_recording(40), ScriptedProvider(overrides={"block": block}))
    budget = compose.VolumeBudget(40 * 19_000 / MIN, document.stats["blocks"])
    for section in document.sections:
        if section.role == roles.TOPICS:
            points = [ln for ln in section.lines if not ln.parent and ln.kind == "bullet"]
            assert len(points) <= max(budget.bullets_per_block, doclint.POINTS_PER_SECTION[1])


# ── T2 phase headings and sub-points ────────────────────────────────


def test_a_generic_heading_is_asked_again_then_takes_the_entity_fallback() -> None:
    def block(facts: list[tuple[str, str, str]]) -> dict:
        return {
            "heading": "Diskussion",
            "bullets": [{"text": t, "fact_ids": [i]} for i, _k, t in facts[:3]],
        }

    provider = ScriptedProvider(overrides={"block": block})
    document = _run(_recording(40), provider)
    systems = [system for step, _p, system in provider.calls if step == "block"]
    assert any(prompts.heading_retry("de") in s for s in systems)
    assert document.stats["headings_fallback"] == document.stats["blocks"]
    titles = [s.title or "" for s in document.sections if s.role == roles.TOPICS]
    assert titles and all(re.match(r"^\d\d:\d\d — Peter Thiel$", t) for t in titles)


def test_the_comparison_headings_are_accepted() -> None:
    data = json.loads(
        (REPO / "tests/fixtures/meeting_doc/doclint/r03_comparison.json").read_text("utf-8")
    )
    by_id = {f["id"]: _fact(f["text"], f["start_ms"], quote=f["quote"]) for f in data["facts"]}
    gate = pipeline._Gate(language="de")
    for section in data["sections"]:
        facts = [by_id[i] for ln in section["lines"] for i in ln["fact_ids"]]
        assert pipeline._heading_faults(section["title"], facts, gate) == [], section["title"]


def _table(name: str | None = "Peter Thiel") -> roles_table.RolesTable:
    return roles_table.RolesTable(
        speakers={
            "SPEAKER_1": roles_table.Speaker("SPEAKER_1", 0.8, 20, 0.1, roles_table.NARRATOR),
            "SPEAKER_3": roles_table.Speaker(
                "SPEAKER_3", 0.2, 5, 0.6, roles_table.GUEST, name=name
            ),
        }
    )


def test_a_quote_child_is_written_from_its_facts_quote_with_speaker_and_time() -> None:
    parent = _fact("Palantir wird 2004 in Palo Alto gegründet", 7 * MIN)
    said = _fact(
        "Thiel nennt Palantir nach den Palantíri",
        7 * MIN + 31_000,
        quote="die Palantíri sind mächtige Steine, mit denen man in die Vergangenheit "
        "schauen kann und tausende Kilometer überbrücken kann, sagt er",
        speaker_label="SPEAKER_3",
    )
    by_id = {f.item_key: f for f in (parent, said)}
    parsed = schema.BlockOut(
        heading="Gründung von Palantir",
        bullets=[
            schema.TopicBullet(
                text=parent.text,
                fact_ids=[parent.item_key],
                children=[
                    schema.SubPoint(
                        text="ignored model words", fact_ids=[said.item_key], quote_of=said.item_key
                    ),
                    schema.SubPoint(
                        text="Palantir wird 2004 in Palo Alto gegründet", fact_ids=[parent.item_key]
                    ),
                ],
            )
        ],
    )
    gate = pipeline._Gate(language="de")
    [(text, ids, children)] = pipeline._block_bullets(parsed, by_id, "de", gate, _table())
    assert text == parent.text
    assert children == [
        (
            "„die Palantíri sind mächtige Steine, mit denen man in die Vergangenheit schauen "
            "kann und tausende Kilometer überbrücken kann, sagt er“ — Peter Thiel (07:31)",
            [said.item_key],
            pipeline.QUOTE,
        )
    ]
    long = compose.quote_child(_fact("x", 0, quote=" ".join(["Wort"] * 25)), "Ada Lovelace", "de")
    assert long == f"„{' '.join(['Wort'] * 20)} …“ — Ada Lovelace (00:00)"
    assert gate.children_restated == 1  # the child restating its parent is dropped
    # A speaker nobody named gets no quote: a label is never written.
    [(_t, _i, unnamed)] = pipeline._block_bullets(parsed, by_id, "de", gate, _table(None))
    assert unnamed == []


# ── T3 subjects and narrator attribution ────────────────────────────


def _window(*lines: tuple[str, str, str | None]) -> Window:
    return Window(
        index=0,
        turns=tuple(
            Turn(n, label, name, text, n * 10_000, n * 10_000 + 9_000, line=n)
            for n, (label, name, text) in enumerate(lines)
        ),
    )


GENERVT = "Er ist genervt, dass er plötzlich seine Schuhe am Flughafen ausziehen muss."


def test_a_pronoun_sentence_with_its_subject_named_is_that_persons() -> None:
    window = _window(
        (
            "SPEAKER_1",
            None,
            "Peter Thiel fliegt 2002 nach dem Verkauf von PayPal oft durch die USA.",
        ),
        ("SPEAKER_1", None, GENERVT),
    )
    fact = schema.Fact(
        kind=schema.KEY_POINT,
        text="Peter Thiel ist genervt, dass er am Flughafen plötzlich die Schuhe ausziehen muss",
        subject="Peter Thiel",
        quote=GENERVT,
        turn=1,
        certainty="opinion",
    )
    [kept] = verify.verify_facts([fact], window=window, meeting_date=DAY, language="de")
    assert kept.subject == "Peter Thiel" and not kept.evidence_only
    assert kept.attributed_to is None  # "Speaker 1" is a label, never a holder
    table = roles_table.build(window.turns, [], "podcast_broadcast")
    [fixed], changed = pipeline._narrator_attribution([kept], table, "podcast_broadcast")
    assert fixed.attributed_to == "Peter Thiel" and changed == 1


def test_a_pronoun_with_no_antecedent_in_the_window_is_evidence() -> None:
    window = _window(("SPEAKER_1", None, GENERVT))
    fact = schema.Fact(
        kind=schema.KEY_POINT,
        text="Er ist genervt, dass er am Flughafen plötzlich die Schuhe ausziehen muss",
        subject="Peter Thiel",  # nowhere in this window
        quote=GENERVT,
        turn=0,
    )
    [kept] = verify.verify_facts([fact], window=window, meeting_date=DAY, language="de")
    assert kept.subject is None and kept.evidence_only
    assert verify.SUBJECT_UNRESOLVED in kept.flags


def test_a_guests_own_opinion_stays_the_guests() -> None:
    quote = "Ich finde, Palantir ist heute das mächtigste Datenunternehmen der Welt."
    window = _window(
        ("SPEAKER_1", None, "Das ist Felix Holtermann vom Handelsblatt."),
        ("SPEAKER_3", "Felix Holtermann", quote),
    )
    fact = schema.Fact(
        kind=schema.KEY_POINT,
        text="Palantir ist laut Holtermann heute das mächtigste Datenunternehmen der Welt",
        quote=quote,
        turn=1,
        certainty="opinion",
    )
    [kept] = verify.verify_facts(
        [fact], window=window, meeting_date=DAY, language="de",
        name_candidates=frozenset({"Felix Holtermann"}),
    )  # fmt: skip
    assert kept.attributed_to == "Felix Holtermann"
    table = roles_table.build(window.turns, [], "podcast_broadcast")
    [same], changed = pipeline._narrator_attribution([kept], table, "podcast_broadcast")
    assert same.attributed_to == "Felix Holtermann" and changed == 0


# ── T4 roles table, type cues, paragraph 1 ──────────────────────────


def _r03_like() -> tuple[list[Turn], list[VerifiedFact], list[tuple[int, int]]]:
    turns = [
        Turn(0, "UNKNOWN", None, "Ich bin Chris Hansen von Dateline NBC.", 5_000, 11_000),
        Turn(1, "UNKNOWN", None, "Jetzt im Kino.", 12_000, 14_000),
        Turn(2, "SPEAKER_2", None, "Simplicissimus Podcast.", 34_000, 36_000),
    ]
    t = 40_000
    for n in range(30):
        turns.append(
            Turn(
                3 + n,
                "SPEAKER_1",
                None,
                f"Peter Thiel und Alex Karp gründen {2004 + n % 3} die Firma Palantir.",
                t,
                t + 15_000,
            )
        )
        t += 16_000
        if n == 10:
            turns.append(
                Turn(
                    100,
                    "SPEAKER_1",
                    None,
                    "Das ist Felix Holtermann vom Handelsblatt.",
                    t,
                    t + 3_000,
                )
            )
            t += 4_000
            for k in range(5):
                turns.append(
                    Turn(
                        101 + k,
                        "SPEAKER_3",
                        None,
                        "Thiel wollte die Daten zusammenführen.",
                        t,
                        t + 8_000,
                    )
                )
                t += 9_000
        if n == 20:
            turns.append(Turn(200, "SPEAKER_9", None, "The goal is to instill fear.", t, t + 3_000))
            t += 4_000
    intro = _fact(
        "Felix Holtermann vom Handelsblatt wird vorgestellt",
        next(x.start_ms for x in turns if x.index == 100),
        person=Person(
            name="Felix Holtermann", organisation="Handelsblatt", self_introduction=False
        ),
    )
    return turns, [intro], [(5_000, 33_000)]


def test_r03s_roles_are_narrator_guest_advert_and_clip_and_karp_is_nobody() -> None:
    turns, intros, adverts = _r03_like()
    table = roles_table.build(turns, intros, "lecture_webinar", adverts)
    assert table.role_of("SPEAKER_1") == roles_table.NARRATOR
    assert table.role_of("SPEAKER_3") == roles_table.GUEST
    assert table.speakers["SPEAKER_3"].name == "Felix Holtermann"
    assert table.role_of("UNKNOWN") == roles_table.ADVERT
    assert table.role_of("SPEAKER_9") == roles_table.CLIP
    assert not any(s.name == "Alex Karp" for s in table.speakers.values())


def test_cues_make_r03_a_podcast_and_a_single_voice_with_slides_a_lecture() -> None:
    turns, intros, adverts = _r03_like()
    table = roles_table.build(turns, intros, "lecture_webinar", adverts)
    verdict, cues = classify.type_cues(turns, table, adverts)
    assert verdict == "podcast_broadcast" and {"show", "guest", "clips", "advert"} <= set(
        cues["podcast"]
    )
    talk = [
        Turn(
            n,
            "SPEAKER_1",
            None,
            f"Auf der nächsten Folie sehen wir Punkt {n}.",
            n * 20_000,
            n * 20_000 + 19_000,
        )
        for n in range(20)
    ]
    lecture = roles_table.build(talk, [], "podcast_broadcast")
    assert classify.type_cues(talk, lecture)[0] == "lecture_webinar"


def test_r03s_first_paragraph_names_type_show_speakers_guest_and_themes() -> None:
    turns, intros, adverts = _r03_like()
    table = roles_table.build(turns, intros, "podcast_broadcast", adverts)
    text = compose.orientation_p1(
        language="de",
        recording_type="podcast_broadcast",
        table=table,
        subject="die Gründung von Palantir und Peter Thiel",
        themes=[
            "der 11. September",
            "Thiels Idee einer Datenanalyse",
            "die Gründung von Palantir",
            "Alex Karps Werdegang",
        ],
        show=compose.show_name(turns),
    )
    assert text.startswith("Podcast-Folge (Simplicissimus) über die Gründung von Palantir")
    assert "Erzähler/in und als Gast Felix Holtermann (Handelsblatt)" in text
    assert 25 <= len(text.split()) <= 60 and "Vortrag" not in text
    assert "Alex Karp" not in text.split("Themen")[0]  # a subject, never a speaker


def test_r02s_host_presents_and_a_meeting_has_participants() -> None:
    walk = [
        Turn(
            n,
            "SPEAKER_1",
            None,
            f"I think the 65 GT is our best boat, feature {n}.",
            n * 15_000,
            n * 15_000 + 14_000,
        )
        for n in range(12)
    ]
    mitchell = _fact(
        "Mitchell introduces himself", 0,
        person=Person(name="Mitchell", role="broker", organisation="Springbrook Marine Group", self_introduction=True),
    )  # fmt: skip
    table = roles_table.build(walk, [mitchell], "presentation_demo")
    assert table.role_of("SPEAKER_1") == roles_table.HOST
    assert roles_table.standing(mitchell, table) == "presenter"
    meeting = [
        Turn(
            n,
            f"SPEAKER_{n % 2 + 1}",
            ["Ada", "Ben"][n % 2],
            "Wir planen das Budget.",
            n * 10_000,
            n * 10_000 + 9_000,
        )
        for n in range(10)
    ]
    table = roles_table.build(meeting, [], "meeting")
    assert {s.role for s in table.speakers.values()} == {roles_table.PARTICIPANT}
    assert compose.speakers_of(table, "de") == (["Ada", "Ben"], [])


# ── T5 orientation paragraph 2 ──────────────────────────────────────


def test_rung_1_follows_the_blocks_rung_2_names_their_top_facts_rung_3_is_code() -> None:
    def summary(facts: list, system: str) -> dict:
        if prompts.strict_suffix("de") in system:
            return {
                "summary": [{"sentence": "Olaf Scholz erfindet etwas", "fact_ids": [facts[0][0]]}]
            }
        return {"summary": [{"sentence": "Olaf Scholz erfindet etwas", "fact_ids": [facts[0][0]]}]}

    provider = ScriptedProvider(overrides={"summary": summary})
    document = _run(_recording(40), provider)
    systems = [system for step, _p, system in provider.calls if step == "summary"]
    assert "Die Teile der Aufnahme, in dieser Reihenfolge" in systems[0]
    assert prompts.strict_suffix("de") in systems[1]
    assert document.stats["summary_ladder"] == "composed"
    top = document.sections[0]
    second = top.text.split("\n\n")[1]
    sentences = [ln for ln in top.lines if ln.kind == "summary"]
    assert 3 <= len(sentences) <= 6 and "\n\n" not in second
    assert all(ln.fact_ids for ln in sentences)
    assert not any(doclint.has_label(ln.text) for ln in sentences)


def test_the_d1_hook_names_a_subject_and_the_linter_rereads_the_document() -> None:
    """D1's line.subject goes to the pipeline's hook, which re-extracts the
    window told to name every subject."""
    quote = "Er ist genervt, dass er plötzlich seine Schuhe am Flughafen ausziehen muss"
    meeting = {
        "language": "de",
        "transcript": [
            {"speaker": "SPEAKER_1", "t_start_ms": 0, "t_end_ms": 9_000,
             "text": "Peter Thiel fliegt 2002 nach dem Verkauf von PayPal oft durch die USA."},
            {"speaker": "SPEAKER_1", "t_start_ms": 10_000, "t_end_ms": 19_000, "text": quote + "."},
        ],
    }  # fmt: skip

    def extract(_facts: list, system: str) -> dict:
        named = prompts.subject_suffix("de") in system
        return {
            "topic_title": "",
            "noise": [],
            "facts": [
                {"kind": "key_point", "quote": quote, "turn": 1, "explicit": False,
                 "text": ("Peter Thiel ist genervt, dass er am Flughafen plötzlich die Schuhe ausziehen muss"
                          if named else "Er ist genervt, dass er am Flughafen plötzlich die Schuhe ausziehen muss"),
                 "subject": "Peter Thiel" if named else None},
            ],
        }  # fmt: skip

    provider = ScriptedProvider(overrides={"extract": extract})
    document = _run(meeting, provider, family=types.family_for_recording_type("podcast_broadcast"))
    section = render_section_with(
        document, "- Er ist genervt, dass er 2002 die Schuhe am Flughafen ausziehen muss"
    )
    document.sections = [section]
    asyncio.run(doclint.enforce(document, regenerate=document.regenerator))
    texts = [ln.text for s in document.sections for ln in s.lines]
    assert (
        "- Peter Thiel ist genervt, dass er am Flughafen plötzlich die Schuhe ausziehen muss"
        in texts
    )
    assert document.stats["lint"]["regenerated"] >= 1


def render_section_with(document: pipeline.DocumentResult, bullet: str) -> Any:
    from note_service.domain.meeting_doc.render import Line, RenderedSection

    fact = document.facts[0]
    other = _fact("Peter Thiel verkauft PayPal 2002 für 1,5 Milliarden Dollar", 0)
    document.facts.append(other)
    lines = (
        Line(bullet, "bullet", (fact.item_key,)),
        Line(f"- {other.text}", "bullet", (other.item_key,)),
    )
    return RenderedSection(
        "gen:x", roles.TOPICS, "", title="Peter Thiel und die Kontrollen", lines=lines
    )


# ── From r03 on the stack model (2026-09-27) ────────────────────────


def test_themes_packed_into_one_quoted_string_are_split() -> None:
    packed = "Datensammlung”, „Geheimdienste”, „Militär”, „Technologische Lösungen”, „Autoritä"
    assert compose.clean_themes([packed]) == [
        "Datensammlung", "Geheimdienste", "Militär", "Technologische Lösungen"
    ]  # fmt: skip
    assert compose.clean_themes(["die Gründung von Palantir"]) == ["die Gründung von Palantir"]


def test_a_name_another_fact_of_the_block_says_is_cited_not_refused() -> None:
    said = _fact("Peter Thiel gründet 2004 die Firma Palantir", 0)
    other = _fact("Der Chef der Firma ist Alex Karp", 60_000)
    by_id = {f.item_key: f for f in (said, other)}
    gate = pipeline._Gate(language="de")
    parsed = schema.BlockOut(
        heading="Gründung von Palantir",
        bullets=[
            schema.TopicBullet(
                text="Peter Thiel gründet 2004 Palantir mit Alex Karp", fact_ids=[said.item_key]
            )
        ],
    )
    [(_text, ids, _children)] = pipeline._block_bullets(parsed, by_id, "de", gate, _table())
    assert ids == [said.item_key, other.item_key]


def test_the_unknown_label_is_never_a_participant() -> None:
    turns = [
        Turn(n, "SPEAKER_1", None, "Erzählung über Palantir 2004.", n * 20_000, n * 20_000 + 19_000)
        for n in range(10)
    ]
    turns += [
        Turn(
            20 + n,
            "UNKNOWN",
            None,
            "The goal is to instill fear.",
            300_000 + n * 5_000,
            303_000 + n * 5_000,
        )
        for n in range(5)
    ]
    table = roles_table.build(turns, [], "podcast_broadcast")
    assert table.role_of("UNKNOWN") == roles_table.CLIP
    assert table.role_of("SPEAKER_1") == roles_table.NARRATOR


def test_german_names_are_told_from_nouns_by_their_company() -> None:
    from note_service.domain.meeting_doc import support

    texts = [
        "Viele Menschen sehen es. Die Menschen fliehen. 3000 Menschen sterben.",
        "Peter Thiel gründet Palantir. Dann trifft Thiel die USA. Später sagt Thiel etwas.",
        "Im brennenden Gebäude. Das Gebäude fällt. Ein Gebäude steht.",
    ]
    candidates = support.recording_names(texts)
    assert {"Menschen", "Gebäude", "Thiel"} <= candidates
    assert support.proper_names(texts, candidates, "de") >= {"Thiel"}
    assert not support.proper_names(texts, candidates, "de") & {"Menschen", "Gebäude"}
