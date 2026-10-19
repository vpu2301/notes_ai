"""F2-03 — important propositions are not lost: every fact has an auditable stage outcome;
a high-risk line no writable fact came from is asked for once (and nothing is invented
when the line is absent); German nouns and foreign-language evidence no longer block
composition when the final check reads every line; central claims stay in the note.
"""

from __future__ import annotations

from collections import Counter

from note_service.domain.meeting_doc import (
    overview,
    pipeline,
    schema,
    support,
    verify,
)
from note_service.domain.meeting_doc.render import Line, RenderedSection
from note_service.domain.meeting_doc.windows import Turn, Window

PROMISE = (
    "And here is my promise. If we win the House and the Senate, both of them, I will "
    "issue a dividend to every adult citizen for $5,000."
)
HOST = "Bei einer Kundgebung in Ohio hat Präsident Robert Calder ein Wahlversprechen abgegeben."
OTHER = "Die Opposition setzt auf niedrigere Mieten und günstigere Medikamente im Wahlkampf."


def _window(*texts: tuple[str, str | None]) -> Window:
    return Window(
        0,
        tuple(
            Turn(
                n,
                f"SPEAKER_{n % 2 + 1}",
                None,
                text,
                n * 15_000,
                n * 15_000 + 14_000,
                line=n,
                language=lang,
            )  # fmt: skip
            for n, (text, lang) in enumerate(texts)
        ),
    )


def _fact(turn: Turn, text: str, **kw: object) -> verify.VerifiedFact:
    return verify.VerifiedFact(
        kind=kw.pop("kind", schema.KEY_POINT),  # type: ignore[arg-type]
        text=text,
        quote=turn.text[:60],
        turn=turn.index,
        start_ms=turn.start_ms,
        end_ms=turn.end_ms,
        speaker_label=turn.speaker_label,
        speaker_name=None,
        line=turn.number,
        **kw,  # type: ignore[arg-type]
    )


# ── recovery: lines only, never an invented proposition ────────────


def test_a_promise_line_with_only_a_copied_quote_is_a_recovery_target() -> None:
    window = _window((HOST, None), (PROMISE, "en"), (OTHER, None))
    copied = _fact(window.turns[1], PROMISE, copied=True)
    [(target, lines)] = pipeline.recovery_targets([window], [copied], "de")
    assert target is window and lines == [1]


def test_a_line_a_fact_already_covers_is_not_asked_again() -> None:
    window = _window((HOST, None), (PROMISE, "en"))
    written = _fact(window.turns[1], "Calder verspricht 5.000 Dollar, falls …")
    assert pipeline.recovery_targets([window], [written], "de") == []


def test_without_the_promise_in_the_input_nothing_is_targeted() -> None:
    window = _window((HOST, None), (OTHER, None))
    assert pipeline.recovery_targets([window], [], "de") == []


def test_recovery_is_bounded() -> None:
    lines = [(f"If we win, I will pay {n},000 dollars to every adult citizen right away.", "en")
             for n in range(10)]  # fmt: skip
    targets = pipeline.recovery_targets([_window(*lines)], [], "de")
    assert sum(len(t[1]) for t in targets) == pipeline.RECOVERY_LINES_MAX
    assert len(targets) <= pipeline.RECOVERY_CALLS_MAX


# ── the gate under the final check ─────────────────────────────────


def _gate(final: bool, people: frozenset[str] = frozenset()) -> pipeline._Gate:
    return pipeline._Gate(language="de", fidelity=True, final=final, people=people)


def test_a_german_noun_is_not_a_name_when_the_final_check_reads_the_line() -> None:
    window = _window((OTHER, None))
    fact = _fact(window.turns[0], "Die Opposition setzt auf niedrigere Mieten.")
    line = "Im Wahlkampf setzt die Opposition auf niedrigere Mieten."
    assert _gate(final=False).reason(line, [fact]) == "name"
    assert _gate(final=True).reason(line, [fact]) is None
    # A name of the recording on the wrong facts still blocks the line.
    named = "Laut Brandt setzt die Opposition auf niedrigere Mieten."
    assert _gate(final=True, people=frozenset({"Brandt"})).reason(named, [fact]) == "name"


def test_a_line_on_foreign_evidence_is_left_to_the_meaning_check() -> None:
    window = _window((PROMISE, "en"))
    fact = _fact(window.turns[0], PROMISE, source_language="en")
    line = "Calder verspricht jedem erwachsenen Bürger 5.000 Dollar, falls seine Partei beide Kammern gewinnt."
    # Without the final check the word gates block it (German nouns, English evidence).
    assert _gate(final=False).reason(line, [fact]) in ("name", "unsupported")
    assert _gate(final=True).reason(line, [fact]) is None


# ── what became of every fact ──────────────────────────────────────


