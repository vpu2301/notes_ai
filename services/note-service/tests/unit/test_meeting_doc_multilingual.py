"""Multilingual evidence: every transcript language is a source, the note is
written in one output language, and a claim restated across languages is
checked by meaning — never by shared words alone, never dropped for its language.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from note_service.domain.meeting_doc import pipeline, prompts, roles, schema, verify, windows
from note_service.domain.meeting_doc.windows import Turn, Window
from note_service.routers import notes_generation

from .meeting_doc_fakes import ScriptedProvider

DAY = date(2026, 10, 18)
ROLE_MAP = {"decisions": roles.DECISIONS, "action_items": roles.ACTION_ITEMS}

HOST = (
    "Und dann ist da noch dieses ungewöhnliche Wahlversprechen der Republikaner. Wenn die "
    "Republikaner in beiden Kammern gewinnen, gibt es Geld für alle erwachsenen Amerikaner."
)
PROMISE = (
    "And here is my promise. If the Republicans win the House of Representatives and the "
    "United States Senate, both of them, I will issue a dividend to every adult citizen in "
    "the United States of America for $5,000."
)
AFTER = (
    "Aber wie genau das umgesetzt und vor allem finanziert werden soll, das lässt Trump "
    "offen. Es gilt weder politisch noch finanziell als realistisch."
)
QUOTE = "I will issue a dividend to every adult citizen"
FAITHFUL = (
    "Donald Trump verspricht jedem erwachsenen US-Bürger eine Dividende von 5.000 Dollar, "
    "falls die Republikaner Repräsentantenhaus und Senat gewinnen."
)
DISTORTED = "Donald Trump verspricht seinen Wählern eine Dividende von 5.000 Dollar."


def _turn(line: int, text: str, start: int, language: str | None = None) -> Turn:
    return Turn(
        index=line,
        speaker_label="SPEAKER_2" if language == "en" else "SPEAKER_1",
        speaker_name="Trump" if language == "en" else "Moderator",
        text=text,
        start_ms=start,
        end_ms=start + 15_000,
        line=line,
        language=language,
    )


def _window() -> Window:
    return Window(
        index=0,
        turns=(_turn(0, HOST, 0), _turn(1, PROMISE, 15_000, "en"), _turn(2, AFTER, 30_000)),
    )


def _fact(text: str = FAITHFUL, turn: int = 1, quote: str = QUOTE) -> schema.Fact:
    return schema.Fact(kind="key_point", text=text, quote=quote, turn=turn, explicit=False)


def _verify(fact: schema.Fact, **kw: Any) -> tuple[list[verify.VerifiedFact], verify.VerifyStats]:
    stats = verify.VerifyStats()
    kept = verify.verify_facts(
        [fact], window=_window(), meeting_date=DAY, stats=stats, language="de", **kw
    )
    return kept, stats


# ── S1-02: a language is never noise ────────────────────────────────


def test_off_the_language_field_still_confirms_the_exclusion() -> None:
    confirmed, _ = verify.confirm_noise([(1, "other_language")], window=_window(), language="de")
    assert [e.reason for e in confirmed] == ["other_language"]


def test_on_a_model_flag_for_another_language_is_only_advisory() -> None:
    confirmed, advisory = verify.confirm_noise(
        [(1, "other_language")], window=_window(), language="de", multilingual=True
    )
    assert confirmed == [] and advisory == ["other_language"]


def test_on_real_noise_is_still_confirmed() -> None:
    window = Window(
        index=0,
        turns=(
            _turn(0, HOST, 0),
            _turn(1, AFTER, 15_000),
            _turn(2, AFTER, 30_000),
            Turn(3, "SPEAKER_3", None, "Hallo, ja, hallo?", 45_000, 47_000, line=3),
        ),
    )
    confirmed, _ = verify.confirm_noise(
        [(2, "duplicate"), (3, "background")], window=window, language="de", multilingual=True
    )
    assert sorted(e.reason for e in confirmed) == ["background", "duplicate"]


def test_on_another_language_is_not_provable_above_the_cap() -> None:
    exclusions = [
        verify.Exclusion(1, 0, 3_000, "other_language"),
        verify.Exclusion(2, 3_000, 6_000, "duplicate"),
    ]
    kept, overridden = verify.cap_exclusions(exclusions, speech_ms=10_000, multilingual=True)
    assert [e.reason for e in kept] == ["duplicate"] and overridden == 1
    kept, _ = verify.cap_exclusions(exclusions, speech_ms=10_000)
    assert [e.reason for e in kept] == ["other_language", "duplicate"]


def test_the_prompt_names_no_language_as_noise_and_keeps_the_quote_as_spoken() -> None:
    for language, reason in (
        ("en", "background speech, another language,"),
        ("de", "Hintergrundgespräch, andere Sprache,"),
    ):
        on = prompts.extract_system(language, multilingual=True)
        off = prompts.extract_system(language)
        assert reason in off and reason not in on
        assert prompts._SOURCE_LANGUAGE_RULE[language] in on
        assert prompts._ANSWER_LANGUAGE_LINE[language] in off
    uk = prompts.extract_system("uk", multilingual=True)
    assert "фонова мова, інша мова," not in uk and prompts._SOURCE_LANGUAGE_RULE["uk"] in uk
    # The small-model profile drops whichever noise rule is in use.
    small = prompts.extract_system("de", noise=False, multilingual=True)
    assert prompts._NOISE_RULE_MULTILINGUAL["de"] not in small


def test_the_schema_offers_no_language_reason_but_still_reads_one() -> None:
    offered = schema.extract_schema(noise_reasons=schema.OFFERED_NOISE_REASONS)
    reasons = offered["properties"]["noise"]["items"]["properties"]["reason"]["enum"]
    assert "other_language" not in reasons and "background" in reasons
    legacy = schema.ExtractOut.model_validate_json(
        '{"topic_title": "x", "facts": [], "noise": [{"turn": 1, "reason": "other_language"}]}'
    )
    assert legacy.noise[0].reason == "other_language"


def test_a_saved_other_language_exclusion_still_reads() -> None:
    ranges = notes_generation._excluded({"excluded_ranges": [[0, 4_000, "other_language"]]})
    assert [(r.start_ms, r.end_ms, r.reason) for r in ranges] == [(0, 4_000, "other_language")]


# ── S1-03: the word gate is not the judge across languages ──────────


def test_off_a_faithful_translation_fails_the_word_gate() -> None:
    kept, stats = _verify(_fact())
    assert kept == [] and stats.dropped_paraphrase == 1


def test_on_a_translation_is_kept_pending_with_its_original_evidence() -> None:
    kept, stats = _verify(_fact(), multilingual=True, recording_language="de")
    assert len(kept) == 1 and stats.cross_language == 1
    fact = kept[0]
    assert verify.MEANING_PENDING in fact.flags
    assert fact.source_language == "en"
    # Evidence is the English line itself: its words, its line, its time.
    assert fact.quote == QUOTE and fact.line == 1
    assert 15_000 <= fact.start_ms < fact.end_ms <= 30_000
    assert "5.000" in fact.text


def test_on_a_same_language_fact_still_meets_the_word_gate() -> None:
    off_topic = _fact(text="Die Hafenbehörde plant neue Kräne für 2027.", turn=0, quote=HOST[:60])
    kept, stats = _verify(off_topic, multilingual=True, recording_language="de")
    assert kept == [] and stats.dropped_paraphrase == 1 and stats.cross_language == 0


def test_on_an_unsaid_number_is_still_removed_across_languages() -> None:
    kept, stats = _verify(
        _fact(text=FAITHFUL.replace("5.000", "7.000")), multilingual=True, recording_language="de"
    )
    assert stats.numbers_removed == 1
    assert all("7.000" not in f.text for f in kept)


def test_on_a_quote_that_was_not_said_is_still_dropped() -> None:
    kept, stats = _verify(
        _fact(quote="I will give everybody ten thousand dollars"),
        multilingual=True,
        recording_language="de",
    )
    assert kept == [] and stats.dropped_quote == 1


def test_numbers_said_in_words_in_the_source_language_count() -> None:
    turn = _turn(1, "I will issue five thousand dollars to every adult citizen.", 0, "en")
    text, flags = verify.check_numbers(
        "Jeder Erwachsene erhält 5000 Dollar.",
        quote="I will issue five thousand dollars",
        turn=turn,
        language="de",
        source_language="en",
    )
    assert flags == [] and "5000" in text


def test_settling_the_meaning_check() -> None:
    def pending() -> verify.VerifiedFact:
        return _verify(_fact(), multilingual=True, recording_language="de")[0][0]

    supported = verify.settle_meaning(pending(), schema.SUPPORTED)
    assert supported is not None and supported.flags == []
    assert supported.confidence == verify.CONF_INFERRED
    assert verify.settle_meaning(pending(), schema.CONTRADICTED) is None
    for undecided in (schema.INSUFFICIENT, None):
        kept = verify.settle_meaning(pending(), undecided)
        assert kept is not None and verify.MEANING_UNVERIFIED in kept.flags
        assert kept.confidence == verify.CONF_FLAGGED


# ── output language ─────────────────────────────────────────────────


def _result(languages: list[tuple[str | None, int]], recording: str | None = "de") -> dict:
    turns, start = [], 0
    for code, ms in languages:
        turn: dict[str, Any] = {
            "speaker": "SPEAKER_1",
            "start_ms": start,
            "end_ms": start + ms,
            "paragraphs": ["Ein Satz mit genug Wörtern für eine Zeile im Transkript hier."],
        }
        if code:
            turn["language"] = code
        turns.append(turn)
        start += ms
    return {"language": recording, "turns": turns} if recording else {"turns": turns}


def test_an_explicit_choice_wins() -> None:
    assert pipeline.resolve_output_language(_result([(None, 10)]), explicit="uk") == (
        "uk",
        "explicit",
    )


def test_else_the_language_most_of_the_recording_was_spoken_in() -> None:
    assert pipeline.resolve_output_language(_result([(None, 60_000), ("en", 20_000)])) == (
        "de",
        "dominant",
    )
    assert pipeline.resolve_output_language(_result([(None, 10_000), ("en", 50_000)])) == (
        "en",
        "dominant",
    )
    # A tie stays with the recording's own.
    assert (
        windows.dominant_language(
            windows.turns_from_result(_result([(None, 5_000), ("en", 5_000)])), "de"
        )
        == "de"
    )


def test_else_the_documented_default() -> None:
    assert pipeline.resolve_output_language({"turns": []}) == (
        pipeline.DEFAULT_OUTPUT_LANGUAGE,
        "default",
    )


# ── the whole pipeline: German host, English promise ────────────────


def _broadcast() -> dict[str, Any]:
    texts = [(HOST, None), (PROMISE, "en"), (AFTER, None)]
    turns = []
    for n, (text, code) in enumerate(texts):
        turn: dict[str, Any] = {
            "speaker": "SPEAKER_2" if code else "SPEAKER_1",
            "name": "Trump" if code else "Moderator",
            "start_ms": n * 15_000,
            "end_ms": n * 15_000 + 15_000,
            "paragraphs": [text],
        }
        if code:
            turn["language"] = code
        turns.append(turn)
    return {"language": "de", "result_rev": 3, "turns": turns}


def _extract(text: str) -> Any:
    def answer(_facts: Any) -> dict[str, Any]:
        return {
            "topic_title": "Wahlversprechen",
            "facts": [
                {"kind": "key_point", "text": text, "quote": QUOTE, "turn": 1, "explicit": False},
                {
                    "kind": "key_point",
                    "text": "Die Finanzierung des Versprechens von Trump bleibt offen.",
                    "quote": "finanziert werden soll, das lässt Trump offen",
                    "turn": 2,
                    "explicit": False,
                },
            ],
            # A model that still calls the English line noise.
            "noise": [{"turn": 1, "reason": "other_language"}],
        }

    return answer


def _generate(
    text: str = FAITHFUL, checks: Any = None, multilingual: bool = True
) -> tuple[pipeline.DocumentResult, ScriptedProvider]:
    overrides: dict[str, Any] = {"extract": _extract(text)}
    if checks is not None:
        overrides["checks"] = checks
    provider = ScriptedProvider(overrides=overrides)
    document = asyncio.run(
        pipeline.run(
            _broadcast(),
            provider=provider,
            role_by_key=ROLE_MAP,
            output_language="de",
            meeting_date=DAY,
            multilingual=multilingual,
        )
    )
    return document, provider


def _verdict(verdict: str, lines: list[int] | None = None) -> Any:
    return lambda _facts: {
        "checks": [
            {"claim_id": "c1", "verdict": verdict, "evidence_ids": [str(n) for n in lines or [1]],
             "reason": "r", "corrected_claim": None}
        ]
    }  # fmt: skip


def _promise(document: pipeline.DocumentResult) -> list[verify.VerifiedFact]:
    return [f for f in document.facts if f.source_language == "en"]


def test_off_the_english_promise_is_excluded_as_another_language() -> None:
    document, _ = _generate(multilingual=False)
    assert _promise(document) == []
    assert document.stats["facts_dropped_noise"] == 1
    assert document.stats["excluded_language_ms"] == 15_000
    assert document.stats["prompt_version"] == prompts.PREVIOUS_PROMPT_VERSION


def test_on_the_english_promise_reaches_the_note_with_its_english_source() -> None:
    document, provider = _generate(checks=_verdict(schema.SUPPORTED))
    stats = document.stats
    assert stats["excluded_language_ms"] == 0 and stats["facts_dropped_noise"] == 0
    assert stats["noise_other_language_advisory"] == 1
    assert stats["meaning_check"] == {"checked": 1, "supported": 1}
    assert stats["prompt_version"] == prompts.PROMPT_VERSION and stats["fidelity"] is False
    assert stats["output_language"] == "de" and stats["recording_language"] == "de"
    assert stats["input_revision"] == 3
    assert stats["languages"]["en"]["extracted"] == 1
    assert stats["languages"]["en"]["merged"] == 1
    [fact] = _promise(document)
    assert fact.quote == QUOTE and fact.flags == [] and fact.start_ms >= 15_000
    assert not document.partial
    # The check saw the English line and its German neighbours.
    [(_step, prompt, system)] = [c for c in provider.calls if c[0] == "checks"]
    assert PROMISE in prompt and HOST in prompt and FAITHFUL in prompt
    assert system.startswith(prompts.task("de").common)
    assert prompts.task("de").verification in system
    # The extractor was told to keep other languages as evidence.
    extract_system = next(s for step, _p, s in provider.calls if step == "extract")
    assert prompts._SOURCE_LANGUAGE_RULE["de"] in extract_system


def test_on_a_changed_recipient_is_rejected() -> None:
    document, _ = _generate(text=DISTORTED, checks=_verdict(schema.CONTRADICTED))
    assert _promise(document) == []
    assert document.stats["meaning_check"] == {"checked": 1, "contradicted": 1}
    assert document.stats["languages"]["en"]["extracted"] == 1


def test_on_no_answer_keeps_the_claim_for_review_and_the_note_is_partial() -> None:
    document, _ = _generate()  # the scripted model cannot answer the check
    [fact] = _promise(document)
    assert verify.MEANING_UNVERIFIED in fact.flags
    assert document.stats["meaning_check"]["unavailable"] == 1
    assert document.stats["meaning_unverified"] == 1
    assert document.partial


def test_on_a_verdict_citing_a_line_it_was_not_shown_decides_nothing() -> None:
    document, _ = _generate(checks=_verdict(schema.CONTRADICTED, lines=[40]))
    [fact] = _promise(document)
    assert verify.MEANING_UNVERIFIED in fact.flags
    assert document.stats["meaning_check"]["foreign_lines"] == 1


def test_the_trace_says_what_became_of_each_fact_without_text() -> None:
    document, _ = _generate(text=DISTORTED, checks=_verdict(schema.CONTRADICTED))
    outcomes = {(t.line, t.language, t.outcome) for t in document.trace}
    assert (1, "en", "verified") in outcomes
    assert all(isinstance(t.outcome, str) and t.kind for t in document.trace)


def test_an_unverified_claim_is_offered_for_review_not_asserted() -> None:
    from note_service.jobs.generate_note import uncited_rows

    document, _ = _generate()  # no verdict: unverified
    [fact] = _promise(document)
    cited = {i for _key, line in document.lines for i in line.fact_ids}
    assert fact.item_key not in cited
    [row] = [r for r in uncited_rows(document) if r["quote"] == QUOTE]
    assert row["placement"] == "suggested" and verify.MEANING_UNVERIFIED in row["flags"]
