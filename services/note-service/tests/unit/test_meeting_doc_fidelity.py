"""Meaning, attribution and concise notes: a high-risk claim is checked by meaning
whatever its word overlap and repaired once; an unresolved claim is offered for review,
never asserted; a narrator's view stays the narrator's; a label or a number is nobody's
name; composed prose invents no sequence.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date
from typing import Any

from note_service.domain.meeting_doc import (
    doclint,
    overview,
    pipeline,
    prompts,
    render,
    roles_table,
    schema,
    support,
    verify,
)
from note_service.domain.meeting_doc.render import Line
from note_service.domain.meeting_doc.windows import Turn, Window

from .meeting_doc_fakes import ScriptedProvider

DAY = date(2026, 10, 18)
BOARD = (
    "Quick update from finance. The budget increase for the Leeds office was not approved "
    "by the board yesterday, so hiring stays frozen until January."
)
QUOTE = "The budget increase for the Leeds office was not approved by the board yesterday"


def _window() -> Window:
    return Window(index=0, turns=(Turn(0, "SPEAKER_1", "Dana Price", BOARD, 0, 15_000, line=0),))


def _fact(text: str, *, kind: str = "key_point", quote: str = QUOTE) -> schema.Fact:
    return schema.Fact(kind=kind, text=text, quote=quote, turn=0, explicit=False)


def _verify(fact: schema.Fact, **kw: Any) -> list[verify.VerifiedFact]:
    return verify.verify_facts(
        [fact], window=_window(), meeting_date=DAY, language="en", multilingual=True, **kw
    )


# ── S2-01: high-risk claims are checked by meaning ──────────────────


def test_risk_is_read_from_the_claim_and_from_its_quote() -> None:
    assert support.high_risk("The board did not approve it.", "en")
    assert support.high_risk("Tausende Menschen kamen.", "de")
    assert support.high_risk("Trump könnte die Kompetenzen ausreizen.", "de")
    assert support.high_risk("Нам не потрібні генератори.", "uk")
    assert not support.high_risk("The board met in Leeds.", "en")
    # F1-03: polarity and comparison words route both directions of a pair to the check.
    for claim, language in (
        ("The board approved the budget for Leeds.", "en"),
        ("Die Lage ist besser.", "de"),
        ("Die Lage ist schlechter.", "de"),
        ("Es kamen mehr Menschen.", "de"),
        ("Es kamen weniger Menschen.", "de"),
        ("She supports the plan.", "en"),
        ("She opposes the plan.", "en"),
        ("Ситуація краща.", "uk"),
        ("Ситуація гірша.", "uk"),
    ):
        assert support.high_risk(claim, language), claim
    # The dropped negation is in the quote, not the claim: the quote makes it risky.
    [kept] = _verify(_fact("The board approved the budget increase for Leeds."), fidelity=True)
    assert verify.MEANING_PENDING in kept.flags


def test_without_fidelity_a_same_language_claim_meets_only_the_word_gate() -> None:
    [kept] = _verify(_fact("The board approved the budget increase for Leeds."))
    assert verify.MEANING_PENDING not in kept.flags


def test_a_plain_claim_is_not_sent_to_the_check() -> None:
    plain = _fact("Hiring for the Leeds office stays frozen.", quote="so hiring stays frozen")
    [kept] = _verify(plain, fidelity=True)
    assert verify.MEANING_PENDING not in kept.flags


def _pending(
    text: str = "The board approved the budget increase for Leeds.",
) -> verify.VerifiedFact:
    return _verify(_fact(text), fidelity=True)[0]


def _confirm(
    provider: ScriptedProvider, fact: verify.VerifiedFact, **kw: Any
) -> tuple[list[verify.VerifiedFact], Counter[str]]:
    tally: Counter[str] = Counter()
    out = asyncio.run(
        pipeline._confirm_meaning(
            provider, [fact], _window(), "en", tally, task=prompts.task("en"), **kw
        )
    )
    return out, tally


def _checks(*answers: tuple[str, str | None]) -> Any:
    """The verifier's answers in turn: ``(verdict, corrected_claim)``."""
    queue = iter(answers)

    def answer(_facts: Any) -> dict[str, Any]:
        verdict, corrected = next(queue)
        return {
            "checks": [
                {"claim_id": "c1", "verdict": verdict, "evidence_ids": ["0"],
                 "reason": "negation", "corrected_claim": corrected}
            ]
        }  # fmt: skip

    return answer


