"""Nothing real is dropped, nothing unsupported is written (Summary Engine v2, Q2).

Lines instead of turns, noise confirmed by code, a fact budget that
follows density, a meaning check on extraction, and a support gate on
every line a model composes.
"""

from __future__ import annotations

import asyncio
from datetime import date

from note_service.domain.meeting_doc import merge, pipeline, prompts, roles, schema, support, verify
from note_service.domain.meeting_doc.windows import Turn, Window, build_windows

from .meeting_doc_fakes import ScriptedProvider, as_result, load_fixture

DAY = date(2026, 9, 22)
ROLE_MAP = {"decisions": roles.DECISIONS, "action_items": roles.ACTION_ITEMS}


def _piece(line: int, text: str, start_ms: int, end_ms: int, name: str | None = None) -> Turn:
    return Turn(
        index=line,
        speaker_label="SPEAKER_1",
        speaker_name=name,
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        line=line,
    )


def _run(meeting: dict, provider: ScriptedProvider, **kw: object) -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=provider,
            role_by_key=ROLE_MAP,
            language=meeting.get("language", "en"),
            meeting_date=DAY,
            **kw,  # type: ignore[arg-type]
        )
    )


# ── T1: lines, not turns ────────────────────────────────────────────

MONOLOGUE = " ".join(f"Satz Nummer {i} erzählt etwas Neues über den Hafen." for i in range(180))


def _monologue_windows() -> list[Window]:
    assert 8_500 <= len(MONOLOGUE) <= 9_500
    turn = Turn(0, "SPEAKER_1", "Jonas", MONOLOGUE, 0, 300_000)
    return build_windows([turn])


def test_a_monologue_is_four_numbered_lines_and_every_window_has_context() -> None:
    built = _monologue_windows()
    pieces = {t.line: t for w in built for t in w.turns}
    assert len(pieces) == 4
    assert sorted(pieces) == [0, 1, 2, 3]
    assert {t.index for t in pieces.values()} == {0}
    for window in built:
        assert len(window.turns) >= 2
        numbers = [line.split("]")[0] for line in window.render().splitlines()]
        assert len(numbers) == len(set(numbers)), "a bracket number is printed twice"


def test_a_flag_on_one_piece_leaves_the_other_pieces_facts() -> None:
    window = Window(
        index=0,
        turns=(
            _piece(1, "der Hafen in Emden streikt heute", 0, 10_000),
            _piece(2, "hm ja", 10_000, 11_000),
            _piece(3, "die Gewerkschaft fordert acht Prozent mehr", 11_000, 20_000),
        ),
    )
    facts = [
        schema.Fact(
            kind="key_point",
            text="Der Hafen in Emden streikt",
            quote="der Hafen in Emden streikt",
            turn=1,
        ),
        schema.Fact(
            kind="key_point",
            text="Die Gewerkschaft fordert acht Prozent",
            quote="die Gewerkschaft fordert acht Prozent",
            turn=3,
        ),
    ]
    kept = verify.verify_facts(
        facts, window=window, meeting_date=DAY, noise_lines=frozenset({2}), language="de"
    )
    assert [f.line for f in kept] == [1, 3]


def test_a_quote_on_the_wrong_line_takes_the_timestamps_of_the_piece_that_has_it() -> None:
    window = Window(
        index=0,
        turns=(
            _piece(4, "the first piece talks about ferries", 0, 20_000),
            _piece(5, "the second piece talks about ticket prices", 20_000, 40_000),
        ),
    )
    fact = schema.Fact(
        kind="key_point",
        text="Ticket prices were discussed",
        quote="talks about ticket prices",
        turn=4,
    )
    [kept] = verify.verify_facts([fact], window=window, meeting_date=DAY)
    assert (kept.line, kept.start_ms, kept.end_ms) == (5, 20_000, 40_000)


# ── T2: noise policy in code ────────────────────────────────────────

GERMAN = (
    "Die Gewerkschaft hat für heute zu einem Warnstreik aufgerufen und die Arbeitgeber haben "
    "bisher kein neues Angebot vorgelegt, das ist der Stand am Morgen in den Häfen"
)
UKRAINIAN = (
    "Сьогодні в місті знову відключили світло, і люди чекають на новини про те, коли все "
    "повернеться до норми, а влада поки що нічого не каже про терміни"
)


