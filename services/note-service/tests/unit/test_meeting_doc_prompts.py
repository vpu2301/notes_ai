"""Prompts carry no content, and a run carries only its own recording
(Summary Engine v2, Q1 T4 — the closure of audit finding P0-1).

On 2026-09-22 a news podcast's note said "Der Start im November bleibt
das Ziel". It was the German summary prompt's own example sentence, not
another workspace's recording (docs/security/2026-09-22-november-sentence.md).
These tests keep both halves of that conclusion true: the examples are
invented and caught when copied, and every prompt a run sends is built
from that run's transcript alone.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date

from note_service.domain.meeting_doc import pipeline, prompts, roles, schema, verify, windows

from .meeting_doc_fakes import (
    EVAL_FIXTURES,
    REPO,
    ScriptedProvider,
    as_result,
    data_blocks,
    facts_in,
    load_fixture,
)

# PROMPT_VERSION → fingerprint of every prompt table and schema. Changing
# either without the other fails: bump the version, add a line here.
PINNED: dict[str, str] = {
    "2026-10-6": "ee603fa84683802279d59428d0a349f0140a89337dc631fc388982b9af00c6e3",
    "2026-10-7": "60b79697daedf5861220735f1a49251f8b443be27cc1fed103ad12cf878efafa",
    "2026-10-8": "a70b5d83639b736ec6a43fc333d315eab42816200129619e4684b69c038604f5",
    "2026-10-9": "7c4ac09f26e9ca193775855634075d063f612f32f9ed36cbdfb35912aa5f7aaf",
    "2026-10-10": "4790f2eccc17f5b6079420cac2db8c5d2566d080dd180895ae14250f64bd6a21",
    "2026-10-11": "8bde8a1ffe8c52f52c854db56259bab8368b8d0753f4e5099c2fcf1efcade7b5",
    "2026-10-12": "1acfc550bc80b3253c1465b50211cd14800c82dd4423150cb3080fa1390999ee",
    "2026-10-13": "fdeefa1c1d2906fae6f2280798c0b01e92ddde5c0bfcdd4e776a9e26e856d5c3",  # F2: restate suffix, small-talk shot, sub-points
    "2026-10-14": "43d58e09d2cb4e8f75ff549bcdc5271a6416b5274c57392507315935a2f952a6",  # F3: figure/introduction/next_step rules, intro hint, presentation_demo
    "2026-10-15": "43d58e09d2cb4e8f75ff549bcdc5271a6416b5274c57392507315935a2f952a6",  # F3: figure-details follow-up
    "2026-10-16": "43d58e09d2cb4e8f75ff549bcdc5271a6416b5274c57392507315935a2f952a6",  # F3: person-details follow-up
    "2026-10-17": "43d58e09d2cb4e8f75ff549bcdc5271a6416b5274c57392507315935a2f952a6",  # F3: call-to-action line hint
    "2026-10-18": "43d58e09d2cb4e8f75ff549bcdc5271a6416b5274c57392507315935a2f952a6",  # F3: call-to-action follow-up
    "2026-10-19": "7145b51eb8abe1ee535a7a6b35773879b0e860a93ff16a44c05510b8b264c33f",  # F3 amendment: scene example, specific claims
    "2026-10-20": "847a3d2c44452868a551f8752f9d54c199f3d756ca8cfd1914f1eb133a34533a",  # F3 amendment: block headings, summary skeleton
    "2026-10-21": "61f351fc9b999eb4463868fc93fb4573c4931353ebf766f3364b0fbe04afc4f3",  # document standard §1: title 30–80 characters, one colon
}

FIXTURE_DIRS = (EVAL_FIXTURES, REPO / "tests" / "fixtures" / "meeting_doc")
ROLE_MAP = {"decisions": roles.DECISIONS, "action_items": roles.ACTION_ITEMS}


def _transcript_texts() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for folder in FIXTURE_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            data = json.loads(path.read_text("utf-8"))
            for turn in data.get("transcript", []):
                out.append((path.name, turn.get("text", "")))
    return out


def _run(meeting: dict, provider: ScriptedProvider) -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=provider,
            role_by_key=ROLE_MAP,
            language=meeting.get("language", "en"),
            meeting_date=date(2026, 9, 22),
        )
    )


def _grams(text: str) -> set[str]:
    return prompts._grams(text)


def _transcript_grams(meeting: dict) -> set[str]:
    return set().union(*(_grams(t["text"]) for t in meeting["transcript"]))


# ── The examples ────────────────────────────────────────────────────


def test_the_examples_are_the_invented_company_in_every_language() -> None:
    for language, table in prompts.EXAMPLES.items():
        assert set(table) == set(prompts.EXAMPLES["en"]), language
        systems = prompts.extract_system(language) + prompts.extract_prompt("", language)
        systems += prompts.summary_system(language) + prompts.context_system(language)
        systems += prompts.block_system(language)
        for sentence in table.values():
            # One source of truth: every example is shown by some prompt.
            assert sentence in systems, (language, sentence)
    for old in ("November", "листопад", "Russia", "Russland", "Росії", "two million"):
        for language in prompts.EXAMPLES:
            text = (
                prompts.extract_system(language)
                + prompts.extract_prompt("", language)
                + prompts.summary_system(language)
                + prompts.context_system(language)
                + prompts.topics_system(language)
            )
            assert old not in text, (language, old)


def test_the_type_list_does_not_open_with_a_meeting() -> None:
    for language in prompts.EXAMPLES:
        first = prompts.CONVERSATION_TYPES[language].split(",")[0].strip().casefold()
        assert first in ("podcast", "подкаст"), language
        assert prompts.CONVERSATION_TYPES[language] in prompts.context_system(language)


def test_the_phrase_set_is_built_from_the_examples_and_is_specific() -> None:
    assert "quillhaven" in prompts.EXAMPLE_PHRASES
    assert "ferrytale" in prompts.EXAMPLE_PHRASES
    assert prompts.echoes_example(prompts.EXAMPLES["de"]["summary_right"])
    assert prompts.echoes_example(prompts.EXAMPLES["uk"]["worry_text"])
    # A way of speaking is not an example.
    for line in (
        "Costs were estimated at well over budget.",
        "The participants talked about the budget.",
        "Der Start im November bleibt das Ziel.",
        "Ich habe ehrlich gesagt Sorge, dass wir das nicht schaffen.",
    ):
        assert not prompts.echoes_example(line), line


def test_no_example_phrase_appears_in_any_fixture() -> None:
    """If a synthetic fixture trips this, change the fixture, not the set:
    a guard that drops real speech is worse than no guard."""
    hits = [
        (name, phrase)
        for name, text in _transcript_texts()
        for phrase in prompts.EXAMPLE_PHRASES
        if f" {phrase} " in f" {verify.normalise_quote(text)} "
    ]
    assert hits == []


def test_a_fact_copied_from_an_example_is_dropped_in_verify() -> None:
    quote = "the tin box for the game was agreed yesterday"
    window = windows.Window(
        index=0,
        turns=(windows.Turn(0, "SPEAKER_1", None, quote, 0, 5_000),),
    )
    stats = verify.VerifyStats()
    kept = verify.verify_facts(
        [
            schema.Fact(
                kind=schema.KEY_POINT,
                text=prompts.EXAMPLES["en"]["proposal_right"],
                quote=quote,
                turn=0,
            ),
            schema.Fact(kind=schema.KEY_POINT, text="The tin box was agreed", quote=quote, turn=0),
        ],
        window=window,
        meeting_date=date(2026, 9, 22),
        stats=stats,
    )
    assert [f.text for f in kept] == ["The tin box was agreed"]
    assert stats.dropped_example == 1


def test_an_echoed_example_never_reaches_the_note() -> None:
    meeting = load_fixture("m02_de_kundenprojekt")
    echoed = prompts.EXAMPLES["de"]["summary_right"]

    def summary(facts: list[tuple[str, str, str]]) -> dict:
        # One echo among four: under the Q2 retry threshold (30 %), so
        # the echo is dropped and the rest is written.
        real = facts[0][0]
        return {
            "summary": [
                {"sentence": echoed, "fact_ids": [real]},
                *({"sentence": text, "fact_ids": [fid]} for fid, _k, text in facts[:3]),
            ]
        }

    document = _run(meeting, ScriptedProvider(overrides={"summary": summary}))
    overview = next(s for s in document.sections if s.section_key == roles.OVERVIEW_KEY)
    assert echoed not in overview.text
    assert all(echoed not in line.text for _key, line in document.lines)
    assert document.stats["example_echo_dropped"] == 1
    # The real sentence beside it is still written.
    assert any(line.kind == "summary" for _key, line in document.lines)


# ── A run carries only its own recording ────────────────────────────


def test_prompts_carry_only_this_recording() -> None:
    a = load_fixture("m01_en_product_sync")
    b = load_fixture("m02_de_kundenprojekt")
    shared = _transcript_grams(a) & _transcript_grams(b)

    provider_a = ScriptedProvider()
    document_a = _run(a, provider_a)
    assert document_a.windows_total > 0 and document_a.facts

    renderings = {
        w.render() for w in windows.build_windows(windows.turns_from_result(as_result(a)))
    }
    produced = {f.item_key: f.text for f in document_a.facts}
    b_grams = _transcript_grams(b) - shared

    a_lines = {t["text"] for t in a["transcript"]}
    for step, prompt, system in provider_a.calls:
        if step in ("figures", "people", "steps"):
            # F3 details: this window's own lines, nothing else.
            for body in data_blocks(prompt):
                for line in body.splitlines():
                    listed = re.match(r"^\s*\d+\.\s*(?:line:\s*)?(?P<said>.+)$", line)
                    if listed:
                        said = listed["said"].strip()
                        assert any(said in t or t in said for t in a_lines), step
            continue
        if step == "extract":
            # The data block is exactly one of A's windows, as rendered.
            blocks = data_blocks(prompt)
            assert len(blocks) == 1 and blocks[0] in renderings
        else:
            # Reduce steps see only ids and texts of facts THIS run verified.
            listed = facts_in(prompt)
            assert listed, step
            for fact_id, _kind, text in listed:
                assert produced.get(fact_id) == text, step
            body = "\n".join(data_blocks(prompt))
            assert len(body.splitlines()) == len(listed), step
        # No system string carries another recording's words.
        assert not (_grams(system) & b_grams), step

    # Every written line rests on facts of this run.
    for _key, line in document_a.lines:
        assert set(line.fact_ids) <= set(produced), line

    # And nothing is carried over from one run to the next.
    provider_b = ScriptedProvider()
    document_b = _run(b, provider_b)
    assert document_b.windows_total > 0
    a_grams = _transcript_grams(a) - shared
    for step, prompt, system in provider_b.calls:
        assert not (_grams(prompt) & a_grams), step
        assert not (_grams(system) & a_grams), step
    for _key, line in document_b.lines:
        assert not (_grams(line.text) & a_grams), line


def test_prompt_version_changes_with_prompt_text() -> None:
    assert prompts.PROMPT_VERSION in PINNED, "bump PROMPT_VERSION and pin its fingerprint"
    assert prompts.fingerprint() == PINNED[prompts.PROMPT_VERSION], (
        "prompt text or schema changed: bump PROMPT_VERSION and pin the new fingerprint"
    )


def test_the_security_note_exists() -> None:
    note = REPO / "docs" / "security" / "2026-09-22-november-sentence.md"
    assert note.is_file()
    assert "not an isolation incident" in note.read_text("utf-8").casefold()