def test_a_rejected_claim_is_corrected_once_and_kept_when_the_correction_holds() -> None:
    repaired = "The board did not approve the budget increase for the Leeds office."
    provider = ScriptedProvider(
        overrides={"checks": _checks((schema.CONTRADICTED, repaired), (schema.SUPPORTED, None))}
    )
    [fact], tally = _confirm(provider, _pending(), repair=True)
    assert fact.text == repaired and fact.flags == []
    assert tally["contradicted"] == 1 and tally["repaired"] == 1
    # The correction is checked again, independently: two checks, no other call.
    assert [step for step, _p, _s in provider.calls] == ["checks", "checks"]
    assert repaired in provider.calls[1][1] and BOARD in provider.calls[1][1]


def test_a_correction_that_still_fails_is_kept_for_review_with_its_first_text() -> None:
    provider = ScriptedProvider(
        overrides={
            "checks": _checks(
                (schema.CONTRADICTED, "The board approved it."), (schema.CONTRADICTED, None)
            )
        }
    )
    original = _pending()
    first_text = original.text
    [fact], tally = _confirm(provider, original, repair=True)
    assert verify.MEANING_UNVERIFIED in fact.flags and fact.text == first_text
    assert tally["repair_rejected"] == 1
    # One correction, never a loop until a model agrees.
    assert len(provider.calls) == 2


def test_a_correction_adding_an_unsaid_number_is_refused_by_code() -> None:
    provider = ScriptedProvider(
        overrides={
            "checks": _checks((schema.CONTRADICTED, "The board refused 40,000 pounds for Leeds."))
        }
    )
    [fact], tally = _confirm(provider, _pending(), repair=True)
    assert tally["repair_number"] == 1 and verify.MEANING_UNVERIFIED in fact.flags
    assert len(provider.calls) == 1


def test_a_response_missing_a_claim_is_rejected_whole() -> None:
    provider = ScriptedProvider(
        overrides={"checks": lambda _f: {"checks": []}}  # truncated: no claim answered
    )
    [fact], tally = _confirm(provider, _pending(), repair=True)
    assert tally["malformed"] == 1 and verify.MEANING_UNVERIFIED in fact.flags


def test_an_exhausted_budget_leaves_the_claim_unverified_without_a_call() -> None:
    provider = ScriptedProvider(overrides={"checks": _checks((schema.SUPPORTED, None))})
    budget = pipeline.MeaningBudget(limit=0)
    [fact], tally = _confirm(provider, _pending(), repair=True, budget=budget)
    assert provider.calls == [] and tally["budget"] == 1
    assert verify.MEANING_UNVERIFIED in fact.flags


def test_a_verifier_failure_is_counted_apart_from_a_rejection() -> None:
    _out, tally = _confirm(ScriptedProvider(), _pending(), repair=True)
    assert tally["unavailable"] == 1 and tally["contradicted"] == 0


# ── S2-02: attribution ──────────────────────────────────────────────


def test_a_label_or_a_number_is_nobodys_name() -> None:
    assert support.real_name("1") is None and support.real_name("SPEAKER_2") is None
    assert support.display_actor("1", "de") == "Sprecher/in 1"
    assert support.display_actor("Speaker 2", "en") == "Speaker 2"
    assert support.display_actor("Unknown speaker", "de") is None
    assert support.display_actor("Politische Beobachter", "de") == "Politische Beobachter"


def _opinion(attributed_to: str | None, text: str = "Trump neigt zur Übertreibung.") -> Any:
    return verify.VerifiedFact(
        kind="key_point",
        text=text,
        quote="Ja, Trump neigt natürlich zur Übertreibung",
        turn=0,
        start_ms=0,
        end_ms=5_000,
        speaker_label="SPEAKER_1",
        speaker_name="Speaker 1",
        certainty="opinion",
        attributed_to=attributed_to,
    )


def test_a_holder_is_written_whole_and_a_number_never() -> None:
    line = render.patch_claim("Die Lage ist ernst.", [_opinion("Donald Trump")], "de")
    assert line.endswith("— laut Donald Trump")
    numbered = render.patch_claim("Die Lage ist ernst.", [_opinion("1")], "de")
    assert "laut 1" not in numbered and numbered.endswith("laut Sprecher/in 1")