def test_every_fact_has_a_stage_outcome_without_text() -> None:
    window = _window((HOST, None), (PROMISE, "en"), (OTHER, None))
    written = _fact(window.turns[0], "Calder gab ein Wahlversprechen ab.")
    unverified = _fact(window.turns[1], "Calder verspricht 5.000 Dollar.", source_language="en",
                       flags=[verify.MEANING_UNVERIFIED])  # fmt: skip
    unverified.meaning = "budget"
    merged = _fact(window.turns[2], "Die Opposition will Mieten senken.", flags=[verify.MERGED])
    survivor = _fact(window.turns[2], "Die Opposition setzt auf niedrigere Mieten.",
                     also=(merged.item_key,))  # fmt: skip
    section = RenderedSection(
        "overview", "overview", "x",
        lines=(Line("Calder gab ein Wahlversprechen ab.", "summary", (written.item_key,)),),
    )  # fmt: skip
    document = pipeline.DocumentResult(
        sections=[section], facts=[written, unverified, merged, survivor]
    )
    fates = {f["key"]: f for f in pipeline.fates(document)}
    assert fates[written.item_key]["placement"] == "written"
    assert fates[written.item_key]["section"] == "overview"
    # A budget failure is told apart from a contradiction.
    assert fates[unverified.item_key]["placement"] == "review_unverified"
    assert fates[unverified.item_key]["meaning"] == "budget"
    assert fates[merged.item_key]["placement"] == "merged"
    assert fates[merged.item_key]["merged_into"] == survivor.item_key
    assert fates[survivor.item_key]["placement"] == "suggested"
    assert all("text" not in f and "quote" not in f for f in fates.values())


def test_the_meaning_check_records_why_it_decided_nothing() -> None:
    import asyncio

    from note_service.domain.meeting_doc import prompts

    from .meeting_doc_fakes import ScriptedProvider

    window = _window((PROMISE, "en"))
    pending = _fact(
        window.turns[0], "Calder verspricht 5.000 Dollar.", flags=[verify.MEANING_PENDING]
    )
    budget = pipeline.MeaningBudget(limit=0)
    [out] = asyncio.run(
        pipeline._confirm_meaning(
            ScriptedProvider(), [pending], window, "de", Counter(),
            task=prompts.task("de"), repair=True, budget=budget,
        )
    )  # fmt: skip
    assert out.meaning == "budget" and verify.MEANING_UNVERIFIED in out.flags


# ── central claims and the overview ────────────────────────────────


def test_a_central_claim_joins_even_a_full_topic() -> None:
    window = _window((PROMISE, "en"), (OTHER, None))
    claim = _fact(window.turns[0], "Calder verspricht 5.000 Dollar, falls seine Partei gewinnt.")
    filler = _fact(window.turns[1], "Die Opposition will Mieten senken.")
    full = [(f"- Punkt {n}", [filler.item_key], []) for n in range(8)]
    for keep, expected in ((False, 8), (True, 9)):
        topics: pipeline.Topics = [("Wahl", list(full), [filler.item_key])]
        pipeline._append_salient(topics, [claim, filler], _gate(final=True), keep_central=keep)
        assert len(topics[0][1]) == expected
    assert pipeline.central(claim, "de") and not pipeline.central(filler, "de")


def test_a_call_to_action_is_no_overview_while_a_claim_is_available() -> None:
    window = _window((HOST, None), (OTHER, None))
    cta = _fact(window.turns[0], "Zuhörer sollen ihre Meinung in die Kommentare schreiben.",
                kind=schema.NEXT_STEP)  # fmt: skip
    claim = _fact(window.turns[1], "Die Opposition setzt auf niedrigere Mieten.")
    sentences = overview.composed_sentences([cta, claim], language="de")
    assert [ids for _s, ids in sentences] == [[claim.item_key]]
    alone = overview.composed_sentences([cta], language="de")
    assert [ids for _s, ids in alone] == [[cta.item_key]]


def test_support_knows_german_capitalises_nouns() -> None:
    assert "de" in support.NOUNS_CAPITALISED and "en" not in support.NOUNS_CAPITALISED


def test_two_paraphrases_of_one_spoken_promise_go_to_the_duplicate_check() -> None:
    from note_service.domain.meeting_doc import merge

    window = _window((PROMISE, "en"), (OTHER, None))
    turn = window.turns[0]
    trump = _fact(
        turn,
        "Donald Trump versprach jedem erwachsenen US-Bürger 5000 Dollar, falls die Republikaner beide Kammern gewinnen.",
    )
    unnamed = _fact(
        turn,
        "Ein Kandidat verspricht eine Dividende von 5000 US-Dollar, wenn seine Partei Repräsentantenhaus und Senat gewinnt.",
    )
    other = _fact(window.turns[1], "Die Opposition setzt auf niedrigere Mieten.")
    assert (0, 1) in merge.candidates([trump, unnamed, other])
    # The code's veto still holds: a different amount is a different statement.
    changed = _fact(
        turn, "Ein Kandidat verspricht 500 Dollar, wenn seine Partei beide Kammern gewinnt."
    )
    assert merge.candidates([trump, changed]) == []
