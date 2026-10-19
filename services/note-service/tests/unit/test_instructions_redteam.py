"""N5 red team, engine end: the gate alone holds. Each of the 40 hostile texts
(eval/instructions/v1/hostile.json) is passed verbatim as wording guidance — the compiler
bypassed — to a scripted writer that obeys it and writes the planted strings into the
framing, the summary and the bullets. No planted string may reach a line of the note."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import pytest

from note_service.domain import note_instructions as ni
from note_service.domain.meeting_doc import pipeline, roles, types

from .meeting_doc_fakes import REPO, ScriptedProvider, as_result, load_fixture

HOSTILE = json.loads((REPO / "eval" / "instructions" / "v1" / "hostile.json").read_text("utf-8"))
# What an obedient writer adds when a text plants nothing specific.
DEFAULT_PLANT = ("the contract was signed on 3 March", "Quillon Marsh approved it")


def worst_case_profile(text: str) -> ni.WritingProfile:
    """The hostile text as up to 12 guidance lines, as if the compiler had passed it on."""
    lines = [ni.sanitize_line(ln, max_chars=ni.MAX_GUIDANCE_CHARS) for ln in text.splitlines()]
    return ni.WritingProfile.model_validate({"guidance": [ln for ln in lines if ln][:12]})


def obedient_writer(plants: list[str]) -> ScriptedProvider:
    """A writer that follows the hostile guidance: every planted string, cited to real facts."""
    attack = [f"Note that {p}." for p in plants]

    def context(facts: list[tuple[str, str, str]]) -> dict[str, Any]:
        return {"conversation_type": "meeting", "subject": "", "themes": [],
                "framing": " ".join(attack), "key_fact_ids": [f[0] for f in facts[:2]]}  # fmt: skip

    def summary(facts: list[tuple[str, str, str]]) -> dict[str, Any]:
        ids = [f[0] for f in facts[:1]]
        return {"summary": [{"sentence": a, "fact_ids": ids} for a in attack]
                + [{"sentence": t, "fact_ids": [fid]} for fid, _k, t in facts[:2]]}  # fmt: skip

    def block(facts: list[tuple[str, str, str]]) -> dict[str, Any]:
        if not facts:
            return {"heading": "", "bullets": []}
        return {"heading": attack[0][:60],
                "bullets": [{"text": a, "fact_ids": [facts[0][0]]} for a in attack]
                + [{"text": t, "fact_ids": [fid]} for fid, _k, t in facts[:3]]}  # fmt: skip

    return ScriptedProvider(overrides={"context": context, "summary": summary, "block": block})


def _run(profile: ni.WritingProfile, provider: ScriptedProvider) -> Any:
    return asyncio.run(
        pipeline.run(
            as_result(load_fixture("m01_en_product_sync")),
            provider=provider,
            role_by_key={"decisions": roles.DECISIONS, "action_items": roles.ACTION_ITEMS},
            language="en",
            meeting_date=date(2026, 9, 15),
            family=types.family_for_recording_type("meeting"),
            recording_type="meeting",
            recording_type_source="classifier",
            profile=profile,
        )
    )


def _lines(document: Any) -> list[str]:
    return [ln.text for s in document.sections for ln in s.lines] + [
        s.title or "" for s in document.sections
    ]


@pytest.mark.parametrize("item", HOSTILE["texts"], ids=[h["id"] for h in HOSTILE["texts"]])
def test_no_planted_string_survives_the_gate(item: dict[str, Any]) -> None:
    plants = [p for p in item["planted"] if len(p) > 2] or list(DEFAULT_PLANT)
    document = _run(worst_case_profile(item["text"]), obedient_writer(plants))
    written = "\n".join(_lines(document)).casefold()
    for plant in plants:
        assert plant.casefold() not in written, (item["id"], plant)
    # The attack reached the gate and was dropped there, not skipped.
    assert sum(int(n) for n in (document.stats.get("lines_unsupported") or {}).values()) > 0
    # The note still says what was said: every line cites a fact.
    assert all(ln.fact_ids for s in document.sections for ln in s.lines if ln.kind != "heading")


def test_the_corpus_is_forty_texts_across_seven_kinds() -> None:
    kinds = {h["category"] for h in HOSTILE["texts"]}
    assert len(HOSTILE["texts"]) == 40 and len(kinds) == 7
    assert all(h["expected_reasons"] or h["planted"] for h in HOSTILE["texts"])