def test_a_framing_sentence_is_not_labelled_as_a_claim() -> None:
    fact = _opinion("Politische Beobachter")
    ctx = doclint.LintContext(language="de", speech_ms=60_000, facts={fact.item_key: fact})
    framing = Line("Sendung über die Midterm-Wahlen.", "framing", (fact.item_key,))
    summary = Line("Die Lage ist ernst.", "summary", (fact.item_key,))
    assert not doclint._certainty_missing(framing, ctx)
    assert doclint._certainty_missing(summary, ctx)


def _host_table() -> roles_table.RolesTable:
    host = roles_table.Speaker(
        label="SPEAKER_1", share=0.9, turns=10, first_person_share=0.0, role=roles_table.NARRATOR
    )
    return roles_table.RolesTable(speakers={"SPEAKER_1": host})


def test_a_narrators_view_about_somebody_stays_the_narrators() -> None:
    facts = [_opinion("Trump")]
    off, _ = pipeline._narrator_attribution(facts, _host_table(), "podcast_broadcast")
    assert off[0].attributed_to == "Trump"
    on, _ = pipeline._narrator_attribution(
        facts, _host_table(), "podcast_broadcast", fidelity=True, language="de"
    )
    assert on[0].attributed_to == "Erzähler/in"


def test_a_reported_view_stays_with_who_the_narrator_reports() -> None:
    reported = _opinion("Politische Beobachter")
    reported.quote = "Politische Beobachter befürchten, dass sich das Spiel fortsetzen würde"
    on, _ = pipeline._narrator_attribution(
        [reported], _host_table(), "podcast_broadcast", fidelity=True, language="de"
    )
    assert on[0].attributed_to == "Politische Beobachter"


# ── S2-04: no invented sequence ─────────────────────────────────────


def test_composed_prose_has_no_connectives_under_fidelity() -> None:
    facts = [
        verify.VerifiedFact(
            kind="key_point",
            text=f"Die Stadt Lindau plant Maßnahme Nummer {n} für 2027.",
            quote="q",
            turn=n,
            start_ms=n * 60_000,
            end_ms=n * 60_000 + 5_000,
            speaker_label="SPEAKER_1",
            speaker_name=None,
        )
        for n in range(4)
    ]
    # B1 T1: rung 3 never writes a sequence, fidelity or not.
    without = overview.composed_sentences(facts, language="de")
    assert not any(s.startswith(("Zunächst", "Anschließend", "Schließlich")) for s, _ids in without)


# ── S2-03: merge without losing conditions ──────────────────────────

from note_service.domain.meeting_doc import merge  # noqa: E402


def _said(text: str, start: int, kind: str = "key_point") -> verify.VerifiedFact:
    return verify.VerifiedFact(
        kind=kind,
        text=text,
        quote=f"quote at {start}",
        turn=start,
        start_ms=start * 1_000,
        end_ms=start * 1_000 + 900,
        speaker_label="SPEAKER_1",
        speaker_name=None,
    )


POSTAL = "Trump claims without evidence that postal voting is manipulated against Republicans."
POSTAL_AGAIN = (
    "Trump claims without evidence that postal voting is manipulated against the Republicans."
)
POSTAL_PRECISE = (
    "Trump claims without evidence that postal voting is manipulated and forged against "
    "Republicans in 2026."
)


def test_a_repetition_collapses_and_its_line_keeps_both_sources() -> None:
    first, again = _said(POSTAL, 10), _said(POSTAL_AGAIN, 300)
    kept, sources = merge.merge_with_sources([first, again], language="en")
    assert len(kept) == 1 and [s.item_key for s in sources] == [again.item_key]
    assert kept[0].also == (again.item_key,)
    assert sources[0].evidence_only and verify.MERGED in sources[0].flags


def test_the_more_precise_wording_survives_not_the_earliest() -> None:
    early, precise = _said(POSTAL, 10), _said(POSTAL_PRECISE, 300)
    assert merge.precise_first(early, precise, "en")[0] is precise


