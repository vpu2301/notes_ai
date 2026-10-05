"""Sprint L1 T2 — the small-model profile.

A backend that says ``small_model: true`` (the founder's Mac) gets simpler
work: twelve facts per window, one extraction example, no ``noise`` field,
reduce calls over at most fifteen facts with the heading asked separately
and no sub-points, the strict summary rung first, and a schema-echo retry
after a malformed answer. A capable backend sees exactly what it saw
before: the profile is a switch, never a default.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from note_service.domain.meeting_doc import compose, pipeline, prompts, roles_table, schema
from note_service.domain.meeting_doc.verify import VerifiedFact

from .meeting_doc_fakes import ScriptedProvider, as_result, facts_in, step_of

DAY = date(2026, 9, 27)


@dataclass
class SmallProvider(ScriptedProvider):
    """The scripted model, declaring itself a small local model."""

    small_model: bool = True


def _recording(turns: int) -> dict[str, Any]:
    return {
        "language": "de",
        "transcript": [
            {
                "speaker": ("SPEAKER_1", "SPEAKER_2")[n % 2],
                "t_start_ms": n * 20_000,
                "t_end_ms": n * 20_000 + 19_000,
                "text": f"Im Jahr {2000 + n} traf Peter Thiel in Kalifornien genau {n + 3} "
                "Investoren aus dem Silicon Valley und sprach lange über Daten",
            }
            for n in range(turns)
        ],
    }


def _run(meeting: dict[str, Any], provider: ScriptedProvider) -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            as_result(meeting), provider=provider, role_by_key={}, language="de", meeting_date=DAY
        )
    )


def _fact(text: str, start_ms: int) -> VerifiedFact:
    return VerifiedFact(
        kind=schema.KEY_POINT,
        text=text,
        quote="so wurde es in dem Gespräch erzählt",
        turn=0,
        start_ms=start_ms,
        end_ms=start_ms + 1_000,
        speaker_label="SPEAKER_1",
        speaker_name=None,
    )


# ── extraction: schema and prompt ───────────────────────────────────


def test_small_model_extraction_asks_for_twelve_facts_one_example_and_no_noise() -> None:
    provider = SmallProvider()
    _run(_recording(40), provider)
    extract_schemas = [s for s in provider.schemas if step_of(s) == "extract"]
    assert extract_schemas
    for built in extract_schemas:
        # SQ2 T2: 8–12 by the window's length, one per 500 characters.
        cap = built["properties"]["facts"]["maxItems"]
        assert pipeline.SMALL_MODEL_MIN_FACTS == 8 <= cap <= pipeline.SMALL_MODEL_MAX_FACTS == 12
        assert "noise" not in built["properties"]
        assert "noise" not in built["required"]
    for _step, prompt, system in (c for c in provider.calls if c[0] == "extract"):
        # One example — the proposal that is not a decision — and only that one.
        assert prompts.EXAMPLES["de"]["shot_proposal"] in prompt
        assert prompts.EXAMPLES["de"]["shot_should"] not in prompt
        assert prompts.EXAMPLES["de"]["shot_small_talk"] not in prompt
        # The system prompt no longer asks for a field the schema lacks.
        assert "`noise`" not in system


def test_a_capable_model_sees_the_density_rule_all_examples_and_the_noise_field() -> None:
    """The snapshot: nothing changes for a provider without the flag."""
    provider = ScriptedProvider()
    _run(_recording(40), provider)
    extract_schemas = [s for s in provider.schemas if step_of(s) == "extract"]
    assert extract_schemas
    for built in extract_schemas:
        cap = built["properties"]["facts"]["maxItems"]
        assert pipeline.MIN_FACTS_BUDGET <= cap <= pipeline.MAX_FACTS_BUDGET
        assert "noise" in built["properties"] and "noise" in built["required"]
    for _step, prompt, system in (c for c in provider.calls if c[0] == "extract"):
        assert prompts.EXAMPLES["de"]["shot_proposal"] in prompt
        assert prompts.EXAMPLES["de"]["shot_should"] in prompt
        assert prompts.EXAMPLES["de"]["shot_small_talk"] in prompt
        assert "`noise`" in system


def test_the_schema_switch_and_the_one_shot_prompt_stand_alone() -> None:
    built = schema.extract_schema(max_facts=12, noise=False)
    assert built["properties"]["facts"]["maxItems"] == 12
    assert "noise" not in built["properties"]
    default = schema.extract_schema()
    assert "noise" in default["properties"]
    for language in ("en", "de", "uk"):
        one = prompts.extract_prompt("x", language, one_shot=True)
        every = prompts.extract_prompt("x", language)
        assert len(one) < len(every)
        assert prompts.EXAMPLES[language]["shot_proposal"] in one
        assert prompts.EXAMPLES[language]["shot_estimate_quote"] not in one
        assert prompts.EXAMPLES[language]["shot_estimate_quote"] in every
        # The example guard still knows every example sentence.
        assert prompts.echoes_example(prompts.EXAMPLES[language]["shot_should"])


# ── SCHEMA_INVALID: the retry carries the schema ─────────────────────


@dataclass
class _BrokenOnce:
    """Answers nonsense once, then defers to the scripted model."""

    inner: ScriptedProvider
    small_model: bool = True
    backend: str = "scripted"
    model_id: str = "scripted"
    prompts: list[str] = field(default_factory=list)
    failed: bool = False

    async def complete(self, prompt: str, schema: Any = None, **kw: Any) -> Any:
        if step_of(schema) == "extract":
            self.prompts.append(prompt)
            if not self.failed:
                self.failed = True
                return type("A", (), {"text": "not json at all"})()
        return await self.inner.complete(prompt, schema, **kw)


def test_after_a_malformed_answer_the_small_model_is_shown_the_schema() -> None:
    inner = ScriptedProvider()
    provider = _BrokenOnce(inner)
    document = _run(_recording(6), provider)  # type: ignore[arg-type]
    assert document.windows_failed == 0
    first, second = provider.prompts[0], provider.prompts[1]
    assert second.startswith(first)
    echoed = second[len(first) :]
    assert prompts.SCHEMA_ECHO["de"] in echoed
    # SQ2 T2: a short window's budget is the floor, eight.
    assert '"maxItems": 8' in echoed and '"noise"' not in echoed


def test_a_capable_model_is_retried_without_the_echo() -> None:
    inner = ScriptedProvider()
    provider = _BrokenOnce(inner, small_model=False)
    document = _run(_recording(6), provider)  # type: ignore[arg-type]
    assert document.windows_failed == 0
    first, second = provider.prompts[0], provider.prompts[1]
    assert second == first


# ── reduce: heading and bullets apart, ≤ 15 facts, no children ──────


def test_small_model_reduce_splits_a_block_and_asks_for_the_heading_separately() -> None:
    provider = SmallProvider()
    facts = [
        _fact(f"Peter Thiel nannte {n + 3} Investoren im Jahr {1990 + n}", n * 20_000)
        for n in range(22)
    ]
    block = compose.Block(0, tuple(facts))
    gate = pipeline._Gate(
        language="de", known=frozenset({"Peter Thiel"}), people=frozenset({"Peter Thiel"})
    )
    budget = compose.VolumeBudget(minutes=20, blocks=1)
    result = asyncio.run(
        pipeline._reduce_block(
            provider,
            block,
            "de",
            budget,
            brief=None,
            gate=gate,
            table=roles_table.build([], [], "meeting"),
            small=True,
        )
    )
    assert result is not None
    heading, bullets, _ids = result
    assert heading and bullets
    block_calls = [(p, s) for step, p, s in provider.calls if step == "block"]
    bullet_calls = [
        (p, s)
        for (p, s), sch in zip(
            block_calls, [x for x in provider.schemas if step_of(x) == "block"], strict=True
        )
        if "bullets" in (sch or {}).get("properties", {})
    ]
    heading_calls = [
        (p, s)
        for (p, s), sch in zip(
            block_calls, [x for x in provider.schemas if step_of(x) == "block"], strict=True
        )
        if "heading" in (sch or {}).get("properties", {})
    ]
    # 22 facts → two bullet calls of at most fifteen facts, one heading call.
    assert len(bullet_calls) == 2 and len(heading_calls) == 1
    assert all(len(facts_in(p)) <= pipeline.SMALL_MODEL_REDUCE_FACTS for p, _s in bullet_calls)
    for sch in provider.schemas:
        if step_of(sch) == "block":
            props = sch["properties"]  # type: ignore[index]
            assert not ("heading" in props and "bullets" in props)
            if "bullets" in props:
                assert "children" not in props["bullets"]["items"]["properties"]
    assert all(children == [] for _t, _ids, children in bullets)


def test_a_capable_model_gets_the_one_call_block_schema_with_children() -> None:
    provider = ScriptedProvider()
    _run(_recording(40), provider)
    block_schemas = [s for s in provider.schemas if step_of(s) == "block"]
    assert block_schemas
    for sch in block_schemas:
        assert sch == schema.BLOCK_SCHEMA  # type: ignore[comparison-overlap]


# ── orientation p2: the strict skeleton first ────────────────────────


def test_small_model_summary_runs_the_strict_skeleton_rung_first() -> None:
    def summary(facts: list, system: str) -> dict:
        return {"summary": [{"sentence": text, "fact_ids": [fid]} for fid, _k, text in facts[:3]]}

    provider = SmallProvider(overrides={"summary": summary})
    document = _run(_recording(40), provider)
    systems = [system for step, _p, system in provider.calls if step == "summary"]
    assert systems and prompts.strict_suffix("de") in systems[0]
    assert prompts.SKELETON["de"].split("{")[0] in systems[0]
    assert document.stats["summary_ladder"] == "strict"
    assert document.stats["small_model_profile"] is True


def test_a_capable_model_summary_runs_the_free_rung_first() -> None:
    def summary(facts: list, system: str) -> dict:
        return {"summary": [{"sentence": text, "fact_ids": [fid]} for fid, _k, text in facts[:3]]}

    provider = ScriptedProvider(overrides={"summary": summary})
    document = _run(_recording(40), provider)
    systems = [system for step, _p, system in provider.calls if step == "summary"]
    assert systems and prompts.strict_suffix("de") not in systems[0]
    assert document.stats["summary_ladder"] == "model"
    assert document.stats["small_model_profile"] is False


# ── the switch itself ───────────────────────────────────────────────


def test_the_profile_is_read_from_the_provider_and_defaults_off() -> None:
    assert pipeline.small_model(ScriptedProvider()) is False
    assert pipeline.small_model(SmallProvider()) is True

    class Bare:
        backend = "x"
        model_id = "x"

    assert pipeline.small_model(Bare()) is False  # type: ignore[arg-type]


def test_stats_and_the_schema_echo_are_json_serialisable() -> None:
    echo = prompts.schema_echo("en", schema.extract_schema(max_facts=12, noise=False))
    json.loads(echo.split("\n", 1)[1])
    document = _run(_recording(8), SmallProvider())
    json.dumps(document.stats)


# ── the header a small model writes ─────────────────────────────────


def test_a_colon_after_the_line_number_is_still_a_turn_header() -> None:
    """Under the one-example profile Gemma 3 4B quotes "[2]: Nadia (01:42): …":
    on m09 every fact was dropped for its quote. The header goes; the words
    are verified as before."""
    from note_service.domain.meeting_doc import verify

    assert verify.strip_turn_header("[2]: Nadia (01:42): And last, remind Ravi") == (
        "And last, remind Ravi"
    )
    assert verify.strip_turn_header("[2] Nadia (01:42): And last, remind Ravi") == (
        "And last, remind Ravi"
    )
    assert verify.strip_turn_header("Nadia (01:42): And last") == "And last"
    assert verify.strip_turn_header("And last, remind Ravi") == "And last, remind Ravi"
