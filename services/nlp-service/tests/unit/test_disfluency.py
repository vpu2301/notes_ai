"""Disfluency stage: a conversation reads clean without a word being touched."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from uuid import UUID

from nlp_service.pipeline.base import AbbreviationSnapshot, ProcessingContext, StageInput, Word
from nlp_service.pipeline.orchestrator import idempotence_key
from nlp_service.stages import disfluency
from nlp_service.stages.disfluency import DisfluencyStage

REPO = Path(__file__).resolve().parents[4]
FIXTURE = json.loads((REPO / "tests" / "fixtures" / "nlp" / "fillers.json").read_text("utf-8"))


def _w(text: str, i: int) -> Word:
    return Word(text=text, start_s=i * 0.4, end_s=i * 0.4 + 0.3, probability=0.9)


def _ctx(*, conversation: bool = True, language: str = "en") -> ProcessingContext:
    return ProcessingContext(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        language=language,  # type: ignore[arg-type]
        category=None,
        reference_date=date(2026, 9, 25),
        is_partial=False,
        abbreviation_snapshot=AbbreviationSnapshot(entries=(), fingerprint="x"),
        pipeline_version="t",
        conversation=conversation,
    )


def _run(text: str, **kw: object):  # noqa: ANN202
    words = tuple(_w(tok, i) for i, tok in enumerate(text.split()))
    return asyncio.run(DisfluencyStage().process(_ctx(**kw), StageInput(text=text, words=words)))  # type: ignore[arg-type]


def test_the_table_is_the_shared_fixture() -> None:
    assert {k: set(v) for k, v in disfluency.FILLERS.items()} == {
        k: set(v) for k, v in FIXTURE["fillers"].items()
    }


def test_fillers_are_hidden_and_keep_their_timing() -> None:
    out = _run("uh so this is, um, the swim platform")
    assert out.text == "So this is, the swim platform"
    hidden = [w for w in out.words if w.hidden]
    assert [w.text for w in hidden] == ["uh", "um,"]
    assert hidden[0].start_s == 0.0 and hidden[1].start_s == 1.6  # timings untouched
    assert len(out.words) == 8  # nothing deleted
    assert out.metadata == {"disfluency.hidden": 2}


def test_an_immediate_repeat_hides_its_first_copy() -> None:
    out = _run("this is this is the tender garage and and it takes a a Williams")
    assert out.text == "This is the tender garage and it takes a Williams"


def test_a_repeat_across_a_filler_still_collapses() -> None:
    out = _run("the boat uh the boat is incredible")
    assert out.text == "The boat is incredible"


def test_segment_initial_casing_only_touches_the_first_letter() -> None:
    out = _run("questions or inquiries about this Pardo 65 GT")
    assert out.text == "Questions or inquiries about this Pardo 65 GT"
    assert out.words[0].text == "questions"  # the word itself is untouched


def test_dictation_is_left_alone() -> None:
    out = _run("uh the the patient", conversation=False)
    assert out.text == "uh the the patient" and not any(w.hidden for w in out.words)
    assert out.metadata == {}


def test_a_word_that_is_a_filler_in_one_language_is_speech_in_another() -> None:
    # "er" is "he" in German.
    out = _run("er sagte äh nichts", language="de")
    assert out.text == "Er sagte nichts"


def test_without_timings_the_text_is_still_cleaned() -> None:
    out = asyncio.run(
        DisfluencyStage().process(_ctx(), StageInput(text="um it is it is fine", words=()))
    )
    assert out.text == "It is fine" and out.words == ()


def test_the_cache_key_separates_conversation_from_dictation() -> None:
    initial = StageInput(text="uh hi", words=())
    assert idempotence_key(_ctx(conversation=True), initial) != idempotence_key(
        _ctx(conversation=False), initial
    )
