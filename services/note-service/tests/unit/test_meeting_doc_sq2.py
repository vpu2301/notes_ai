"""Sprint SQ2 — the whole recording is in the note.

T1 the diagnosis numbers (per window, per third; numbers only), T2 even
fact budgets, T3 the coverage guard, T4 sections from the transcript, T5
reduce over every fact. Scripted provider throughout: what is tested is
what the engine sends and keeps, not what a model writes."""

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
    schema,
    windows,
)
from note_service.domain.meeting_doc.verify import VerifiedFact
from note_service.domain.meeting_doc.windows import Turn

from .meeting_doc_fakes import ScriptedProvider, as_result, data_blocks, step_of

MIN = 60_000
DAY = date(2026, 10, 1)

# Three vocabularies, one per part of a recording: a lexical shift between them.
TOPICS = (
    "Zentrifugen Natanz Anreicherung Uran Reaktor Inspektoren Atomprogramm",
    "Kindergärten Panikknöpfe Hacker Albanien Regierung Server Angriff",
    "Bewegung Proteste Studenten Wahlen Opposition Straße Teheran",
)


CITIES = (
    "Berlin",
    "Wien",
    "Zürich",
    "Hamburg",
    "Köln",
    "Graz",
    "Basel",
    "Bremen",
    "Linz",
    "Bonn",
    "Kiel",
    "Ulm",
    "Mainz",
)
NOUNS = (
    "Berichte",
    "Verträge",
    "Budgets",
    "Pläne",
    "Daten",
    "Zahlen",
    "Termine",
    "Kosten",
    "Risiken",
    "Ziele",
    "Preise",
)


def _turn_text(n: int, topic: str, filler: int = 0) -> str:
    # Distinct opening words per turn, so the merge keeps every fact.
    base = (
        f"{CITIES[n % len(CITIES)]} meldete {NOUNS[n % len(NOUNS)]} am Tag {n + 3} "
        f"und dann ging es um {topic}"
    )
    return base + (" und es wurde weiter darüber gesprochen" * filler)


