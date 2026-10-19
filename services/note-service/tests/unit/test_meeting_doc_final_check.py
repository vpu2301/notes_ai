"""F1 — the final check: every asserted line, after composition, attribution patching and
doclint, is checked against the transcript lines of the facts it cites before anything is
written; what it cannot confirm leaves the asserted prose, kept for review, and the note
says it is incomplete. Provenance says which code, prompts, flags and models made a run.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from note_models import NoteContent, NoteSection
from note_service.domain import prompt_profiles as profiles
from note_service.domain.meeting_doc import (
    final_check,
    pipeline,
    prompts,
    schema,
    verify,
    writer,
)
from note_service.domain.meeting_doc.render import Line, RenderedSection
from note_service.domain.meeting_doc.windows import Turn, Window
from note_service.jobs import generate_note
from note_service.routers import notes_generation

from .meeting_doc_fakes import ScriptedProvider

DAY = date(2026, 10, 18)
WORSE = (
    "Die Wirtschaftslage im Süden ist laut dem neuen Bericht deutlich schlechter als im Vorjahr."
)
CHAMBERS = (
    "The relief money is paid out only if both chambers of Congress approve the package "
    "before the recess."
)
OTHER = "Die Moderation dankt allen Gästen und schließt die Sendung mit einem kurzen Ausblick."
TURNS = (
    Turn(0, "SPEAKER_1", "Dana Price", WORSE, 0, 10_000, line=0),
    Turn(1, "SPEAKER_2", "Tom Berg", CHAMBERS, 10_000, 20_000, line=1, language="en"),
    Turn(2, "SPEAKER_1", "Dana Price", OTHER, 20_000, 30_000, line=2),
)
WINDOW = Window(index=0, turns=TURNS)
POOL = {0: WINDOW}


def _fact(text: str, line: int, quote: str, **kw: Any) -> verify.VerifiedFact:
    turn = TURNS[line]
    return verify.VerifiedFact(
        kind="key_point",
        text=text,
        quote=quote,
        turn=line,
        start_ms=turn.start_ms,
        end_ms=turn.end_ms,
        speaker_label=turn.speaker_label,
        speaker_name=turn.speaker_name,
        line=line,
        **kw,
    )


ECONOMY = _fact(
    "Die Wirtschaftslage im Süden ist deutlich schlechter als im Vorjahr.",
    0,
    "Wirtschaftslage im Süden ist laut dem neuen Bericht deutlich schlechter",
)
RELIEF = _fact(
    "Die Hilfsgelder fließen nur, wenn beide Kammern des Kongresses vor der Pause zustimmen.",
    1,
    "only if both chambers of Congress approve the package",
    source_language="en",
)
FACTS = [ECONOMY, RELIEF]

_CLAIM = re.compile(r"^claim_id (?P<id>c\d+): (?P<claim>.*)$")
_SHOWN = re.compile(r"^\s+\[(?P<n>\d+)\]")


def claims_in(prompt: str) -> list[tuple[str, str, list[int]]]:
    """``[(claim_id, claim, line numbers shown)]`` from a meaning-check prompt."""
    out: list[tuple[str, str, list[int]]] = []
    for line in prompt.splitlines():
        if match := _CLAIM.match(line):
            out.append((match["id"], match["claim"], []))
        elif (shown := _SHOWN.match(line)) and out:
            out[-1][2].append(int(shown["n"]))
    return out


@dataclass
class Judge(ScriptedProvider):
    """A verifier that reads each claim: ``rules`` = ``[(substring, verdict, correction)]``
    (``=text``: the whole claim, end punctuation aside), first match wins, else supported.
    ``fail``: raise instead; ``hang``: never answer."""

    rules: list[tuple[str, str, str | None]] = field(default_factory=list)
    fail: bool = False
    hang: bool = False
    seen: list[str] = field(default_factory=list)

    def _checks(self, prompt: str, _facts: list[Any]) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("verifier down")
        checks = []
        for claim_id, claim, shown in claims_in(prompt):
            self.seen.append(claim)
            verdict, corrected = schema.SUPPORTED, None
            for needle, said, correction in self.rules:
                exact = needle.startswith("=") and claim.rstrip(".") == needle[1:]
                if exact or (not needle.startswith("=") and needle in claim):
                    verdict, corrected = said, correction
                    break
            checks.append(
                {
                    "claim_id": claim_id,
                    "verdict": verdict,
                    "evidence_ids": [str(shown[0])],
                    "reason": "r",
                    "corrected_claim": corrected,
                }
            )
        return {"checks": checks}

    async def complete(self, prompt: str, schema_: Any = None, **kw: Any) -> Any:
        if self.hang:
            await asyncio.sleep(10)
        return await super().complete(prompt, schema_, **kw)


def _section(key: str, *lines: Line, title: str | None = None) -> RenderedSection:
    section = RenderedSection(section_key=key, role="topics", text="", title=title, lines=lines)
    return replace(section, text="\n".join(ln.text for ln in lines))


def _validate(
    sections: list[RenderedSection], judge: Judge, cache: dict[str, Any] | None = None
) -> tuple[list[RenderedSection], list[final_check.Rejected], Counter[str]]:
    tally: Counter[str] = Counter()
    kept, rejected = asyncio.run(
        final_check.validate(
            sections,
            facts=FACTS,
            windows_by_index=POOL,
            verifier=judge,
            language="de",
            task=prompts.task("de"),
            cache={} if cache is None else cache,
            tally=tally,
        )
    )
    return kept, rejected, tally


def _texts(sections: list[RenderedSection]) -> list[str]:
    return [ln.text for s in sections for ln in s.lines]


# ── F1-02 acceptance ────────────────────────────────────────────────


def test_an_inverted_comparison_is_corrected_and_checked_again() -> None:
    better = "- Die Wirtschaftslage im Süden ist deutlich besser als im Vorjahr"
    judge = Judge(
        rules=[
            ("besser", schema.CONTRADICTED, "Die Lage im Süden ist schlechter als im Vorjahr"),
        ]
    )
    kept, rejected, tally = _validate(
        [_section("gen:economy", Line(better, "bullet", (ECONOMY.item_key,)))], judge
    )
    assert _texts(kept) == ["- Die Lage im Süden ist schlechter als im Vorjahr"]
    assert rejected == [] and tally["repaired"] == 1
    # Checked, then the correction checked again on its own: two calls.
    assert [c[0] for c in judge.calls] == ["checks", "checks"]
    assert judge.seen[1] == "Die Lage im Süden ist schlechter als im Vorjahr"


def test_an_inverted_comparison_without_a_correction_falls_back_to_its_fact() -> None:
    better = "- Die Wirtschaftslage im Süden ist deutlich besser als im Vorjahr"
    judge = Judge(rules=[("besser", schema.CONTRADICTED, None)])
    kept, rejected, tally = _validate(
        [_section("gen:economy", Line(better, "bullet", (ECONOMY.item_key,)))], judge
    )
    assert _texts(kept) == [f"- {ECONOMY.text.rstrip('.')}"]
    assert tally["restored"] == 1 and rejected == []


def test_a_summary_that_loses_the_condition_is_kept_for_review() -> None:
    lost = "Der Bericht nennt eine schwächere Lage im Süden, und die Hilfsgelder fließen."
    judge = Judge(rules=[("Hilfsgelder fließen.", schema.CONTRADICTED, None)])
    summary = Line(lost, "summary", (ECONOMY.item_key, RELIEF.item_key))
    kept, rejected, tally = _validate(
        [_section("overview", Line("Ein Bericht.", "framing", ()), summary)], judge
    )
    assert lost not in " ".join(_texts(kept))
    [review] = rejected
    assert review.line.text == lost and review.reason == schema.CONTRADICTED
    assert set(review.line.fact_ids) == {ECONOMY.item_key, RELIEF.item_key}
    assert tally["unverified"] == 1


def test_a_german_line_on_english_evidence_is_judged_by_meaning() -> None:
    judge = Judge()
    paraphrase = "- Das Geld kommt nur mit der Zustimmung beider Kammern vor der Pause"
    kept, rejected, _tally = _validate(
        [_section("gen:relief", Line(paraphrase, "bullet", (RELIEF.item_key,)))], judge
    )
    assert _texts(kept) == [paraphrase] and rejected == []
    # Checked against the ORIGINAL English line (and its neighbours), not the fact's paraphrase only.
    [(_step, prompt, system)] = judge.calls
    assert CHAMBERS in prompt and WORSE in prompt
    assert prompts.task("de").verification in system


def test_a_line_that_is_its_facts_text_and_structure_are_not_sent() -> None:
    judge = Judge()
    sections = [
        _section(
            "gen:economy",
            Line("### Wirtschaft", "heading", (ECONOMY.item_key,)),
            Line(f"- {ECONOMY.text}", "bullet", (ECONOMY.item_key,)),
            Line(f"  - {ECONOMY.quote}", "quote", (ECONOMY.item_key,), parent="- x"),
        )
    ]
    kept, _rejected, tally = _validate(sections, judge)
    assert judge.calls == [] and kept == sections
    assert tally["fact_text"] == 1 and tally["structural"] == 2


def test_an_unavailable_verifier_publishes_no_unchecked_line() -> None:
    judge = Judge(fail=True)
    composed = Line("Der Süden steht schlechter da, und Hilfe kommt mit den Kammern.", "summary",
                    (ECONOMY.item_key, RELIEF.item_key))  # fmt: skip
    single = Line("- Im Süden ist die Lage schlechter", "bullet", (ECONOMY.item_key,))
    kept, rejected, tally = _validate(
        [_section("overview", composed), _section("gen:economy", single)], judge
    )
    # The one-fact line falls back to its verified fact; the composed one leaves the prose.
    assert _texts(kept) == [f"- {ECONOMY.text.rstrip('.')}"]
    assert [r.line.text for r in rejected] == [composed.text]
    assert tally["unavailable"] == 2


def test_a_verifier_that_times_out_or_runs_out_of_budget_decides_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(final_check, "TIMEOUT_S", 0.01)
    composed = Line("Der Süden steht schlechter da, und Hilfe kommt mit den Kammern.", "summary",
                    (ECONOMY.item_key, RELIEF.item_key))  # fmt: skip
    _kept, rejected, tally = _validate([_section("overview", composed)], Judge(hang=True))
    assert tally["timeout"] == 1 and len(rejected) == 1

    monkeypatch.setattr(final_check, "CALLS_MAX", 0)
    judge = Judge()
    _kept, rejected, tally = _validate([_section("overview", composed)], judge)
    assert judge.calls == [] and tally["budget"] == 1 and len(rejected) == 1


def test_a_malformed_answer_or_a_foreign_line_decides_nothing() -> None:
    composed = Line("Der Süden steht schlechter da, und Hilfe kommt mit den Kammern.", "summary",
                    (ECONOMY.item_key, RELIEF.item_key))  # fmt: skip
    malformed = Judge(overrides={"checks": lambda _f: {"checks": []}})
    _kept, rejected, tally = _validate([_section("overview", composed)], malformed)
    assert tally["malformed"] == 1 and len(rejected) == 1
    foreign = Judge(
        overrides={
            "checks": lambda _f: {
                "checks": [
                    {"claim_id": "c1", "verdict": "supported", "evidence_ids": ["40"],
                     "reason": "r", "corrected_claim": None}
                ]
            }
        }
    )  # fmt: skip
    _kept, rejected, tally = _validate([_section("overview", composed)], foreign)
    assert tally["foreign_lines"] == 1 and len(rejected) == 1


def test_a_correction_with_an_unsaid_number_is_refused_by_code() -> None:
    judge = Judge(rules=[("besser", schema.CONTRADICTED, "Die Lage ist um 40 Prozent schlechter")])
    better = Line("- Die Lage im Süden ist besser", "bullet", (ECONOMY.item_key,))
    kept, _rejected, tally = _validate([_section("gen:economy", better)], judge)
    assert tally["repair_number"] == 1 and len(judge.calls) == 1
    assert _texts(kept) == [f"- {ECONOMY.text.rstrip('.')}"]


def test_a_verdict_is_cached_only_for_the_same_words_on_the_same_evidence() -> None:
    cache: dict[str, Any] = {}
    line = Line("- Im Süden ist die Lage schlechter", "bullet", (ECONOMY.item_key,))
    judge = Judge()
    _validate([_section("gen:economy", line)], judge, cache)
    _validate([_section("gen:economy", line)], judge, cache)
    assert len(judge.calls) == 1
    reworded = replace(line, text="- Im Süden ist die Lage viel schlechter")
    _validate([_section("gen:economy", reworded)], judge, cache)
    assert len(judge.calls) == 2


def test_a_dropped_bullets_sub_points_move_up_and_its_quotes_go() -> None:
    parent = Line("- Hilfe und Lage hängen zusammen", "bullet", (ECONOMY.item_key, RELIEF.item_key))
    child = Line("  - Im Süden ist die Lage schlechter", "bullet", (ECONOMY.item_key,),
                 parent=parent.text)  # fmt: skip
    quote = Line(f"  - {ECONOMY.quote}", "quote", (ECONOMY.item_key,), parent=parent.text)
    judge = Judge(rules=[("hängen zusammen", schema.INSUFFICIENT, None)])
    kept, rejected, _tally = _validate(
        [_section("gen:mixed", Line("### Lage", "heading", ()), parent, child, quote)], judge
    )
    assert _texts(kept) == ["### Lage", "- Im Süden ist die Lage schlechter"]
    assert [r.line.text for r in rejected] == [parent.text]
    [section] = kept
    assert section.lines[1].parent is None and section.text.endswith("schlechter")


def test_a_topic_left_with_nothing_asserted_goes() -> None:
    composed = Line(
        "- Lage und Hilfe hängen zusammen", "bullet", (ECONOMY.item_key, RELIEF.item_key)
    )
    judge = Judge(rules=[("hängen zusammen", schema.INSUFFICIENT, None)])
    kept, rejected, _tally = _validate(
        [_section("gen:mixed", Line("### Lage", "heading", ()), composed)], judge
    )
    assert kept == [] and len(rejected) == 1


def test_a_line_with_no_evidence_is_not_asserted() -> None:
    orphan = Line("- Der Kongress hat bereits zugestimmt", "bullet", ("unknown-id",))
    kept, rejected, tally = _validate([_section("gen:x", orphan)], Judge())
    assert kept == [] and rejected[0].reason == "no_evidence" and tally["no_evidence"] == 1


# ── finalize(): incomplete state, review rows, human text ──────────


def _document(sections: list[RenderedSection], judge: Judge) -> pipeline.DocumentResult:
    document = pipeline.DocumentResult(sections=sections, facts=list(FACTS))
    document.stats = {"prompt_version": prompts.PROMPT_VERSION}

    async def finalizer(current: list[RenderedSection]) -> Any:
        tally: Counter[str] = Counter()
        kept, rejected = await final_check.validate(
            current,
            facts=FACTS,
            windows_by_index=POOL,
            verifier=judge,
            language="de",
            task=prompts.task("de"),
            cache={},
            tally=tally,
        )
        return kept, rejected, tally

    document.finalizer = finalizer
    return document


def test_finalize_marks_the_note_incomplete_and_offers_the_line_for_review() -> None:
    composed = Line("Der Süden steht schlechter da, und Hilfe kommt mit den Kammern.", "summary",
                    (ECONOMY.item_key, RELIEF.item_key))  # fmt: skip
    document = asyncio.run(
        pipeline.finalize(_document([_section("overview", composed)], Judge(fail=True)))
    )
    assert document.partial and final_check.FINAL_UNVERIFIED in document.incomplete
    stats = document.stats["final_check"]
    assert stats["ran"] and stats["unverified"] == 1 and stats["version"] == final_check.VERSION
    assert stats["unverified_sources"] == sorted({ECONOMY.item_key, RELIEF.item_key})
    # Ids and counts only: no transcript or line text in the stats.
    assert CHAMBERS not in str(stats) and composed.text not in str(stats)
    [row] = generate_note.review_rows(document)
    assert row["text"] == composed.text and row["placement"] == writer.SUGGESTED
    assert final_check.FINAL_UNVERIFIED in row["flags"]
    assert row["cites"] == [ECONOMY.item_key, RELIEF.item_key]


def test_finalize_without_a_finalizer_records_that_it_did_not_run() -> None:
    document = asyncio.run(pipeline.finalize(pipeline.DocumentResult()))
    assert document.stats["final_check"] == {"ran": False}


def test_a_crashing_check_publishes_no_generated_line() -> None:
    document = pipeline.DocumentResult(
        sections=[_section("overview", Line("Ein Satz.", "summary", (ECONOMY.item_key,)))]
    )

    async def broken(_sections: Any) -> Any:
        raise ValueError("bug")

    document.finalizer = broken
    document = asyncio.run(pipeline.finalize(document))
    assert _texts(document.sections) == [] and document.stats["final_check"]["crashed"] == 1
    assert document.partial


def test_a_persons_section_is_preserved_whatever_the_check_did() -> None:
    authored = "My own notes on the south."
    content = NoteContent(
        template_id=uuid4(),
        template_schema_version=2,
        title="Weekly",
        sections=[NoteSection(section_key="gen:economy", text=authored)],
    )
    better = Line("- Die Lage im Süden ist besser", "bullet", (ECONOMY.item_key,))
    document = asyncio.run(
        pipeline.finalize(
            _document(
                [_section("gen:economy", better)],
                Judge(rules=[("besser", schema.CONTRADICTED, None)]),
            )
        )
    )
    planned, outcome = writer.plan(content, document.sections, previous_hashes={})
    assert planned.sections[0].text == authored
    assert outcome.suggested_sections == ["gen:economy"]


# ── the whole pipeline: a correct extractor, a corrupting composer ─


_CONDITION_FACT = "Die Hilfsgelder fließen nur, wenn beide Kammern zustimmen."


def _broadcast() -> dict[str, Any]:
    return {
        "language": "de",
        "result_rev": 2,
        "turns": [
            {"speaker": t.speaker_label, "name": t.speaker_name, "start_ms": t.start_ms,
             "end_ms": t.end_ms, "paragraphs": [t.text], **({"language": t.language} if t.language else {})}
            for t in TURNS
        ],
    }  # fmt: skip


def _extract(_facts: Any) -> dict[str, Any]:
    return {
        "topic_title": "Hilfe",
        "facts": [
            {"kind": "key_point", "text": _CONDITION_FACT,
             "quote": "only if both chambers of Congress approve the package", "turn": 1,
             "explicit": False},
            {"kind": "key_point", "text": ECONOMY.text, "quote": ECONOMY.quote, "turn": 0,
             "explicit": False},
        ],
        "noise": [],
    }  # fmt: skip


def _corrupt(facts: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """The composer drops the condition and turns 'worse' into 'better'."""
    out = []
    for fid, _kind, text in facts:
        text = text.replace(", wenn beide Kammern zustimmen", "").replace(" nur", "")
        out.append((fid, text.replace("schlechter", "besser")))
    return out


def _run(final: bool) -> tuple[pipeline.DocumentResult, Judge]:
    judge = Judge(
        overrides={
            "extract": _extract,
            "block": lambda facts: {
                "heading": "Hilfe und Lage",
                "bullets": [{"text": t, "fact_ids": [i]} for i, t in _corrupt(facts)],
            },
            "summary": lambda facts: {
                "summary": [{"sentence": f"{t}.", "fact_ids": [i]} for i, t in _corrupt(facts)]
            },
        },
        rules=[
            ("besser", schema.CONTRADICTED, None),
            ("=Die Hilfsgelder fließen", schema.CONTRADICTED, None),
        ],
    )
    # Extraction's own check sees only the correct facts: rules never fire there.
    document = asyncio.run(
        pipeline.run(
            _broadcast(),
            provider=judge,
            role_by_key={},
            output_language="de",
            meeting_date=DAY,
            multilingual=True,
            fidelity=True,
            final=final,
        )
    )
    return document, judge


def test_a_corrupting_composer_after_a_correct_extractor_never_reaches_the_note() -> None:
    document, _judge = _run(final=False)
    before = " ".join(ln.text for _k, ln in document.lines)
    # Without the final check the composer's inversion passes the word gate into the prose…
    assert "besser" in before
    document, judge = _run(final=True)
    document = asyncio.run(pipeline.finalize(document))
    after = " ".join(ln.text for _k, ln in document.lines)
    # …with it, never: every inverted or condition-less line is corrected, restored or held.
    assert "besser" not in after
    assert "Die Hilfsgelder fließen.." in before and "Die Hilfsgelder fließen." not in after
    assert "schlechter" in after and "nur, wenn beide Kammern zustimmen" in after
    stats = document.stats["final_check"]
    assert stats["ran"] and stats["contradicted"] >= 1
    assert any(step == "checks" for step, _p, _s in judge.calls)


# ── F1-01: what produced a run ──────────────────────────────────────


def test_a_pinned_job_runs_with_its_snapshot_and_says_so() -> None:
    pinned = {
        "multilingual": True,
        "fidelity": True,
        "algorithm_version": profiles.ALGORITHM_VERSION,
        "build_sha": "abc1234",
        "config": {},
    }
    deps = SimpleNamespace(
        multilingual_evidence=False,
        fidelity=False,
        build_sha="def5678",
        fallbacks=lambda: [
            {"kind": "summarize", "backend": "mistral_eu_small", "primary": "mistral_eu",
             "fallback": "mistral_eu_small", "reason": "probe_failed"}
        ],
    )  # fmt: skip
    row = SimpleNamespace(config_snapshot=pinned)
    snapshot, multilingual, fidelity, _config = generate_note.run_configuration(row, deps)
    assert (multilingual, fidelity) == (True, True)
    runtime = generate_note.provenance(
        snapshot, deps, multilingual=multilingual, fidelity=fidelity, final=True
    )
    assert runtime["flags_source"] == "snapshot" and runtime["flags"] == {
        "multilingual": True,
        "fidelity": True,
    }
    # The worker's deployment disagrees: the job runs as pinned, and the run says so.
    assert runtime["flags_differ"] == ["fidelity", "multilingual"]
    assert runtime["build_sha"] == "def5678" and runtime["pinned_build_sha"] == "abc1234"
    assert runtime["fallbacks"][0]["reason"] == "probe_failed"


def test_a_row_from_before_snapshots_runs_on_the_deployment_and_says_so() -> None:
    deps = SimpleNamespace(multilingual_evidence=True, fidelity=False, build_sha="", fallbacks=None)
    snapshot, multilingual, fidelity, _ = generate_note.run_configuration(
        SimpleNamespace(config_snapshot=None), deps
    )
    runtime = generate_note.provenance(
        snapshot, deps, multilingual=multilingual, fidelity=fidelity, final=False
    )
    assert runtime["flags_source"] == "deployment" and runtime["flags_differ"] == []
    assert runtime["build_sha"] is None


def test_a_job_pinned_before_the_final_check_runs_without_it() -> None:
    assert not generate_note.final_check_pinned({"algorithm_version": profiles.FIDELITY_ALGORITHM})
    assert generate_note.final_check_pinned({"algorithm_version": profiles.ALGORITHM_VERSION})
    assert generate_note.final_check_pinned({})
    # A profile version saved for the fidelity algorithm can still be activated.
    assert (
        profiles.compatible(
            contract_version=profiles.CONTRACT_VERSION,
            schema=profiles.schema_version(),
            algorithm_version=profiles.FIDELITY_ALGORITHM,
        )
        is None
    )


def test_the_snapshot_labels_the_run_and_pins_the_code() -> None:
    snap = profiles.snapshot(
        profiles.BUNDLED,
        version_id=None,
        version_hash=None,
        multilingual=True,
        fidelity=True,
        language_hint="de",
        models={},
        build_sha="abc1234",
        run_kind="experiment",
    )
    assert snap["run_kind"] == "experiment" and snap["build_sha"] == "abc1234"
    assert snap["algorithm_version"] == profiles.ALGORITHM_VERSION


def test_the_view_shows_provenance_while_queued_and_after_the_run() -> None:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "id": uuid4(), "status": "queued", "step": None, "windows_total": None,
        "windows_done": None, "windows_failed": None, "failed_ranges": [],
        "prompt_version": prompts.PROMPT_VERSION, "model_id": None, "error_kind": None,
        "created_at": now, "finished_at": None, "transcript_rev": 4,
    }  # fmt: skip
    pinned = {"multilingual": True, "fidelity": False, "build_sha": "abc1234",
              "algorithm_version": profiles.ALGORITHM_VERSION, "output_language": "auto",
              "profile_version_id": "v1"}  # fmt: skip
    queued = notes_generation._view(SimpleNamespace(**base, stats={}, config_snapshot=pinned))
    assert queued.provenance is not None
    assert queued.provenance.flags_source == "snapshot" and queued.provenance.fidelity is False
    assert queued.provenance.pinned_build_sha == "abc1234" and queued.provenance.transcript_rev == 4

    stats = {
        "runtime": {"run_kind": "generation", "build_sha": "def5678", "flags_source": "snapshot",
                    "flags": {"multilingual": True, "fidelity": False}, "final_check": False,
                    "flags_differ": ["fidelity"], "fallbacks": []},
        "final_check": {"ran": False},
        "output_language": "de", "output_language_source": "dominant",
        "calls": [{"stage": "verification", "backend": "mistral_eu", "model_id": "mistral-large-2512",
                   "calls": 3, "failed": 1}],
    }  # fmt: skip
    done = notes_generation._view(
        SimpleNamespace(**{**base, "status": "complete"}, stats=stats, config_snapshot=pinned)
    )
    p = done.provenance
    assert p is not None and p.build_sha == "def5678" and p.final_check is False
    assert p.flags_differ == ["fidelity"] and p.output_language_source == "dominant"
    assert p.stages[0].model_id == "mistral-large-2512" and p.stages[0].failed == 1


def test_every_stage_is_metered_even_without_a_profile() -> None:
    provider = ScriptedProvider()
    deps = SimpleNamespace(provider_named=None)
    staged, meters = asyncio.run(
        generate_note._stage_providers(deps, provider, profiles.BUNDLED, {})
    )
    assert set(staged) == {*profiles.STAGES, "final_check"} and len(meters) == 4
    assert staged["final_check"].backend == provider.backend


def test_review_line_keeps_the_words_and_the_citations() -> None:
    rejected = final_check.Rejected(
        "gen:x", Line("  - Ein Satz", "bullet", ("a", "b"), parent="- P"), "contradicted"
    )
    line = final_check.review_line(rejected)
    assert line.text == "Ein Satz" and line.fact_ids == ("a", "b") and line.parent is None