def _confirm(piece: Turn, reason: str, language: str = "de") -> tuple[list, list]:
    # The window around the flag is mostly the German conversation: noise
    # is never most of a window (ADR-0059's rule, now one of confirm_noise's).
    opening = (
        "Guten Morgen, das ist die Lage am Montag. Wir sprechen heute über die Häfen, "
        "den Streik und die Rente, und danach über das Wetter und die Bahn in der Stadt."
    )
    window = Window(index=0, turns=(_piece(0, opening, 0, 5_000), piece))
    return verify.confirm_noise([(piece.line or 0, reason)], window=window, language=language)


def test_a_fifteen_second_correspondent_piece_is_not_background() -> None:
    confirmed, advisory = _confirm(_piece(1, "und das ist wichtig", 5_000, 20_000), "background")
    assert confirmed == [] and advisory == ["background"]


def test_a_three_second_music_cue_is_excluded() -> None:
    confirmed, advisory = _confirm(_piece(1, "(Musik)", 5_000, 8_000), "artifact")
    assert confirmed == [verify.Exclusion(1, 5_000, 8_000, "artifact")] and advisory == []


def test_a_short_piece_with_a_number_is_kept() -> None:
    confirmed, advisory = _confirm(_piece(1, "rund 3.000 Leute", 5_000, 11_000), "background")
    assert confirmed == [] and advisory == ["background"]


def test_a_ukrainian_piece_in_a_german_recording_is_excluded() -> None:
    confirmed, _ = _confirm(_piece(1, UKRAINIAN, 5_000, 20_000), "other_language")
    assert [e.reason for e in confirmed] == ["other_language"]


def test_a_german_piece_flagged_as_another_language_is_advisory() -> None:
    confirmed, advisory = _confirm(_piece(1, GERMAN, 5_000, 20_000), "other_language")
    assert confirmed == [] and advisory == ["other_language"]


def test_a_duplicate_is_confirmed_only_when_it_repeats_an_earlier_piece() -> None:
    window = Window(
        index=0,
        turns=(_piece(0, GERMAN, 0, 10_000), _piece(1, GERMAN + ".", 10_000, 20_000)),
    )
    confirmed, _ = verify.confirm_noise(
        [(1, "duplicate"), (0, "duplicate")], window=window, language="de"
    )
    assert [e.line for e in confirmed] == [1]


def test_exclusions_over_the_cap_keep_only_what_code_can_prove() -> None:
    exclusions = [
        verify.Exclusion(1, 0, 3_000, "background"),
        verify.Exclusion(2, 10_000, 13_000, "other_language"),
    ]
    kept, overridden = verify.cap_exclusions(exclusions, speech_ms=100_000)
    assert [e.reason for e in kept] == ["other_language"] and overridden == 1
    kept, overridden = verify.cap_exclusions(exclusions, speech_ms=1_000_000)
    assert kept == exclusions and overridden == 0


def test_a_run_whose_model_flags_everything_keeps_the_recording() -> None:
    """The audit's failure: a model calling whole passages noise. Code
    confirms only short, empty lines (here the host's 8-second question),
    none of the stories, and the note keeps both."""
    meeting = load_fixture("m06_de_news_podcast")
    provider = ScriptedProvider(noise=[{"turn": n, "reason": "background"} for n in range(40)])
    document = _run(meeting, provider)
    stats = document.stats
    assert stats["noise_flagged"] > stats["noise_confirmed"] > 0
    assert all(e.end_ms - e.start_ms <= verify.MAX_EXCLUDED_MS for e in document.excluded)
    assert stats["excluded_ms"] <= verify.MAX_EXCLUDED_SHARE * stats["speech_ms"]
    text = "\n".join(s.text for s in document.sections)
    assert "Hafenbund" in text and "Frühverrentung" in text


# ── T3: fact budget follows density ─────────────────────────────────


def test_a_dense_window_may_carry_twenty_four_facts() -> None:
    dense = Window(index=0, turns=(_piece(0, "x" * 6_000, 0, 60_000),))
    short = Window(index=0, turns=(_piece(0, "x" * 1_200, 0, 60_000),))
    assert pipeline.fact_budget(dense) == 24
    assert pipeline.extract_tokens(24) >= 6_000
    assert pipeline.fact_budget(short) == 8
    assert schema.extract_schema(max_facts=24)["properties"]["facts"]["maxItems"] == 24
    assert "24" in prompts.extract_prompt("", "de", max_facts=24)