def _recording(turns: int, *, ms: int = 20_000, filler: int = 0, topics: bool = True) -> dict:
    return {
        "language": "de",
        "transcript": [
            {
                "speaker": ("SPEAKER_1", "SPEAKER_2")[n % 2],
                "t_start_ms": n * ms,
                "t_end_ms": n * ms + ms - 1_000,
                "text": _turn_text(
                    n, TOPICS[min(2, 3 * n // turns)] if topics else TOPICS[0], filler
                ),
            }
            for n in range(turns)
        ],
    }


def _run(meeting: dict, provider: Any, **kw: Any) -> pipeline.DocumentResult:
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


class Small(ScriptedProvider):
    small_model: bool = True


class Wide(ScriptedProvider):
    context_window = 131_072


# ── T1 the diagnosis numbers ────────────────────────────────────────


def test_per_window_and_reduce_numbers_are_recorded_and_are_numbers_only() -> None:
    document = _run(_recording(90), ScriptedProvider())
    stats = document.stats
    assert stats["windows"] and len(stats["windows"]) >= document.windows_total
    for w in stats["windows"]:
        for key in (
            "index",
            "start_ms",
            "end_ms",
            "chars",
            "budget",
            "facts_extracted",
            "facts_verified",
            "facts_kept_after_merge",
            "call_failed",
            "facts_first_half",
            "facts_second_half",
        ):
            assert isinstance(w[key], int), key
    for key in (
        "reduce_input_facts",
        "reduce_cited_facts",
        "excluded_speech_ms",
        "blocks_planned",
        "blocks_rendered",
        "sections_rendered",
        "coverage_retry_facts",
        "coverage_gaps",
        "blocks_boundaries",
        "blocks_merged_small",
    ):
        assert isinstance(stats[key], int), key
    assert all(isinstance(n, int) for n in stats["reduce_cited_by_third"])
    assert all(isinstance(m, float) for m in stats["speech_minutes_by_third"])
    assert stats["blocks_source"] in {
        compose.SOURCE_CUES,
        compose.SOURCE_LEXICAL,
        compose.SOURCE_MIXED,
        compose.SOURCE_UNIFORM,
        compose.SOURCE_SINGLE,
        f"{compose.SOURCE_LEXICAL}+{compose.SOURCE_UNIFORM}",
        f"{compose.SOURCE_CUES}+{compose.SOURCE_UNIFORM}",
    }
    # No word of the recording in any SQ2 number.
    sq2 = {
        k: stats[k]
        for k in (
            "windows",
            "reduce_cited_by_third",
            "speech_minutes_by_third",
            "coverage_retry",
            "blocks_source",
        )
    }
    dumped = json.dumps(sq2, ensure_ascii=False)
    for word in ("Zentrifugen", "Kindergärten", "Bewegung", "Abschnitt"):
        assert word not in dumped


def test_thirds_are_by_time_not_by_window() -> None:
    """One window holding the whole recording is not "the middle third"."""
    document = _run(_recording(20), Wide())
    assert document.windows_total == 1
    first, middle, last = document.stats["facts_by_third"]
    assert first and last, document.stats["facts_by_third"]


# ── T2 even budgets ─────────────────────────────────────────────────


def test_48k_characters_give_8_small_windows_or_6_wide_ones() -> None:
    meeting = _recording(120, filler=7)  # ~400 characters a turn
    chars = sum(len(t["text"]) for t in meeting["transcript"])
    assert 45_000 <= chars <= 52_000
    small = _run(meeting, Small())
    assert small.windows_total >= 8
    assert all(w["budget"] >= 8 for w in small.stats["windows"] if not w.get("coverage_retry"))
    wide = _run(meeting, Wide())
    assert wide.windows_total >= 6
    assert wide.stats["window_chars"] == windows.EXTRACT_WINDOW_CHARS


def test_small_budget_follows_the_window_length() -> None:
    def window(chars: int) -> windows.Window:
        return windows.Window(0, (Turn(0, "S1", None, "x" * chars, 0, 1_000),))

    assert pipeline.small_budget(window(1_000)) == 8
    assert pipeline.small_budget(window(5_000)) == 10
    assert pipeline.small_budget(window(6_000)) == 12


def test_facts_by_third_are_even_on_the_scripted_provider() -> None:
    by_third = _run(_recording(120, filler=5), ScriptedProvider()).stats["facts_by_third"]
    mean = sum(by_third) / 3
    assert all(abs(n - mean) <= 0.2 * mean for n in by_third), by_third


# ── T3 the coverage guard ───────────────────────────────────────────


_LINE = re.compile(r"^\[(?P<n>\d+)\] [^()\n]*\((?P<m>\d{2}):(?P<s>\d{2})\)", re.MULTILINE)


class MiddleDeaf(ScriptedProvider):
    """Returns nothing for the lines said inside ``middle`` (ms) on a normal
    extract; ``retry_ok`` decides whether the coverage variant is answered."""

    def __init__(self, middle: range, retry_ok: bool) -> None:
        super().__init__()
        self.middle = middle
        self.retry_ok = retry_ok
        self.coverage_calls = 0

    async def complete(self, prompt: str, schema: Any = None, **kw: Any) -> Any:
        answer = await super().complete(prompt, schema, **kw)
        if step_of(schema) != "extract":
            return answer
        retry = "Abschnitt reicht von" in (kw.get("system") or "")
        self.coverage_calls += int(retry)
        if retry and self.retry_ok:
            return answer
        said = {
            int(m["n"]): (int(m["m"]) * 60 + int(m["s"])) * 1000
            for body in data_blocks(prompt)
            for m in _LINE.finditer(body)
        }
        payload = answer.json
        payload["facts"] = [
            f for f in payload["facts"] if said.get(f["turn"], -1) not in self.middle
        ]
        answer.text = json.dumps(payload)
        return answer


def _ratio(document: pipeline.DocumentResult) -> float | None:
    return doclint.coverage_ratio(doclint.context_of(document))


def test_an_empty_middle_third_is_read_again_and_comes_back() -> None:
    provider = MiddleDeaf(range(10 * MIN, 20 * MIN), retry_ok=True)
    document = _run(_recording(90), provider)
    assert 2 in document.stats["coverage_retry"]
    assert provider.coverage_calls >= 1
    assert document.stats["coverage_retry_facts"] > 0
    ratio = _ratio(document)
    assert ratio is not None and round(ratio, 6) >= 0.8, document.stats["facts_by_third"]
    assert document.coverage_gaps == [] and not document.partial


def test_a_third_still_empty_after_the_retry_is_named_never_silent() -> None:
    provider = MiddleDeaf(range(10 * MIN, 20 * MIN), retry_ok=False)
    document = _run(_recording(90), provider)
    assert 2 in document.stats["coverage_retry"]
    assert len(document.coverage_gaps) == 1
    start, end = document.coverage_gaps[0]
    assert 9 * MIN <= start <= 11 * MIN and 19 * MIN <= end <= 21 * MIN
    assert document.coverage_gaps[0] in document.failed_ranges
    assert document.partial  # the status line's "around minute …"
    linted = asyncio.run(doclint.enforce(document, regenerate=document.regenerator))
    assert linted.stats["lint"]["unresolved_rules"].get("coverage.thirds") == 1


def test_the_retry_is_skipped_past_its_time_budget_and_the_gap_is_named() -> None:
    provider = MiddleDeaf(range(10 * MIN, 20 * MIN), retry_ok=True)
    document = _run(_recording(90), provider, retry_budget_s=0.0)
    assert document.stats["coverage_retry_skipped"] == "budget"
    assert provider.coverage_calls == 0
    assert document.coverage_gaps and document.partial


def test_the_coverage_variant_adds_only_the_range_and_ids() -> None:
    text = prompts.coverage_suffix("de", 600_000, 1_200_000, ["a1", "b2"])
    assert "10:00" in text and "20:00" in text and "a1, b2" in text
    assert not prompts.echoes_example(text)
    for language in ("en", "de", "uk"):
        assert not prompts.echoes_example(prompts.COVERAGE_SUFFIX[language])


# ── T4 sections follow the recording ────────────────────────────────


def _turns(texts: list[str], ms: int = 30_000) -> list[Turn]:
    return [
        Turn(n, f"SPEAKER_{n % 2}", None, t, n * ms, n * ms + ms - 1_000)
        for n, t in enumerate(texts)
    ]


def test_three_spoken_chapters_are_three_blocks_in_order() -> None:
    texts = [f"Wir sprechen über Thema {n} und vieles mehr" for n in range(24)]  # 12 minutes
    texts[8] = "Kapitel 2 wie alles anfing mit der Geschichte"
    texts[16] = "Kapitel drei und was danach geschah"
    turns = _turns(texts)
    cues = classify.structure_cues(turns, "de")
    assert cues == [8 * 30_000, 16 * 30_000]
    seg = compose.segment(turns, 12, "de", cues)
    assert seg.boundaries == (240_000, 480_000) and seg.source == compose.SOURCE_CUES
    facts = [_fact(f"Fakt {n}", n * 30_000) for n in range(24)]
    parts, merged = compose.blocks_at(list(reversed(facts)), seg)
    assert merged == 0 and len(parts) == 3
    assert [p.facts[0].start_ms for p in parts] == [0, 240_000, 480_000]
    assert all(
        a.facts[-1].start_ms < b.facts[0].start_ms for a, b in zip(parts, parts[1:], strict=False)
    )


def test_cues_in_english_and_ukrainian() -> None:
    assert classify.structure_cues(_turns(["ok", "let's move on to the budget"]), "en") == [30_000]
    assert classify.structure_cues(_turns(["так", "перейдемо до бюджету"]), "uk") == [30_000]


def test_without_cues_the_boundaries_are_the_two_largest_lexical_shifts() -> None:
    texts = [TOPICS[0]] * 8 + [TOPICS[1]] * 8 + [TOPICS[2]] * 8  # 3 × 4 min of 30 s turns
    seg = compose.segment(_turns(texts), 12, "de")
    assert seg.source == compose.SOURCE_LEXICAL
    assert len(seg.boundaries) == 2
    assert abs(seg.boundaries[0] - 240_000) <= compose.TILE_MS
    assert abs(seg.boundaries[1] - 480_000) <= compose.TILE_MS


def test_a_monologue_on_one_subject_gets_equal_parts() -> None:
    seg = compose.segment(_turns([TOPICS[0]] * 24), 12, "de")
    assert seg.source == compose.SOURCE_UNIFORM and len(seg.boundaries) == 2


def test_a_one_fact_block_is_merged_and_counted() -> None:
    seg = compose.Segmentation((100_000, 200_000), compose.SOURCE_LEXICAL)
    facts = [
        _fact("a", 0),
        _fact("b", 50_000),
        _fact("c", 150_000),
        _fact("d", 210_000),
        _fact("e", 220_000),
    ]
    parts, merged = compose.blocks_at(facts, seg)
    assert merged == 1 and len(parts) == 2
    assert all(len(p.facts) >= compose.MIN_SEGMENT_FACTS for p in parts)


def test_bullets_inside_a_block_are_in_recording_order() -> None:
    document = _run(_recording(90), ScriptedProvider())
    by_id = {f.item_key: f for f in document.facts}
    for section in document.sections:
        if section.role != roles.TOPICS:
            continue
        starts = [
            min(by_id[i].start_ms for i in line.fact_ids if i in by_id)
            for line in section.lines
            if line.kind == "bullet" and not line.parent and any(i in by_id for i in line.fact_ids)
        ]
        assert starts == sorted(starts)


# ── T5 reduce sees every block's facts ──────────────────────────────


def test_facts_from_the_last_window_are_cited_in_the_last_section() -> None:
    document = _run(_recording(120, filler=5), ScriptedProvider())
    assert document.windows_total >= 7
    topics = [s for s in document.sections if s.role == roles.TOPICS]
    by_id = {f.item_key: f for f in document.facts}
    cited = [by_id[i] for line in topics[-1].lines for i in line.fact_ids if i in by_id]
    end = max(f.start_ms for f in document.facts)
    # The last section is written from the end of the recording.
    assert cited and min(f.start_ms for f in cited) >= 2 * end / 3
    assert all(n > 0 for n in document.stats["reduce_cited_by_third"])


def test_the_small_profile_reads_its_last_chunk_too() -> None:
    facts = [
        _fact(f"Fakt {n} über das Projekt", n * 10_000)
        for n in range(pipeline.SMALL_MODEL_REDUCE_FACTS)
    ] + [
        _fact(
            f"Am 3. März {2020 + n} kaufte Peter Thiel {n + 7} Server in Kalifornien",
            (40 + n) * 10_000,
        )
        for n in range(5)
    ]
    provider = Small()
    gate = pipeline._Gate(language="de", known=frozenset({"Peter Thiel", "Kalifornien"}))
    from note_service.domain.meeting_doc import roles_table

    out = asyncio.run(
        pipeline._reduce_block(
            provider,
            compose.Block(0, tuple(facts)),
            "de",
            compose.VolumeBudget(40, 1),
            brief=None,
            gate=gate,
            table=roles_table.RolesTable(),
            small=True,
        )
    )
    last_ids = {f.item_key for f in facts[pipeline.SMALL_MODEL_REDUCE_FACTS :]}
    block_prompts = [p for step, p, _s in provider.calls if step == "block"]
    assert any(any(i in body for i in last_ids for body in data_blocks(p)) for p in block_prompts)
    assert out is not None
    cited = {i for _t, ids, _c in out[1] for i in ids}
    assert cited & last_ids


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


def test_the_worker_scales_the_retry_budget_with_the_recording() -> None:
    from types import SimpleNamespace

    from note_service.jobs.generate_note import _retry_budget

    built = windows.build_windows(windows.turns_from_result(as_result(_recording(90))))
    half_hour = built[-1].end_ms - built[0].start_ms
    assert 29 * MIN <= half_hour <= 31 * MIN
    assert _retry_budget(SimpleNamespace(coverage_retry_budget_s_per_hour=None), built) is None
    budget = _retry_budget(SimpleNamespace(coverage_retry_budget_s_per_hour=300.0), built)
    assert budget is not None and 145 <= budget <= 155