def test_two_amounts_or_two_conditions_never_merge() -> None:
    amounts = [
        _said("Every adult citizen gets 5,000 dollars from the dividend.", 1),
        _said("Every adult citizen gets 2,000 dollars from the dividend.", 2),
    ]
    assert len(merge.merge_with_sources(amounts, language="en")[0]) == 2
    conditioned = [
        _said("Every adult citizen gets the dividend if both chambers are won.", 1),
        _said("Every adult citizen gets the dividend.", 2),
    ]
    assert not merge.compatible(*conditioned)
    negated = [
        _said("The board approved the budget.", 1),
        _said("The board did not approve the budget.", 2),
    ]
    assert not merge.compatible(*negated)
    # A proposal and a decision are two statements.
    assert not merge.compatible(
        _said("Hire two engineers.", 1, "decision"), _said("Hire two engineers.", 2)
    )


def _judge(relation: str) -> Any:
    def answer(_facts: Any, system: str = "") -> dict[str, Any]:
        return {"pairs": [{"left_id": PAIR[0], "right_id": PAIR[1], "relation": relation,
                           "reason": "r", "merged_text": None}]}  # fmt: skip

    return answer


PAIR: list[str] = []


def test_deduplication_merges_equivalents_and_lets_an_explicit_correction_stand() -> None:
    a = _said(
        "Trump wants the homeland security ministry to search voter rolls for noncitizens.", 1
    )
    b = _said("The homeland security ministry is to search the voter rolls for noncitizens.", 400)
    c = _said("Untersuchungen zeigen, dass Wahlbetrug durch Nichtbürger äußerst selten ist.", 500)
    assert merge.candidates([a, b, c]) == [(0, 1)]
    PAIR[:] = [a.item_key, b.item_key]
    run = lambda relation: asyncio.run(  # noqa: E731
        pipeline._merge_equivalent(
            ScriptedProvider(overrides={"pairs": _judge(relation)}), [a, b, c], "en", tally,
            task=prompts.task("en"),
        )
    )  # fmt: skip
    tally: Counter[str] = Counter()
    kept, sources = run("equivalent")
    assert len(kept) == 2 and len(sources) == 1 and tally["equivalent"] == 1
    kept, sources = run("explicit_correction")
    # The right one corrects the left: it stands; the left is kept as superseded evidence.
    assert b.item_key in {f.item_key for f in kept} and a.item_key not in {f.item_key for f in kept}
    assert verify.SUPERSEDED in sources[0].flags and sources[0].evidence_only
    for relation in ("distinct", "contradiction"):
        kept, sources = run(relation)
        assert len(kept) == 3 and sources == []


def test_a_written_line_cites_every_merged_source() -> None:
    survivor, copy = merge.absorb(_said(POSTAL, 10), _said(POSTAL_AGAIN, 300))
    section = render.RenderedSection(
        section_key="gen:x",
        role="topics",
        text="- x",
        lines=(Line("- x", "bullet", (survivor.item_key,)),),
    )
    [cited] = pipeline._cite_sources([section], [survivor, copy])
    assert cited.lines[0].fact_ids == (survivor.item_key, copy.item_key)


def test_a_suggestion_repeating_a_written_line_becomes_its_source() -> None:
    written, repeat = _said(POSTAL, 10), _said(POSTAL_AGAIN, 300)
    section = render.RenderedSection(
        section_key="gen:x",
        role="topics",
        text="- x",
        lines=(Line("- x", "bullet", (written.item_key,)),),
    )
    facts, sources = pipeline._absorb_repeats([section], [written, repeat])
    assert [f.item_key for f in facts] == [written.item_key]
    assert facts[0].also == (repeat.item_key,) and sources[0].evidence_only


# ── S2-04: headings say what a block is about ───────────────────────

from note_service.domain.meeting_doc import compose  # noqa: E402


def test_a_fallback_heading_names_the_theme_its_facts_carry_not_a_voice() -> None:
    facts = [
        _said("Trump verbreitet die unbelegte Behauptung, die Briefwahl werde manipuliert.", 504),
        _said("Trump hat strengere Briefwahlregeln verfügt.", 520),
    ]
    themed = compose.fallback_heading(
        facts,
        "de",
        frozenset({"Trump"}),
        themes=("Zölle und Inflation", "Briefwahl und Manipulation"),
    )
    assert themed == "Briefwahl und Manipulation"
    # No theme the facts carry: the block's claim, never a stamp and a name.
    plain = compose.fallback_heading(facts, "de", frozenset({"Trump"}))
    assert plain != "Briefwahl und Manipulation" and plain != "Trump"
    assert not plain.startswith("08:24")
