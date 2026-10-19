"""Sprint B2 — the model path per language and family: meeting prompts byte-identical,
narrated addenda only for broadcast/memo, the outline step, the certainty of reported
claims and its verdict."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import pytest

from note_service.domain import note_title
from note_service.domain.meeting_doc import (
    compose,
    pipeline,
    prompts,
    render,
    schema,
    support,
)
from note_service.domain.meeting_doc.verify import VerifiedFact


def _vf(text: str, start_ms: int = 0, **kw: object) -> VerifiedFact:
    fields = {
        "kind": schema.KEY_POINT,
        "text": text,
        "quote": text,
        "turn": 0,
        "start_ms": start_ms,
        "end_ms": start_ms + 1_000,
        "speaker_label": "SPEAKER_1",
        "speaker_name": None,
    }
    fields.update(kw)
    return VerifiedFact(**fields)  # type: ignore[arg-type]


# ── Golden: the meeting families' prompts are what they were before B2 ────────

# sha256 over every meeting-family builder output on this branch before B2 (every
# language, noise and multilingual variant, 3–6 bullets); a narrated addendum must
# never reach them. Bump only with a deliberate meeting-prompt change.
MEETING_PROMPTS_BEFORE_B2 = "53dffeef2c3808372ae6ebfaaad69fb5fb1da217fda1210a07280b39242029de"


def _meeting_prompts() -> dict[str, str]:
    parts: dict[str, str] = {}
    for lang in ("en", "de", "uk"):
        for noise in (True, False):
            for ml in (True, False):
                parts[f"extract/{lang}/noise={noise}/ml={ml}"] = prompts.extract_system(
                    lang, noise=noise, multilingual=ml
                )
        for b in (3, 4, 5, 6):
            parts[f"block/{lang}/{b}"] = prompts.block_system(lang, b)
        parts[f"summary/{lang}"] = prompts.summary_system(lang)
        parts[f"context/{lang}"] = prompts.context_system(lang)
        parts[f"block_heading/{lang}"] = prompts.block_heading_system(lang)
        parts[f"block_bullets/{lang}"] = prompts.block_bullets_system(lang)
    return parts


def test_meeting_family_prompts_are_byte_identical() -> None:
    digest = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in _meeting_prompts().items()}
    whole = hashlib.sha256(json.dumps(digest, sort_keys=True).encode()).hexdigest()
    assert whole == MEETING_PROMPTS_BEFORE_B2


@pytest.mark.parametrize("language", ["en", "de", "uk"])
def test_the_narrated_addenda_sit_between_the_rules_and_the_guard(language: str) -> None:
    plain = prompts.extract_system(language)
    narrated = prompts.extract_system(language, narrated=True)
    addendum = prompts.EXTRACT_NARRATED[language]
    assert addendum not in plain and addendum in narrated
    assert narrated.index(addendum) < narrated.index(prompts.guard(language))
    assert prompts.CONTEXT_NARRATED[language] in prompts.context_system(language, narrated=True)
    assert prompts.SUMMARY_NARRATED[language] in prompts.summary_system(language, narrated=True)
    block = prompts.block_system(language, narrated=True, title="Die Rechte des Rats")
    assert "Die Rechte des Rats" in block and prompts.BLOCK_NARRATED[language] in block
    untitled = prompts.block_system(language, narrated=True)
    assert prompts.BLOCK_NARRATED_LEAD[language]["untitled"] in untitled
    assert prompts.OUTLINE_SYSTEM[language] in prompts.outline_system(language)


def test_the_title_rule_is_added_only_for_narrated_recordings() -> None:
    plain = note_title.system_text("de")
    narrated = note_title.system_text("de", narrated=True)
    assert prompts.TITLE_NARRATED not in plain and prompts.TITLE_NARRATED in narrated
    assert "{narrated}" not in plain and "{narrated}" not in narrated
    # The pinned meeting title prompt is the template without the narrated slot.
    assert prompts._title_prompt() == note_title._SYSTEM.replace("{narrated}", "")


def test_the_narrated_examples_are_quillhaven_and_guarded() -> None:
    for table in (prompts.EXTRACT_NARRATED, prompts.BLOCK_NARRATED, prompts.OUTLINE_SYSTEM):
        for text in table.values():
            for real in ("Trump", "Senat", "Senate", "Republikan", "Republican"):
                assert real not in text
    assert prompts.echoes_example(prompts.EXAMPLES["de"]["narrated_bullet"])
    assert prompts.echoes_example(prompts.EXAMPLES["en"]["outline_levy"])


# ── T2: blocks from the outline ───────────────────────────────────────


def _facts(n: int) -> list[VerifiedFact]:
    return [_vf(f"Fact number {k} about the Quillhaven council", k * 10_000) for k in range(n)]


def test_outline_blocks_follow_the_assignment_and_keep_their_titles() -> None:
    facts = _facts(16)
    ids = [f.item_key for f in facts]
    built = compose.blocks_from_outline(
        facts,
        [
            ("What is at stake", ids[0:4]),
            ("The council's rights", ids[4:8] + ["zz-unknown"]),
            ("The levy decides", ids[8:12] + ids[0:1]),  # duplicate: first wins
            ("What happens next", ids[12:16]),
        ],
    )
    assert built is not None
    blocks, counts = built
    assert [b.title for b in blocks] == [
        "What is at stake",
        "The council's rights",
        "The levy decides",
        "What happens next",
    ]
    assert [len(b.facts) for b in blocks] == [4, 4, 4, 4]
    assert counts == {"sections": 4, "unassigned": 0, "merged": 0, "unknown": 1}
    assert blocks[0].span == (0, 30_000)


def test_unassigned_facts_join_the_section_nearest_in_time() -> None:
    facts = _facts(12)
    ids = [f.item_key for f in facts]
    built = compose.blocks_from_outline(
        facts,
        [("Opening", ids[0:4]), ("Closing", ids[8:12])],  # 4–7 are left unassigned
    )
    assert built is not None
    blocks, counts = built
    assert counts["unassigned"] == 4 and counts["merged"] == 0
    assert [len(b.facts) for b in blocks] == [7, 5]
    assert all(list(b.facts) == sorted(b.facts, key=lambda f: f.start_ms) for b in blocks), (
        "facts inside a block run in time order"
    )


def test_a_section_below_the_block_minimum_merges_into_the_nearest_by_median_time() -> None:
    facts = _facts(12)
    ids = [f.item_key for f in facts]
    built = compose.blocks_from_outline(
        facts,
        [("Opening", ids[0:5]), ("A thin section", ids[5:6]), ("Closing", ids[6:12])],
    )
    assert built is not None
    blocks, counts = built
    assert counts["merged"] == 1 and [b.title for b in blocks] == ["Opening", "Closing"]
    assert [len(b.facts) for b in blocks] == [6, 6]


def test_an_outline_that_assigns_nothing_is_refused() -> None:
    assert compose.blocks_from_outline(_facts(4), [("Nothing", ["none"])]) is None


class _Outliner:
    """Answers the outline call with a script; counts the calls."""

    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers = answers
        self.systems: list[str] = []

    async def complete(self, prompt: str, schema_: Any, **kw: Any) -> str:
        self.systems.append(kw.get("system") or "")
        return json.dumps(self.answers.pop(0))


def _gate(language: str = "en") -> pipeline._Gate:
    return pipeline._Gate(language=language, narrated=True)


def test_the_outline_step_builds_titled_blocks_and_retries_a_faulty_title() -> None:
    facts = _facts(16)
    ids = [f.item_key for f in facts]
    good = {
        "sections": [
            {"title": "Why the levy settles the council vote", "fact_ids": ids[0:4]},
            {"title": "Overview", "fact_ids": ids[4:8]},  # generic → asked again
            {"title": "The council's rights this winter", "fact_ids": ids[8:12]},
            {"title": "What remains open after the vote", "fact_ids": ids[12:16]},
        ]
    }
    retry = {
        "sections": [
            {"title": "Why the levy settles the council vote", "fact_ids": ids[0:4]},
            {"title": "The second step of the argument", "fact_ids": ids[4:8]},
            {"title": "The council's rights this winter", "fact_ids": ids[8:12]},
            {"title": "What remains open after the vote", "fact_ids": ids[12:16]},
        ]
    }
    provider = _Outliner([good, retry])
    gate = _gate()
    blocks = asyncio.run(pipeline._outline(provider, facts, "en", gate=gate, brief=None))
    assert blocks is not None
    assert [b.title for b in blocks][1] == "The second step of the argument"
    assert gate.outline == {
        "sections": 4,
        "unassigned": 0,
        "merged": 0,
        "unknown": 0,
        "retried": True,
        "fallback_titles": 0,
    }
    assert prompts.heading_retry("en") in provider.systems[1]
    assert prompts.OUTLINE_SYSTEM["en"] in provider.systems[0]


def test_too_few_facts_skip_the_outline_without_a_call() -> None:
    provider = _Outliner([])
    gate = _gate()
    assert asyncio.run(pipeline._outline(provider, _facts(11), "en", gate=gate, brief=None)) is None
    assert provider.systems == [] and gate.block_calls == 0 and gate.outline is None


def test_an_outline_refused_twice_falls_back_to_time_blocks() -> None:
    facts = _facts(12)
    provider = _Outliner([{"sections": []}, {"sections": [{"title": "x", "fact_ids": ["n"]}]}])
    gate = _gate()
    assert asyncio.run(pipeline._outline(provider, facts, "en", gate=gate, brief=None)) is None
    assert gate.outline is None and gate.block_failures["outline_short"] == 2


def test_a_title_the_retry_cannot_fix_is_written_by_the_fallback() -> None:
    facts = _facts(12)
    ids = [f.item_key for f in facts]
    sections = [
        {"title": "Other", "fact_ids": ids[0:4]},
        {"title": "The levy and the council majority", "fact_ids": ids[4:8]},
        {"title": "What remains open after the vote", "fact_ids": ids[8:12]},
    ]
    provider = _Outliner([{"sections": sections}, {"sections": sections}])
    gate = _gate()
    blocks = asyncio.run(pipeline._outline(provider, facts, "en", gate=gate, brief=None))
    assert blocks is not None and gate.outline is not None
    assert gate.outline["fallback_titles"] == 1 and gate.headings_fallback == 1
    assert blocks[0].title and blocks[0].title.casefold() != "other"


# ── T4: reported claims and the speaker's verdict ─────────────────────


def test_the_new_certainties_are_in_the_schema_and_the_gate_tables() -> None:
    assert {"reported", "unproven", "refuted"} <= set(schema.CERTAINTIES)
    assert {"reported", "unproven"} <= support.UNSURE_CERTAINTIES
    assert "refuted" not in support.UNSURE_CERTAINTIES
    assert {"unproven", "refuted"} == support.VERDICT_CERTAINTIES
    for lang in ("de", "en", "uk"):
        for kind in ("reported", "unproven", "refuted"):
            clause = support.certainty_clause(kind, "the levy is rigged", lang)
            assert support.has_marker(clause, lang), (lang, kind)
            assert support.has_verdict(clause, kind, lang), (lang, kind)


def test_a_bullet_on_a_judged_claim_gets_the_verdict_suffix() -> None:
    unproven = _vf("Die Briefwahl werde manipuliert", certainty="unproven", attributed_to="Trump")
    refuted = _vf("Die Wahl 2020 sei gestohlen worden", certainty="refuted", attributed_to="Trump")
    line = render.patch_claim("Trump sagt, die Briefwahl werde manipuliert.", [unproven], "de")
    # Without a hedge marker the phrase leads ("Behauptung — unbelegt: …"), once.
    assert line.startswith("Behauptung — unbelegt:") and line.count("unbelegt") == 1
    hedged = render.patch_claim("Laut Trump werde die Briefwahl manipuliert.", [unproven], "de")
    assert hedged.endswith("— unbelegt") and hedged.count("unbelegt") == 1
    line = render.patch_claim("Trump nennt die Wahl 2020 gestohlen.", [refuted], "de")
    assert line.endswith("— widerlegt")
    kept = "Trump nennt die Wahl 2020 gestohlen — widerlegt."
    assert render.patch_claim(kept, [refuted], "de") == kept
    assert render.patch_claim("The election was stolen.", [refuted], "en").endswith("— refuted")


def test_a_summary_sentence_without_the_verdict_is_dropped_as_verdict() -> None:
    gate = pipeline._Gate(language="de", known=frozenset({"Trump"}))
    fact = _vf(
        "Trump behauptet, die Briefwahl werde manipuliert",
        certainty="unproven",
        attributed_to="Trump",
    )
    assert (
        gate.reason("Laut Trump wird die Briefwahl manipuliert.", [fact], claims=True) == "verdict"
    )
    assert (
        gate.reason("Laut Trump wird die Briefwahl manipuliert — unbelegt.", [fact], claims=True)
        is None
    )
    assert gate.counts["verdict"] == 0  # reason() counts nothing; ok() does
    assert not gate.ok("Laut Trump wird die Briefwahl manipuliert.", [fact], claims=True)
    assert gate.counts["verdict"] == 1


def test_the_composed_overview_keeps_the_verdict_once() -> None:
    fact = _vf("die Wahl 2020 sei gestohlen worden", certainty="refuted", attributed_to="Trump")
    sentence = support.certainty_clause(fact.certainty, fact.text, "de", actor="Trump")
    assert sentence.count("widerlegt") == 1 and sentence.endswith("— widerlegt")
    reported = support.certainty_clause("reported", fact.text, "de", actor="Trump")
    assert reported.endswith("— laut Trump") and support.has_marker(reported, "de")