def test_twenty_four_distinct_facts_are_all_kept() -> None:
    sentences = [f"Punkt {chr(65 + i)}{chr(97 + i)} betrifft Hafen Nummer {i}." for i in range(24)]
    window = Window(
        index=0,
        turns=tuple(_piece(i, s, i * 1000, i * 1000 + 900) for i, s in enumerate(sentences)),
    )
    facts = [
        schema.Fact(kind="key_point", text=s.rstrip("."), quote=s.rstrip("."), turn=i)
        for i, s in enumerate(sentences)
    ]
    kept = verify.verify_facts(facts, window=window, meeting_date=DAY, language="de")
    assert len(merge.merge_facts(kept)) == 24


# ── T4: meaning check on extraction ─────────────────────────────────


def test_a_real_paraphrase_passes_and_its_ratio_is_pinned() -> None:
    quote = "I'm honestly a bit worried we won't be ready by November for the launch"
    ratio = support.support_ratio(
        "The current timeline may not support the November launch", quote, "en"
    )
    assert ratio == 0.4 and ratio >= verify.MIN_TEXT_SUPPORT


def test_the_ceiling_an_inverted_relation_from_the_right_words_passes() -> None:
    """Stated so nobody claims more: lexical support cannot see this."""
    turn = "Es gibt viel Kritik, auch an den Wahlkreisen, sagt die Opposition"
    assert support.support_ratio("Kritik an Wahlkreisen", turn, "de") == 1.0
    assert support.new_names("Kritik an Wahlkreisen", turn) == []


def test_a_longer_compound_of_a_said_stem_is_not_caught() -> None:
    """ "Fraktionsvorsitzende" from a turn that says "Fraktion": the stem
    matches and the name rule does not fire, so it is NOT flagged — the
    same ceiling. Pinned so the behaviour is known, not assumed."""
    turn = "die Fraktion kritisiert den Plan"
    claim = "Die Fraktionsvorsitzende kritisiert den Plan"
    assert support.support_ratio(claim, turn, "de") == 1.0
    assert support.new_names(claim, turn) == []


def test_a_new_name_flags_a_key_point_and_drops_an_action() -> None:
    quote = "the launch moves to the spring"
    window = Window(index=0, turns=(_piece(0, quote, 0, 5_000, name="Anna"),))
    assert support.new_names("The launch moves to Berlin", quote) == ["Berlin"]
    stats = verify.VerifyStats()
    kept = verify.verify_facts(
        [
            schema.Fact(
                kind="key_point",
                text="The launch moves to the spring in Berlin",
                quote=quote,
                turn=0,
            ),
            schema.Fact(
                kind="action", text="Move the launch to the spring in Berlin", quote=quote, turn=0
            ),
        ],
        window=window,
        meeting_date=DAY,
        stats=stats,
    )
    assert [f.kind for f in kept] == ["key_point"]
    assert verify.PARAPHRASE_UNSUPPORTED in kept[0].flags
    assert kept[0].confidence == verify.CONF_FLAGGED
    assert stats.dropped_paraphrase == 1 and stats.flagged_paraphrase == 1


def test_a_known_speaker_is_not_a_new_name() -> None:
    quote = "I'll send the offer on Monday"
    window = Window(index=0, turns=(_piece(0, quote, 0, 5_000, name="Anna"),))
    kept = verify.verify_facts(
        [schema.Fact(kind="action", text="Send the offer, says Anna", quote=quote, turn=0)],
        window=window,
        meeting_date=DAY,
    )
    assert len(kept) == 1 and verify.PARAPHRASE_UNSUPPORTED not in kept[0].flags


def test_merge_tokens_are_unchanged() -> None:
    assert merge._tokens is support.merge_tokens
    assert len(support.MERGE_STOP) == 49  # the pre-Q2 merge list, verbatim
    assert support.merge_tokens("Send the Deck to Anna, und die Liste") == frozenset(
        {"send", "deck", "anna", "liste"}
    )


# ── T5: the support gate on every composed line ─────────────────────


def _meeting_with(
    summary=None, topics=None, context=None
) -> tuple[pipeline.DocumentResult, ScriptedProvider]:  # noqa: ANN001
    overrides = {
        k: v for k, v in (("summary", summary), ("topics", topics), ("context", context)) if v
    }
    provider = ScriptedProvider(overrides=overrides)
    return _run(load_fixture("m06_de_news_podcast"), provider), provider


def test_a_sentence_naming_someone_the_facts_do_not_is_dropped() -> None:
    def summary(facts):  # noqa: ANN001, ANN202
        fid, _k, text = facts[0]
        return {
            "summary": [
                {"sentence": f"{text}, sagte Olaf Scholz", "fact_ids": [fid]},
                *({"sentence": t, "fact_ids": [i]} for i, _k, t in facts[1:5]),
            ]
        }

    document, _ = _meeting_with(summary=summary)
    assert document.stats["lines_unsupported"]["name"] == 1
    assert all("Scholz" not in line.text for _key, line in document.lines)


def test_three_failures_in_five_retry_strictly_then_fall_back_to_key_facts() -> None:
    def summary(facts):  # noqa: ANN001, ANN202
        good = [{"sentence": t, "fact_ids": [i]} for i, _k, t in facts[:2]]
        bad = [
            {"sentence": f"Etwas ganz anderes Nummer {n} passierte", "fact_ids": [facts[0][0]]}
            for n in range(3)
        ]
        return {"summary": [*good, *bad]}

    document, provider = _meeting_with(summary=summary, topics=lambda facts: {"topics": []})
    systems = [system for step, _p, system in provider.calls if step == "summary"]
    assert len(systems) == 2
    assert prompts.strict_suffix("de") not in systems[0]
    assert prompts.strict_suffix("de") in systems[1]
    assert document.stats["summary_retries"] == 1
    # F3 amendment §2.9: the third rung is composed prose, never a list.
    assert document.stats["summary_ladder"] == "composed"
    overview = document.sections[0]
    assert overview.section_key == roles.OVERVIEW_KEY
    assert overview.lines and all(line.kind != "key_point" for line in overview.lines)
    assert any(line.kind == "summary" for line in overview.lines)
    assert "\n- " not in overview.text


def test_a_topic_left_with_one_bullet_is_not_a_topic() -> None:
    def topics(facts):  # noqa: ANN001, ANN202
        return {
            "topics": [
                {
                    "title": "Rente",
                    "bullets": [{"text": t, "fact_ids": [i]} for i, _k, t in facts[:2]],
                },
                {
                    "title": "Häfen",
                    "bullets": [{"text": t, "fact_ids": [i]} for i, _k, t in facts[2:4]],
                },
                {
                    "title": "Erfunden",
                    "bullets": [
                        {"text": facts[4][2], "fact_ids": [facts[4][0]]},
                        {"text": "Der Kanzler tritt zurück", "fact_ids": [facts[4][0]]},
                    ],
                },
            ]
        }

    def summary(facts):  # noqa: ANN001, ANN202
        # About a fact no topic uses: since Q3 a bullet the summary already
        # says is not written again, which would empty the topics here.
        fid, _k, text = facts[6]
        return {"summary": [{"sentence": text, "fact_ids": [fid]}]}

    document, _ = _meeting_with(topics=topics, summary=summary)
    titles = [s.title for s in document.sections if s.role == roles.TOPICS]
    assert titles == ["Rente", "Häfen"]


def test_the_november_sentence_never_reaches_the_note_of_m06() -> None:
    november = "Der Start im November bleibt das Ziel"

    def summary(facts, system):  # noqa: ANN001, ANN202
        good = [{"sentence": t, "fact_ids": [i]} for i, _k, t in facts[:2]]
        if prompts.strict_suffix("de") in system:
            return {"summary": good}
        return {"summary": [{"sentence": november, "fact_ids": [facts[0][0]]}, *good]}

    document, _ = _meeting_with(summary=summary)
    written = [line.text for _key, line in document.lines if line.kind == "summary"]
    assert len(written) == 2
    assert all("November" not in line.text for _key, line in document.lines)


def test_a_framing_its_key_facts_do_not_carry_is_not_written() -> None:
    def context(facts):  # noqa: ANN001, ANN202
        return {
            "conversation_type": "Podcast",
            "subject": "Rente",
            "themes": [],
            "framing": "Ein Gespräch mit Olaf Scholz über die Weltlage.",
            "key_fact_ids": [facts[0][0]],
        }

    document, _ = _meeting_with(context=context)
    # The model's sentence is not written; the code-composed first
    # paragraph (F3 amendment §2.9) stands in its place.
    framings = [line.text for _key, line in document.lines if line.kind == "framing"]
    assert all("Scholz" not in text for text in framings)
    assert document.stats["lines_unsupported"]["name"] >= 1


def test_the_result_carries_exclusions_and_coverage_as_numbers() -> None:
    document, _ = _meeting_with()
    stats = document.stats
    assert stats["speech_ms"] > 0
    assert stats["excluded_ranges"] == []
    assert len(stats["facts_by_third"]) == 3 and sum(stats["facts_by_third"]) == len(
        [f for f in document.facts if f.kind not in (schema.COMPLETION, schema.JUDGEMENT)]
    )
    assert stats["prompt_version"] == prompts.PROMPT_VERSION
