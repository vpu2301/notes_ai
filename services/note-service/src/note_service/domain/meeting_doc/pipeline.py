"""Transcript in, document out: windows → extract → verify → merge → context → reduce → render.

Every model claim is verified against the spoken words; a failed window is reported,
never silently dropped. `run()` serves both the worker and the eval harness.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final, Protocol

from . import (
    classify,
    compose,
    doclint,
    entities,
    numbers,
    overview,
    prompts,
    render,
    roles,
    roles_table,
    schema,
    support,
    types,
    verify,
    windows,
)
from . import merge as merge_rules
from .verify import PARAPHRASE_UNSUPPORTED, VerifiedFact
from .windows import Window

logger = logging.getLogger(__name__)

# One retry on a malformed answer; then the window is reported as failed.
EXTRACT_ATTEMPTS = 2
# Budgets sized from the schema caps, not a typical answer: smaller values cut
# a full answer off mid-JSON (`context_exceeded`) and failed every window.
EXTRACT_MAX_TOKENS = 3000
REDUCE_MAX_TOKENS = 2500
# Any copied fact triggers one restate call per window (a higher share lost recall).
RESTATE_COPY_SHARE: Final = 0.0
RESTATE_MIN_FACTS: Final = 1
# A sub-point citing only its parent's facts with mostly the same words is a restatement.
CHILD_RESTATES_JACCARD: Final = 0.6

# Small-model profile (config/models.yaml `small_model`): changes what the model
# is asked, never what code accepts. Window budget: one fact per 500 chars, 8..12.
SMALL_MODEL_MAX_FACTS: Final = 12
SMALL_MODEL_MIN_FACTS: Final = 8
SMALL_MODEL_CHARS_PER_FACT: Final = 500
SMALL_MODEL_REDUCE_FACTS: Final = 15
HEADING_MAX_TOKENS: Final = 120

# Coverage guard: a third with >= 3 min of speech and facts/minute below 0.6 of
# the best third is re-read once; still thin afterwards, it is named in coverage_gaps.
COVERAGE_MIN_MINUTES: Final = 3.0
COVERAGE_RETRY_SHARE: Final = 0.6
COVERAGE_GAP_SHARE: Final = 0.6
COVERAGE_WINDOW_BASE: Final = 1000

# Sub-point: ``(text, fact ids)`` or ``(text, fact ids, "quote")`` for a code-written quote.
Child = tuple[str, list[str]] | tuple[str, list[str], str]
QUOTE: Final = "quote"
Bullet = tuple[str, list[str], list[Child]]
Topics = list[tuple[str, list[Bullet], list[str]]]


class ChatLike(Protocol):
    backend: str
    model_id: str
    # Providers without the attribute are capable.
    small_model: bool

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> Any: ...


def small_model(provider: ChatLike) -> bool:
    """Whether the small-model profile applies; a provider without the attribute is capable."""
    return bool(getattr(provider, "small_model", False))


@dataclass(slots=True)
class DocumentResult:
    """What one generation produced."""

    sections: list[render.RenderedSection] = field(default_factory=list)
    facts: list[VerifiedFact] = field(default_factory=list)
    windows_total: int = 0
    windows_done: int = 0
    windows_failed: int = 0
    """``[[start_ms, end_ms]]`` of the parts that could not be processed —
    so the note can say WHICH minutes are missing instead of apologising
    in general."""
    failed_ranges: list[list[int]] = field(default_factory=list)
    """``[[start_ms, end_ms]]`` of thirds still thin after the coverage retry; also in ``failed_ranges``."""
    coverage_gaps: list[list[int]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    backend: str | None = None
    model_id: str | None = None
    """Carried items the recording says are done, and judgement values offered; neither is a line."""
    completions: list[VerifiedFact] = field(default_factory=list)
    judgements: list[VerifiedFact] = field(default_factory=list)
    """What the context pass understood — type, subject, themes, framing,
    key fact ids. Counts and short strings; no transcript."""
    brief: dict[str, Any] = field(default_factory=dict)
    """``[(start_ms, reason)]`` — passages the extractor set aside."""
    noise: list[tuple[int, str]] = field(default_factory=list)
    """``[(start_ms, end_ms, reason)]`` — the same passages with their
    end, so the eval can say how much SPEECH was set aside, not how many
    passages."""
    noise_ranges: list[tuple[int, int, str]] = field(default_factory=list)
    """The lines left out, CONFIRMED by code and within the cap; ``noise`` and ``noise_ranges`` derive from it."""
    excluded: list[verify.Exclusion] = field(default_factory=list)
    """The regeneration hook for this run (``doclint.Regenerate``). Not data; never stored."""
    regenerator: Any = field(default=None, repr=False, compare=False)

    @property
    def partial(self) -> bool:
        return self.windows_failed > 0 or bool(self.coverage_gaps)

    @property
    def lines(self) -> list[tuple[str, render.Line]]:
        """``[(section_key, line)]`` — every written line of the document,
        in the order the sections are written."""
        return [(s.section_key, line) for s in self.sections for line in s.lines]


MARKER_REASONS = frozenset({"music", "noise"})


def transcript_markers(result: dict[str, Any]) -> list[verify.Exclusion]:
    """The ASR result's non-speech markers the note lists: music and noise, never silence."""
    out: list[verify.Exclusion] = []
    for item in result.get("noise") or []:
        try:
            start, end = int(item["start_ms"]), int(item["end_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        kind = str(item.get("kind") or "noise")
        if kind == "silence" or end <= start:
            continue
        out.append(verify.Exclusion(-1, start, end, kind if kind in MARKER_REASONS else "noise"))
    return out


async def run(
    result: dict[str, Any],
    *,
    provider: ChatLike,
    role_by_key: dict[str, str],
    language: str = "en",
    meeting_date: date | None = None,
    name_candidates: frozenset[str] = frozenset(),
    max_concurrency: int = 4,
    family: types.Family | None = None,
    carried: list[tuple[str, str]] | None = None,
    our_side: frozenset[str] = frozenset(),
    counterpart: str = "",
    built: list[Window] | None = None,
    recording_type: str | None = None,
    recording_type_source: str | None = None,
    glossary: tuple[Any, ...] = (),
    entity_model_tier: bool = False,
    entity_provider: ChatLike | None = None,
    retry_budget_s: float | None = None,
) -> DocumentResult:
    """Build a document from an ASR result.

    ``retry_budget_s``: past this, the coverage retry is skipped and a thin third
    is reported as a gap. ``entity_provider`` answers the entity tier (defaults to
    ``provider``). ``carried`` is ``[(item_key, text)]`` of still-open items the
    extractor may mark done by their NUMBER in this list, never by free text.
    """
    started = time.monotonic()
    family = family or types.FALLBACK
    small = small_model(provider)
    sizes = sizes_for(provider)
    kinds = types.fact_kinds(family)
    # `user_point` is the author's own; the engine never proposes one.
    offered = tuple(k for k in kinds if k != "user_point")
    if family.judgement_fields:
        offered = (*offered, schema.JUDGEMENT)
    carried = carried or []
    carried_keys = tuple(key for key, _ in carried)
    turns = windows.turns_from_result(result)
    # Adverts are cut and micro-turns merged before windowing; if that changed
    # anything, the worker's classification windows are rebuilt.
    raw_turns = list(turns)  # the roles table reads every voice, adverts included
    prepared = windows.prepare_turns(turns)
    if prepared.adverts or prepared.microturns_merged:
        turns = prepared.turns
        built = None
    # The worker builds the windows once (for classification) and hands them in.
    built = (
        built if built is not None else windows.build_windows(turns, max_chars=sizes.window_chars)
    )
    meeting_date = meeting_date or date.today()
    out = DocumentResult(
        windows_total=len(built), backend=provider.backend, model_id=provider.model_id
    )
    if not built:
        out.stats = {"reason": "empty_transcript"}
        return out

    stats = verify.VerifyStats()
    verified: list[VerifiedFact] = []
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    # Introduction lines in the first windows, pointed out to the extractor.
    suggested_quotes = [
        str(s.get("quote") or "")
        for s in (result.get("name_suggestions") or [])
        if isinstance(s, dict)
    ]

    def hints(window: Window) -> list[int] | None:
        if schema.INTRODUCTION not in offered or window.index >= INTRODUCTION_WINDOWS:
            return None
        return introduction_lines(window, suggested_quotes) or None

    def contact_hints(window: Window) -> list[int] | None:
        if schema.NEXT_STEP not in offered:
            return None
        return [t.number for t in window.turns if verify.calls_to_action(t.text, language)] or None

    async def one(window: Window) -> tuple[Window, schema.ExtractOut | None]:
        budget = small_budget(window) if small else fact_budget(window, sizes.max_facts_budget)
        window_schema = schema.extract_schema(
            offered,
            judgement_fields=family.judgement_fields,
            carried_items=len(carried),
            max_facts=budget,
            noise=not small,
        )
        async with semaphore:
            return window, await _extract(
                provider,
                window,
                language,
                window_schema,
                carried=carried,
                max_facts=budget,
                max_tokens=extract_tokens(budget),
                introduction_lines=hints(window),
                contact_lines=contact_hints(window),
                small=small,
            )

    extracted_windows = await asyncio.gather(*(one(w) for w in built))

    # Noise first, across the whole recording: the model's flags are
    # checked by code, and the cap needs every window's exclusions.
    flagged = advisory = 0
    confirmed: dict[int, verify.Exclusion] = {}
    previous: Window | None = None
    for window, extracted in extracted_windows:
        if extracted is None:
            previous = window
            continue
        flags = _noise_lines(extracted, window) + _language_lines(window, language)
        flagged += len(flags)
        own = window.turn_numbers
        seen = tuple(t.text for t in previous.turns if t.number not in own) if previous else ()
        ok, not_ok = verify.confirm_noise(
            [(line, reason) for line, _s, _e, reason in flags],
            window=window,
            language=language,
            seen_pieces=seen,
        )
        advisory += len(not_ok)
        for exclusion in ok:
            confirmed.setdefault(exclusion.line, exclusion)
        previous = window
    speech_ms = sum(max(0, t.end_ms - t.start_ms) for t in turns)
    excluded, overridden = verify.cap_exclusions(
        sorted(confirmed.values(), key=lambda e: e.start_ms), speech_ms=speech_ms
    )
    noise_lines = frozenset(e.line for e in excluded)
    # Adverts are confirmed by code already (a cue, at the edge or between
    # two turns of the same speaker) and cut; they are listed, not capped.
    excluded = sorted(
        [*excluded, *(verify.Exclusion(-1, a, b, "advertisement") for a, b in prepared.adverts)],
        key=lambda e: e.start_ms,
    )
    out.excluded = excluded
    # Transcript music/noise markers are listed but not counted in
    # ``noise_ranges`` / ``excluded_ms`` (those measure speech set aside).
    markers = transcript_markers(result)
    out.noise = sorted({(e.start_ms, e.reason) for e in [*excluded, *markers]})
    out.noise_ranges = sorted({(e.start_ms, e.end_ms, e.reason) for e in excluded})

    # Words the recording spells three times or more; then those that are names (not German nouns).
    rec_names = support.recording_names([t.text for t in turns])
    rec_proper = support.proper_names([t.text for t in turns], rec_names, language)

    def check(
        facts: list[schema.Fact], window: Window, into: verify.VerifyStats
    ) -> list[VerifiedFact]:
        return verify.verify_facts(
            facts,
            window=window,
            meeting_date=meeting_date,
            name_candidates=name_candidates,
            stats=into,
            allowed_kinds=frozenset(offered),
            judgement_fields=frozenset(family.judgement_fields),
            carried_keys=carried_keys,
            our_side=our_side,
            noise_lines=noise_lines,
            language=language,
            glossary=tuple(glossary),
            recording_names=rec_names,
        )

    restate = {"improved": 0, "unchanged": 0}
    details_asked = 0
    # Per-window diagnosis, numbers only.
    per_window: dict[int, dict[str, int]] = {
        w.index: {
            "index": w.index,
            "start_ms": w.start_ms,
            "end_ms": w.end_ms,
            "chars": len(w.text),
            "budget": small_budget(w) if small else fact_budget(w, sizes.max_facts_budget),
            "facts_extracted": 0,
            "facts_verified": 0,
            "facts_kept_after_merge": 0,
            "call_failed": 0,
            # A model that reads only the head of a long window shows here.
            "facts_first_half": 0,
            "facts_second_half": 0,
        }
        for w in built
    }
    # A figures table is for a demonstration or a lecture.
    tables = recording_type is None or recording_type in TABLE_TYPES
    for window, extracted in extracted_windows:
        if extracted is None:
            out.windows_failed += 1
            out.failed_ranges.append([window.start_ms, window.end_ms])
            per_window[window.index]["call_failed"] = 1
            continue
        out.windows_done += 1
        per_window[window.index]["facts_extracted"] = len(extracted.facts)
        asked, twins = await _figure_details(
            provider, window, extracted, language, promote=schema.FIGURE in offered
        )
        details_asked += asked
        if schema.NEXT_STEP in offered:
            twins += _contact_twins(extracted, language)
            twins += await _contact_details(
                provider, window, [*extracted.facts, *twins], language, contact_hints(window)
            )
        await _person_details(provider, window, extracted, language)
        kept = check([*extracted.facts, *twins], window, stats)
        if tables:
            # A verified figure replaces its key point only where figures are tabled.
            kept = _without_figure_twins(kept)
        # Figures and introductions are written from their payload: a copy is no reason to restate.
        copies = sum(1 for f in kept if f.copied and f.figure is None and f.person is None)
        if copies and len(kept) >= RESTATE_MIN_FACTS and copies / len(kept) > RESTATE_COPY_SHARE:
            # Once per window, told the rule it broke, same budget as the first answer.
            again_budget = max(1, len(extracted.facts))
            again = await _extract(
                provider,
                window,
                language,
                schema.extract_schema(
                    offered,
                    judgement_fields=family.judgement_fields,
                    carried_items=len(carried),
                    max_facts=again_budget,
                    noise=not small,
                ),
                carried=carried,
                max_facts=again_budget,
                max_tokens=extract_tokens(again_budget),
                system_suffix=prompts.restate_suffix(language),
                small=small,
            )
            second = check(again.facts, window, verify.VerifyStats()) if again else []
            kept, replaced = restated(kept, second)
            restate["improved" if replaced else "unchanged"] += 1
        per_window[window.index]["facts_verified"] = len(kept)
        middle = (window.start_ms + window.end_ms) / 2
        for fact in kept:
            half = "facts_first_half" if fact.start_ms < middle else "facts_second_half"
            per_window[window.index][half] += 1
        verified.extend(kept)

    # ── coverage guard ──────────────────────────────────────────────
    span_start, span_end = (turns[0].start_ms, turns[-1].end_ms) if turns else (0, 1)
    bounds = [span_start + round((span_end - span_start) * k / 3) for k in range(4)]
    third_minutes = [
        sum(max(0, min(t.end_ms, bounds[k + 1]) - max(t.start_ms, bounds[k])) for t in turns)
        / 60_000
        for k in range(3)
    ]

    def rates(found: Sequence[VerifiedFact]) -> list[float]:
        counts = [0, 0, 0]
        for fact in found:
            if fact.kind in (schema.COMPLETION, schema.JUDGEMENT):
                continue
            counts[windows.third_of(fact.start_ms, span_start, span_end) - 1] += 1
        return [counts[k] / third_minutes[k] if third_minutes[k] else 0.0 for k in range(3)]

    def thin(found: Sequence[VerifiedFact], share: float) -> list[int]:
        per = rates(found)
        best = max(per)
        return [
            k
            for k in range(3)
            if third_minutes[k] >= COVERAGE_MIN_MINUTES and (best == 0 or per[k] < share * best)
        ]

    coverage_retry: list[int] = []
    coverage_retry_facts = 0
    coverage_retry_skipped: str | None = None
    retry_thirds = thin(verified, COVERAGE_RETRY_SHARE)
    if (
        retry_thirds
        and retry_budget_s is not None
        and (time.monotonic() - started > retry_budget_s)
    ):
        coverage_retry_skipped = "budget"
        retry_thirds = []
    retry_semaphore = asyncio.Semaphore(BLOCK_CONCURRENCY)

    async def reread(k: int, window: Window) -> list[VerifiedFact]:
        a, b = bounds[k], bounds[k + 1]
        known_ids = [f.item_key for f in verified if a <= f.start_ms < b]
        budget = small_budget(window) if small else fact_budget(window, sizes.max_facts_budget)
        async with retry_semaphore:
            again = await _extract(
                provider,
                window,
                language,
                schema.extract_schema(
                    offered,
                    judgement_fields=family.judgement_fields,
                    carried_items=len(carried),
                    max_facts=budget,
                    noise=not small,
                ),
                carried=carried,
                max_facts=budget,
                max_tokens=extract_tokens(budget),
                system_suffix=prompts.coverage_suffix(
                    language, window.start_ms, window.end_ms, known_ids
                ),
                small=small,
            )
        if again is None:
            return []
        kept = check(again.facts, window, stats)
        per_window[window.index] = {
            "index": window.index,
            "start_ms": window.start_ms,
            "end_ms": window.end_ms,
            "chars": len(window.text),
            "budget": budget,
            "facts_extracted": len(again.facts),
            "facts_verified": len(kept),
            "facts_kept_after_merge": 0,
            "call_failed": 0,
            "facts_first_half": 0,
            "facts_second_half": 0,
            "coverage_retry": 1,
        }
        middle = (window.start_ms + window.end_ms) / 2
        for fact in kept:
            half = "facts_first_half" if fact.start_ms < middle else "facts_second_half"
            per_window[window.index][half] += 1
        return kept

    jobs = []
    for k in retry_thirds:
        third_turns = [t for t in turns if bounds[k] <= t.start_ms < bounds[k + 1]]
        for i, window in enumerate(
            windows.build_windows(third_turns, max_chars=sizes.window_chars)
        ):
            jobs.append(
                reread(k, dataclasses.replace(window, index=COVERAGE_WINDOW_BASE + 100 * k + i))
            )
        coverage_retry.append(k + 1)
    for kept in await asyncio.gather(*jobs):
        coverage_retry_facts += len(kept)
        verified.extend(kept)

    facts = merge_rules.merge_facts(verified)
    # Still thin after the retry: named, never silent (same rule as doclint ``coverage.thirds``).
    out.coverage_gaps = [[bounds[k], bounds[k + 1]] for k in thin(facts, COVERAGE_GAP_SHARE)]
    out.failed_ranges.extend(out.coverage_gaps)
    for fact in facts:
        if fact.window_index in per_window:
            per_window[fact.window_index]["facts_kept_after_merge"] += 1
    # Who each voice is to this recording, by code.
    table = roles_table.build(
        raw_turns,
        [f for f in facts if f.person is not None],
        recording_type,
        prepared.adverts,
        broadcast=(recording_type or "") in roles_table.BROADCAST
        or family.meeting_type == "broadcast",
    )
    facts = [
        dataclasses.replace(
            f, person=dataclasses.replace(f.person, standing=roles_table.standing(f, table))
        )
        if f.person is not None
        else f
        for f in facts
    ]
    # Cues settle a close call between a lecture and a podcast.
    cue_type, type_cues = classify.type_cues(raw_turns, table, prepared.adverts)
    if (
        recording_type in classify.CUE_PAIR
        and recording_type_source != classify.SOURCE_USER
        and cue_type
        and cue_type != recording_type
    ):
        recording_type, recording_type_source = cue_type, classify.SOURCE_CUES
    # Narrators report; they do not hold.
    facts, reattributed = _narrator_attribution(facts, table, recording_type)
    out.facts = facts
    # Completions and judgements are not lines of the document: one
    # ticks a carried item off, the other is offered under a field.
    document_facts = [f for f in facts if f.kind not in (schema.COMPLETION, schema.JUDGEMENT)]
    out.completions = [f for f in facts if f.kind == schema.COMPLETION]
    out.judgements = [f for f in facts if f.kind == schema.JUDGEMENT]

    topics: Topics | None = None
    tops: list[VerifiedFact] = []
    parts: list[compose.Block] = []
    segmentation: compose.Segmentation | None = None
    blocks_merged = 0
    summary: list[tuple[str, list[str]]] | None = None
    brief: Brief | None = None
    entity_stats: dict[str, int] = {"seen": 0, "model_failed": 0, "marked": 0, "model": 0}
    # A person introduced in the recording is somebody a line may name.
    introduced = {f.person.name for f in document_facts if f.person is not None}
    gate = _Gate(
        language=language,
        known=frozenset(
            {t.speaker_name for t in turns if t.speaker_name}
            | set(name_candidates)
            | introduced
            | rec_names
        ),
        reduce_tokens=sizes.reduce_max_tokens,
    )

    if document_facts:
        # Understand the conversation first; then write topics and the
        # summary about it, side by side.
        brief = await _context(provider, document_facts, language, gate=gate)
        # Names nobody in the workspace knows, asked of the model once before writing.
        people = gate.known | {g.term for g in glossary if getattr(g, "kind", "") == "person"}
        renamed = await _model_names(
            entity_provider or provider,
            document_facts,
            brief,
            people=frozenset(people),
            entity=entity_stats,
            enabled=entity_model_tier,
        )
        if renamed and brief is not None:
            brief.key_fact_ids = [renamed.get(i, i) for i in brief.key_fact_ids]
        gate.known = frozenset(
            gate.known | {c.canonical for f in document_facts for c in f.corrections}
        )
        gate.people = frozenset(
            w
            for n in (gate.known - rec_names) | rec_proper
            if n and not _DEFAULT_NAME.match(n.strip())
            for w in (n, *n.split())
        )
        # Budget from the length of speech, one reduce per block, headings merged
        # within the section band; paragraph 2 follows the blocks.
        excluded_speech = sum(max(0, e.end_ms - e.start_ms) for e in excluded)
        minutes = max(0, speech_ms - excluded_speech) / 60_000
        # Parts come from the transcript (cues, then lexical shifts), not from fact positions.
        segmentation = compose.segment(
            turns, minutes, language, classify.structure_cues(turns, language)
        )
        parts, blocks_merged = compose.blocks_at(document_facts, segmentation)
        budget = compose.VolumeBudget(minutes, len(parts))
        topics = await _reduce_blocks(
            provider,
            parts,
            language,
            budget,
            brief=brief,
            gate=gate,
            table=table,
            minutes=minutes,
            small=small,
        )
        if topics:
            # An uncited fact with a number, a date or a holder is kept.
            _append_salient(topics, document_facts, gate)
        tops = compose.top_per_block(parts, language, gate.people)
        summary = await _summary(
            provider,
            document_facts,
            language,
            brief=brief,
            gate=gate,
            headings=[t[0] for t in topics or []],
            skeleton_ids=[f.item_key for f in tops],
            small=small,
        )
    topics_fallback: str | None = "chapters" if gate.block_chapters else None
    # Rung 3: when both model rungs failed, prose composed from each block's most specific fact.
    ladder = gate.summary_rung if summary else None
    if document_facts and not summary:
        summary = (
            overview.composed_sentences(
                document_facts,
                language=language,
                known=gate.known,
                key_ids=[f.item_key for f in tops] or (brief.key_fact_ids if brief else None),
            )
            or None
        )
        ladder = "composed" if summary else None
    if brief is not None:
        out.brief = {
            "conversation_type": brief.conversation_type,
            "subject": brief.subject,
            "themes": brief.themes,
            "key_fact_ids": brief.key_fact_ids,
        }

    key_fact_ids = brief.key_fact_ids if brief else None
    fallback: str | None = None
    if document_facts and summary is None and topics is None:
        fallback = "key_facts"
        if not key_fact_ids:
            key_fact_ids = _earliest_per_window(document_facts)
    # Paragraph 1 is built by code; the model's framing replaces only its first clause.
    opening = ""
    if document_facts:
        speakers, guests, others = compose.speakers_of(table, language)
        show = compose.show_name(raw_turns)
        orientation: dict[str, Any] = {
            "subject": _gated_phrase(brief.subject if brief else "", document_facts, gate),
            "framing": brief.framing if brief else "",
            "speakers": speakers,
            "guests": guests,
            "others": others,
            "themes": [
                t
                for t in compose.clean_themes(brief.themes if brief else [])
                if _gated_phrase(t, document_facts, gate)
            ][: compose.MAX_THEMES],
        }
        opening = compose.orientation_p1(
            language=language,
            recording_type=recording_type,
            table=table,
            subject=str(orientation["subject"]),
            framing=str(orientation["framing"]),
            themes=list(orientation["themes"]),
            show=show,
        )
        # Verified roles/values paragraph 1 is built from (doclint.p1_faults rebuilds it).
        # Only verified names: never frequent capitalised words or a default label.
        names = sorted(
            n
            for n in (gate.known - rec_names) | rec_proper
            if n and not _DEFAULT_NAME.match(n.strip())
        )
        out.brief = {
            **out.brief,
            "orientation": {**orientation, "names": names, "show": show},
            "roles": table.as_stats(),
        }

    render_counts: dict[str, int] = {}
    out.sections = render.render_sections(
        document_facts,
        role_by_key=role_by_key,
        topics=topics,
        summary=summary,
        kind_roles=kinds,
        language=language,
        counterpart=counterpart,
        framing=opening,
        key_fact_ids=key_fact_ids,
        counters=render_counts,
        meeting_date=meeting_date,
        presenter_lines=family.meeting_type == "broadcast",
        subject=brief.subject if brief else "",
        figure_tables=tables,
        recording_names=gate.known,
    )
    # Thirds by TIME over the speech, not by window.
    span = (turns[0].start_ms, turns[-1].end_ms) if turns else (0, 1)

    def third(ms: int) -> int:
        return windows.third_of(ms, *span)

    by_third = [0, 0, 0]
    for fact in document_facts:
        by_third[third(fact.start_ms) - 1] += 1
    by_id_all = {f.item_key: f for f in document_facts}
    cited_ids = {
        i
        for _h, bullets, _ids in topics or []
        for _t, ids, children in bullets
        for i in [*ids, *(c for child in children for c in child[1])]
        if i in by_id_all
    }
    cited_by_third = [0, 0, 0]
    for key in cited_ids:
        cited_by_third[third(by_id_all[key].start_ms) - 1] += 1
    excluded_ms = sum(max(0, e.end_ms - e.start_ms) for e in excluded)
    out.stats = {
        "facts_kept": stats.kept,
        "facts_dropped_quote": stats.dropped_quote,
        "facts_dropped_noise": stats.dropped_noise,
        "facts_dropped_example": stats.dropped_example,
        "facts_dropped_paraphrase": stats.dropped_paraphrase,
        "facts_flagged_paraphrase": stats.flagged_paraphrase,
        "facts_copied": sum(1 for f in facts if f.copied),
        "windows_restated": restate["improved"] + restate["unchanged"],
        "restate_outcomes": dict(restate),
        "dropped_no_information": stats.dropped_no_information,
        "dropped_first_person": stats.dropped_first_person,
        "facts_descriptive": stats.descriptive,
        "recording_names": len(rec_names),
        "third_person_fixed": stats.third_person_fixed + gate.third_person_fixed,
        "children_restated": gate.children_restated,
        "microturns_merged": prepared.microturns_merged,
        "adverts_cut": len(prepared.adverts),
        "figure_details_asked": details_asked,
        "figures_kept": stats.figures_kept,
        "figures_dropped_value": stats.figures_dropped_value,
        "figures_dropped_unit": stats.figures_dropped_unit,
        "figures_dropped_unit_lost": stats.figures_dropped_unit_lost,
        "figures_dropped_name": stats.figures_dropped_name,
        "qualifiers_cleared": stats.qualifiers_cleared,
        "introductions_kept": stats.introductions_kept,
        "introductions_demoted": stats.introductions_demoted,
        "introduction_fields_cleared": stats.introduction_fields_cleared,
        "contact_steps": stats.contact_steps,
        "example_echo_dropped": gate.counts["example"],
        "lines_kept": gate.counts["kept"],
        "lines_unsupported": {
            reason: gate.counts[reason]
            for reason in (
                "unsupported",
                "number",
                "name",
                "example",
                "copied",
                "no_information",
                "first_person",
                "descriptive",
            )
        },
        "summary_retries": gate.retries,
        "summary_fallback": fallback,
        "summary_ladder": ladder,
        "topics_fallback": topics_fallback,
        "topics_failure": gate.topics_failure,
        "noise_passages": len(out.noise),
        "noise_flagged": flagged,
        "noise_confirmed": len(confirmed),
        "noise_advisory": advisory,
        "noise_overridden": overridden,
        "excluded_ms": excluded_ms,
        "speech_ms": speech_ms,
        "excluded_ranges": [
            [e.start_ms, e.end_ms, e.reason]
            for e in sorted([*excluded, *markers], key=lambda x: x.start_ms)
        ],
        "facts_by_third": by_third,
        "speech_minutes_by_third": [round(m, 2) for m in third_minutes],
        "coverage_retry": coverage_retry,
        "coverage_retry_facts": coverage_retry_facts,
        "coverage_retry_skipped": coverage_retry_skipped,
        "coverage_gaps": len(out.coverage_gaps),
        "key_points": len(brief.key_fact_ids) if brief else 0,
        "facts_dropped_owner": stats.dropped_owner,
        "facts_downgraded": stats.downgraded,
        "numbers_removed": stats.numbers_removed,
        "invented_due": stats.invented_due,
        "facts_after_merge": len(facts),
        "prompt_version": prompts.PROMPT_VERSION,
        "section_hashes": section_hashes(out.sections),
        "redundant_lines": render_counts.get("redundant_lines", 0),
        "entities_seen": entity_stats["seen"],
        "entities_corrected": {
            "glossary": stats.corrected.get("glossary", 0),
            "candidate": stats.corrected.get("candidate", 0),
            "model": entity_stats["model"],
        },
        "entities_marked": stats.marked + entity_stats["marked"],
        "entities_model_failed": entity_stats["model_failed"],
        "attribution_set": {"model": stats.attribution_model, "speaker": stats.attribution_speaker},
        "attribution_missing": stats.attribution_missing,
        "salient_appended": gate.salient_appended,
        "salient_skipped_full": gate.salient_skipped_full,
        "topics_merged": gate.topics_merged,
        "blocks": gate.blocks,
        "block_calls": gate.block_calls,
        "block_chapters": gate.block_chapters,
        "block_failures": dict(gate.block_failures),
        "merges_applied": gate.topics_merged,
        "merges_refused": gate.merges_refused,
        "headings_retried": gate.headings_retried,
        "headings_fallback": gate.headings_fallback,
        "quote_children": gate.quote_children,
        "lines_dropped_subject": gate.counts["subject"],
        "lines_dropped_unspecific": gate.counts["unspecific"],
        "roles": table.as_stats(),
        "roles_ambiguous": table.ambiguous,
        "type_cues": type_cues,
        "narrator_reattributed": reattributed,
        "subject_unresolved": stats.subject_unresolved,
        "lines_by_third": _lines_by_third(out.sections, document_facts, third),
        "windows": [per_window[k] for k in sorted(per_window)],
        "reduce_input_facts": sum(len(b.facts) for b in parts),
        "reduce_cited_facts": len(cited_ids),
        "reduce_cited_by_third": cited_by_third,
        "excluded_speech_ms": excluded_ms,
        "blocks_planned": len(parts),
        "blocks_source": segmentation.source if segmentation else None,
        "blocks_boundaries": len(segmentation.boundaries) if segmentation else 0,
        "blocks_merged_small": blocks_merged,
        "blocks_rendered": len(topics or []),
        "sections_rendered": len(out.sections),
        "lines_total": sum(len(s.lines) for s in out.sections),
        "language": language,
        "recording_type": recording_type,
        "recording_type_source": recording_type_source,
        "small_model_profile": small,
        "window_chars": sizes.window_chars,
        "context_window": sizes.context_window,
    }

    async def regenerate(
        requests: list[doclint.RegenRequest], sections: list[render.RenderedSection]
    ) -> list[render.RenderedSection] | None:
        """``line.subject``: re-extract each window once, told to name every subject;
        a verified fact on the same line with a subject replaces the faulted line."""
        wanted = {i for r in requests if r.rule == "line.subject" for i in r.fact_ids}
        by_id = {f.item_key: f for f in out.facts}
        targets = {by_id[i].window_index for i in wanted if i in by_id}
        if not targets:
            return None
        replacements: dict[str, VerifiedFact] = {}
        for window in built:
            if window.index not in targets:
                continue
            allowance = (
                small_budget(window) if small else fact_budget(window, sizes.max_facts_budget)
            )
            again = await _extract(
                provider,
                window,
                language,
                schema.extract_schema(
                    offered,
                    judgement_fields=family.judgement_fields,
                    carried_items=len(carried),
                    max_facts=allowance,
                    noise=not small,
                ),
                carried=carried,
                max_facts=allowance,
                max_tokens=extract_tokens(allowance),
                system_suffix=prompts.subject_suffix(language),
                small=small,
            )
            if again is None:
                continue
            fresh = [
                f
                for f in check(again.facts, window, verify.VerifyStats())
                if f.subject and not f.evidence_only
            ]
            for old_id in wanted:
                old = by_id.get(old_id)
                if old is None or old.window_index != window.index or old_id in replacements:
                    continue
                match = next((f for f in fresh if f.turn == old.turn), None)
                if match is not None:
                    replacements[old_id] = match
        if not replacements:
            return None
        out.facts.extend(f for f in replacements.values() if f.item_key not in by_id)
        rebuilt = []
        for section in sections:
            lines, changed = [], False
            for line in section.lines:
                hit = next((replacements[i] for i in line.fact_ids if i in replacements), None)
                unnamed = support.pronoun_initial(line.text, language) or doclint.has_label(
                    line.text
                )
                if hit is not None and unnamed and line.kind in ("bullet", "summary"):
                    body = hit.text.strip().rstrip(".")
                    text = (
                        f"{'  ' if line.parent else ''}- {body}"
                        if line.kind == "bullet"
                        else f"{body}."
                    )
                    line = dataclasses.replace(line, text=text, fact_ids=(hit.item_key,))
                    changed = True
                lines.append(line)
            rebuilt.append(
                dataclasses.replace(
                    section, lines=tuple(lines), text=doclint.text_of(section, lines)
                )
                if changed
                else section
            )
        return rebuilt

    out.regenerator = regenerate
    return out


# Introductions happen at the start: only the first windows are searched.
INTRODUCTION_WINDOWS: Final = 2
_INTRODUCTION_CUE: Final = re.compile(
    r"\b(?:my name is|i'm|i’m|i am|this is|ich bin|ich heiße|ich heisse|mein name ist|"
    r"hier ist|мене звати|моє ім['’ʼ]я)\b|(?<![\w'’ʼ])(?:це|я)\s+[А-ЯІЇЄҐ]",
    re.IGNORECASE,
)


def introduction_lines(window: Window, suggested_quotes: list[str]) -> list[int]:
    """The window's line numbers that hold an introduction: a cue ("my name
    is", "ich bin", "мене звати") followed by a capitalised word, or the
    quote of an asr-service name suggestion."""
    out: list[int] = []
    quotes = [verify.normalise_quote(q) for q in suggested_quotes if q.strip()]
    for turn in window.turns:
        text = turn.text
        said = verify.normalise_quote(text)
        cue = _INTRODUCTION_CUE.search(text)
        named = cue is not None and any(
            w[:1].isupper() for w in text[cue.end() : cue.end() + 60].split()[:3]
        )
        if named or any(q and (q in said or said in q) for q in quotes):
            out.append(turn.number)
    return out


TABLE_TYPES: Final = frozenset({"presentation_demo", "lecture_webinar"})


def standing_of(fact: VerifiedFact, turns: list[windows.Turn]) -> str:
    """``presenter``, ``guest`` or ``clip`` for an introduction, from the roles table."""
    table = roles_table.build(turns, [fact], "podcast_broadcast")
    return roles_table.standing(fact, table)


def restated(
    first: list[VerifiedFact], second: list[VerifiedFact]
) -> tuple[list[VerifiedFact], int]:
    """Each copied first-answer fact is replaced by a non-copy second-answer fact
    citing the same line; others stay. ``(facts, how many were replaced)``."""
    spare: dict[int | None, list[VerifiedFact]] = {}
    for fact in second:
        if not fact.copied and not fact.evidence_only:
            spare.setdefault(fact.line, []).append(fact)
    out: list[VerifiedFact] = []
    replaced = 0
    for fact in first:
        payload = fact.figure is not None or fact.person is not None
        candidates = spare.get(fact.line) if fact.copied and not payload else None
        if candidates:
            out.append(candidates.pop(0))
            replaced += 1
        else:
            out.append(fact)
    return out, replaced


def small_budget(window: Window) -> int:
    """Small-model profile budget: ``clamp(chars // 500, 8, 12)``."""
    return max(
        SMALL_MODEL_MIN_FACTS,
        min(SMALL_MODEL_MAX_FACTS, len(window.text) // SMALL_MODEL_CHARS_PER_FACT),
    )


def fact_budget(window: Window, max_budget: int | None = None) -> int:
    """Facts a window may carry: one per ~250 characters, between 8 and 24."""
    cap = MAX_FACTS_BUDGET if max_budget is None else max_budget
    return min(cap, max(MIN_FACTS_BUDGET, len(window.text) // 250))


@dataclass(frozen=True, slots=True)
class Sizes:
    """Size constants for one backend's context."""

    context_window: int
    window_chars: int
    extract_max_tokens: int
    reduce_max_tokens: int
    max_facts_budget: int


def sizes_for(provider: ChatLike | None, context_window: int | None = None) -> Sizes:
    """Defaults on 32K and below; on >= 64K, 16 000-character windows and scaled budgets."""
    context = context_window or int(getattr(provider, "context_window", 0) or 0) or 32_768
    chars = windows.window_chars(context)
    scale = chars / windows.MAX_WINDOW_CHARS
    return Sizes(
        context_window=context,
        window_chars=chars,
        extract_max_tokens=round(EXTRACT_MAX_TOKENS * scale),
        reduce_max_tokens=round(REDUCE_MAX_TOKENS * (1 + (scale - 1) / 2)),
        max_facts_budget=round(MAX_FACTS_BUDGET * scale),
    )


def extract_tokens(max_facts: int) -> int:
    """Output budget for that many facts, each up to a sentence and a
    quote. Unused budget costs nothing; a cut-off answer costs the window."""
    return 250 * max_facts + 500


async def _model_names(
    provider: ChatLike,
    facts: list[VerifiedFact],
    brief: Brief | None,
    *,
    people: frozenset[str],
    entity: dict[str, int],
    enabled: bool,
) -> dict[str, str]:
    """Names nobody in the workspace knows, asked of the model once; returns
    ``{old item_key: new item_key}`` for facts whose text changed.

    A proposal applies only when similarity >= ``entities.MODEL_THRESHOLD`` and it
    is not another participant: the model may respell, never swap people."""
    if not enabled or not facts:
        return {}
    known = {p.casefold() for p in people} | {t.casefold() for p in people for t in p.split()}
    stops = frozenset().union(*support.STOP_WORDS.values())
    spans: list[str] = []
    for fact in facts:
        fixed = {c.canonical for c in fact.corrections}
        for span in entities.candidates_in(fact.text):
            parts = span.split()
            if (
                span in fixed
                or len(span) < entities.MIN_TOKEN_CHARS
                or span.casefold() in known
                or any(p.casefold() in known or p.casefold() in stops for p in parts)
            ):
                continue
            spans.append(span)
    spans = list(dict.fromkeys(spans))[: schema.MAX_ENTITY_SPANS]
    entity["seen"] = len(spans)
    if not spans:
        return {}
    try:
        answer = await provider.complete(
            prompts.entity_prompt(
                spans,
                subject=brief.subject if brief else "",
                themes=list(brief.themes) if brief else [],
            ),
            schema.ENTITY_SCHEMA,
            max_tokens=60 * len(spans) + 100,
            temperature=0.0,
            system=prompts.entity_system("en"),
        )
        import json

        payload = json.loads(_json_of(answer))
        proposals = payload.get("corrections", []) if isinstance(payload, dict) else []
    except Exception:  # noqa: BLE001 — no corrections is a note, not a failure
        logger.warning("meeting_doc.entities_failed", exc_info=True)
        entity["model_failed"] += 1
        return {}

    table: dict[str, entities.Correction] = {}
    doubted: set[str] = set()
    for item in proposals:
        surface = str(item.get("surface", "")).strip() if isinstance(item, dict) else ""
        canonical = (
            " ".join(str(item.get("canonical", "")).split()) if isinstance(item, dict) else ""
        )
        if surface not in spans or not canonical or canonical == surface:
            continue
        if canonical.casefold() in known or prompts.echoes_example(canonical):
            continue  # another participant, or a copied example: rejected
        if entities.similarity(surface, canonical) >= entities.MODEL_THRESHOLD:
            table[surface] = entities.Correction(surface, canonical, entities.SOURCE_MODEL)
        else:
            doubted.add(surface)

    renamed: dict[str, str] = {}
    for fact in facts:
        before = fact.item_key
        mine = {s: c for s, c in table.items() if _mentions(fact.text, s)}
        doubt = {s for s in doubted if _mentions(fact.text, s)}
        if not mine and not doubt:
            continue
        fact.text = entities.apply(fact.text, mine, doubt)
        if fact.owner_label:
            fact.owner_label = entities.apply(fact.owner_label, mine)
        if fact.attributed_to:
            fact.attributed_to = entities.apply(fact.attributed_to, mine)
        if mine:
            fact.corrections = (*fact.corrections, *mine.values())
            if verify.ENTITY_CORRECTED not in fact.flags:
                fact.flags.append(verify.ENTITY_CORRECTED)
        entity["model"] += len(mine)
        entity["marked"] += len(doubt)
        if fact.item_key != before:
            renamed[before] = fact.item_key
    return renamed


def _mentions(text: str, surface: str) -> bool:
    import re

    return re.search(rf"(?<!\w){re.escape(surface)}(?!\w)", text) is not None


def _lines_by_third(
    sections: list[render.RenderedSection],
    facts: list[VerifiedFact],
    third: Callable[[int], int],
) -> list[int]:
    """Written lines per third of the recording, by the time of their first cited fact."""
    by_id = {f.item_key: f for f in facts}
    out = [0, 0, 0]
    for section in sections:
        for line in section.lines:
            cited = [by_id[i] for i in line.fact_ids if i in by_id]
            if cited:
                out[third(cited[0].start_ms) - 1] += 1
    return out


def _earliest_per_window(facts: list[VerifiedFact]) -> list[str]:
    """The first fact said in each window, for a code-only overview."""
    seen: dict[int, VerifiedFact] = {}
    for fact in sorted(facts, key=lambda f: f.start_ms):
        seen.setdefault(fact.window_index, fact)
    return [f.item_key for f in seen.values()][: schema.MAX_KEY_POINTS]


def section_hashes(sections: list[render.RenderedSection]) -> dict[str, str]:
    """``{section_key: sha256 of the text we wrote}``: a section still equal to the
    last generation's text may be rewritten; anything else is the author's."""
    import hashlib

    return {s.section_key: hashlib.sha256(s.text.encode("utf-8")).hexdigest() for s in sections}


def _language_lines(window: Window, language: str) -> list[tuple[int, int, int, str]]:
    """Lines the ASR decoded in another language, flagged by CODE regardless of the extractor."""
    return [
        (t.number, t.start_ms, t.end_ms, "other_language")
        for t in window.turns
        if t.language and t.language != language
    ]


def _noise_lines(extracted: schema.ExtractOut, window: Window) -> list[tuple[int, int, int, str]]:
    """``[(line, start_ms, end_ms, reason)]`` for the lines the extractor
    flagged — only ones in this window, only known reasons. These are
    CANDIDATES: :func:`verify.confirm_noise` decides."""
    out: list[tuple[int, int, int, str]] = []
    for flagged in extracted.noise:
        piece = window.turn(flagged.turn)
        if piece is None or flagged.reason not in schema.NOISE_REASONS:
            continue
        out.append((piece.number, piece.start_ms, piece.end_ms, flagged.reason))
    return out


# Line support share is per language: ``support.line_support_threshold``.
# More than this share of a summary failing the gate: ask once more, strictly.
SUMMARY_FAIL_SHARE: Final = 0.3
MAX_FACTS_BUDGET: Final = 24
MIN_FACTS_BUDGET: Final = 8
MIN_BULLETS_PER_TOPIC: Final = 2


@dataclass(slots=True)
class _Gate:
    """The support gate on every line a model composes — summary
    sentences, topic bullets, the framing sentence — and its tallies.

    A line passes when it repeats no prompt example, every number in it is
    in a fact it cites, it names nobody those facts (or the roster) do not,
    and at least half its content is theirs. Counts only; never text."""

    language: str = "en"
    known: frozenset[str] = frozenset()
    counts: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(
            (
                "kept",
                "unsupported",
                "number",
                "name",
                "example",
                "attribution",
                "hedge",
                "copied",
                "no_information",
                "first_person",
                "descriptive",
                "subject",
                "unspecific",
            ),
            0,
        )
    )
    retries: int = 0
    """The rung that wrote the summary: ``model`` or ``strict``."""
    summary_rung: str | None = None
    """The output budget of a reduce call on this backend."""
    reduce_tokens: int = REDUCE_MAX_TOKENS
    salient_appended: int = 0
    salient_skipped_full: int = 0
    topics_merged: int = 0
    """Sub-points that restated their parent; openers dropped."""
    children_restated: int = 0
    third_person_fixed: int = 0
    """Why the topics pass gave nothing (None when it did)."""
    topics_failure: str | None = None
    """Verified names only: `known` less the recording's frequent capitalised words."""
    people: frozenset[str] = frozenset()
    blocks: int = 0
    block_calls: int = 0
    block_chapters: int = 0
    headings_retried: int = 0
    headings_fallback: int = 0
    merges_refused: int = 0
    quote_children: int = 0
    block_failures: Counter[str] = field(default_factory=Counter)

    @property
    def dropped(self) -> int:
        """Alias for the example count."""
        return self.counts["example"]

    def echo(self, text: str) -> bool:
        if prompts.echoes_example(text):
            self.counts["example"] += 1
            return True
        return False

    def reason(self, text: str, cited: list[VerifiedFact], *, claims: bool = False) -> str | None:
        """Why this line may not be written, or None when it may.

        ``claims`` (summary sentences): a sentence resting on an opinion or forecast
        must name its holder and keep its hedge; sentences are dropped, bullets patched."""
        plain = render.strip_inline_ids(text)[0]
        if prompts.echoes_example(plain):
            return "example"
        if not cited:
            return "unsupported"
        # A transcript copy, an uninformative remark or first-person voice is not a line.
        if any(verify.is_copied(plain, f.quote) for f in cited):
            return "copied"
        if not support.carries_information(
            plain, self.language, has_date=verify._has_date_word(plain)
        ):
            return "no_information"
        if support.first_person(plain, self.language):
            return "first_person"
        if support.descriptive(
            plain, self.language, known=self.known, has_date=verify._has_date_word(plain)
        ):
            return "descriptive"
        if not _numbers_supported(plain, cited):
            return "number"
        evidence = " ".join(f"{f.text} {f.quote}" for f in cited)
        owners = {f.owner_label for f in cited if f.owner_label}
        owners |= {f.attributed_to for f in cited if f.attributed_to}
        if support.new_names(plain, evidence, self.known | owners):
            return "name"
        if support.support_ratio(plain, evidence, self.language) < support.line_support_threshold(
            self.language
        ):
            return "unsupported"
        if claims:
            unsure = [f for f in cited if f.certainty in support.UNSURE_CERTAINTIES]
            if any(
                f.attributed_to and not support.names_actor(plain, f.attributed_to) for f in unsure
            ):
                return "attribution"
            if unsure and not support.has_marker(plain, self.language):
                return "hedge"
        return None

    def third_person(self, text: str) -> str:
        """The one mechanical rewrite: a leading "So," / "Again," / "Also," goes."""
        fixed = support.mechanical_third_person(text)
        if fixed is None:
            return text
        self.third_person_fixed += 1
        return fixed

    def ok(self, text: str, cited: list[VerifiedFact], *, claims: bool = False) -> bool:
        why = self.reason(text, cited, claims=claims)
        self.counts[why or "kept"] += 1
        return why is None


@dataclass(slots=True)
class Brief:
    """The conversation as a whole, from the context pass."""

    conversation_type: str = ""
    subject: str = ""
    themes: list[str] = field(default_factory=list)
    framing: str = ""
    key_fact_ids: list[str] = field(default_factory=list)

    def block(self, language: str) -> str:
        return prompts.brief_block(
            conversation_type=self.conversation_type,
            subject=self.subject,
            themes=self.themes,
            key_fact_ids=self.key_fact_ids,
            language=language,
        )


# ── Model steps ─────────────────────────────────────────────────────


async def _extract(
    provider: ChatLike,
    window: Window,
    language: str,
    extract_schema: dict[str, Any] | None = None,
    *,
    carried: list[tuple[str, str]] | None = None,
    max_facts: int | None = None,
    max_tokens: int = EXTRACT_MAX_TOKENS,
    system_suffix: str | None = None,
    introduction_lines: list[int] | None = None,
    contact_lines: list[int] | None = None,
    small: bool = False,
) -> schema.ExtractOut | None:
    """One window; ``None`` when the model could not answer in shape.
    ``system_suffix`` is the rule the last answer broke; ``small`` is the profile."""
    prompt = prompts.extract_prompt(
        window.render(),
        language,
        carried=carried,
        max_facts=max_facts,
        introduction_lines=introduction_lines,
        contact_lines=contact_lines,
        one_shot=small,
    )
    system = prompts.extract_system(language, noise=not small)
    if system_suffix:
        system = f"{system}\n\n{system_suffix}"
    used_schema = extract_schema or schema.EXTRACT_SCHEMA
    for attempt in range(EXTRACT_ATTEMPTS):
        try:
            answer = await provider.complete(
                prompt,
                used_schema,
                max_tokens=max_tokens,
                temperature=0.0,
                system=system,
            )
            extracted = schema.ExtractOut.model_validate_json(_json_of(answer))
            if _unquoted(extracted) and attempt + 1 < EXTRACT_ATTEMPTS:
                # Facts, and not one real quote among them: the model gave
                # line numbers where the words belong. Once more, reminded.
                prompt = f"{prompt}\n\n{prompts.quote_reminder(language)}"
                continue
            return extracted
        except ValueError:  # SCHEMA_INVALID: not JSON, or not this shape
            if attempt + 1 >= EXTRACT_ATTEMPTS:
                logger.warning(
                    "meeting_doc.window_failed",
                    extra={"window": window.index},
                    exc_info=True,
                )
                return None
            if small:
                prompt = f"{prompt}\n\n{prompts.schema_echo(language, used_schema)}"
        except Exception:  # noqa: BLE001 — one window must not stop a meeting
            if attempt + 1 >= EXTRACT_ATTEMPTS:
                logger.warning(
                    "meeting_doc.window_failed",
                    extra={"window": window.index},
                    exc_info=True,
                )
                return None
    return None


FIGURE_DETAILS_MAX_TOKENS: Final = 600
FIGURE_DETAILS_MAX_LINES: Final = 16


async def _figure_details(
    provider: ChatLike,
    window: Window,
    extracted: schema.ExtractOut,
    language: str,
    *,
    promote: bool = False,
) -> tuple[int, list[schema.Fact]]:
    """Fill bare figure fields with one call whose schema REQUIRES them; everything
    is still verified. Returns ``(figures asked about, promoted twins)``; twins are
    NOT added to the model's answer (its size is the restate budget).

    ``promote``: a fact of another kind whose quote says a number gets a figure twin;
    the original stays unless the figure verifies (:func:`_without_figure_twins`)."""
    bare = [f for f in extracted.facts if f.kind == schema.FIGURE and not (f.value and f.name)]
    twins: list[schema.Fact] = []
    if promote:
        figured = {(f.turn, f.quote) for f in extracted.facts if f.kind == schema.FIGURE}
        for fact in list(extracted.facts):
            if (
                fact.kind not in (schema.FIGURE, schema.INTRODUCTION, schema.JUDGEMENT)
                and (fact.turn, fact.quote) not in figured
                # Strip the "[4] Speaker 1 (00:23):" header: its digits were not spoken.
                and numbers.numbers_in(verify.strip_turn_header(fact.quote), language)
            ):
                twin = fact.model_copy(update={"kind": schema.FIGURE})
                twins.append(twin)
                bare.append(twin)
        # Uncovered lines with a number (a small model stops early on long windows):
        # code picks the line, the model names the quantity, code verifies it.
        covered = {
            verify.normalise_quote(verify.strip_turn_header(f.quote)) for f in extracted.facts
        }
        for turn in window.turns:
            said = verify.normalise_quote(turn.text)
            if not numbers.numbers_in(turn.text, language):
                continue
            if any(q and (q in said or said in q) for q in covered):
                continue
            twin = schema.Fact(
                kind=schema.FIGURE, text=turn.text[:240], quote=turn.text, turn=turn.number
            )
            twins.append(twin)
            bare.append(twin)
    if not bare:
        return 0, twins
    # One line per call (a small model skips most of a dozen); bounded per window.
    bare = bare[:FIGURE_DETAILS_MAX_LINES]
    for fact in bare:
        located = verify.locate_quote(fact.quote, window, fact.turn)
        line = located.text if located is not None else verify.strip_turn_header(fact.quote)
        try:
            answer = await provider.complete(
                prompts.figure_details_prompt([(line, verify.strip_turn_header(fact.quote))]),
                schema.figure_details_schema(1),
                max_tokens=FIGURE_DETAILS_MAX_TOKENS,
                temperature=0.0,
                system=prompts.figure_details_system(language),
            )
            parsed = schema.FigureDetailsOut.model_validate_json(_json_of(answer))
        except Exception:  # noqa: BLE001 — this figure is dropped by verification instead
            logger.warning("meeting_doc.figure_details_failed", exc_info=True)
            continue
        for n, detail in enumerate(parsed.figures):
            target = fact
            if n:
                # A second figure from the same line: its own fact, same words.
                target = fact.model_copy(
                    update={"name": None, "value": None, "unit": None, "qualifier": None}
                )
                twins.append(target)
            target.name = target.name or detail.name.strip() or None
            target.value = target.value or detail.value.strip() or None
            target.unit = target.unit or detail.unit.strip() or None
            target.qualifier = target.qualifier or detail.qualifier.strip() or None
    return len(bare), twins


def _contact_twins(extracted: schema.ExtractOut, language: str) -> list[schema.Fact]:
    """A fact whose quote asks the listener to act gets a `next_step` twin; verification decides."""
    have = {(f.turn, f.quote) for f in extracted.facts if f.kind == schema.NEXT_STEP}
    return [
        f.model_copy(update={"kind": schema.NEXT_STEP})
        for f in extracted.facts
        if f.kind not in (schema.NEXT_STEP, schema.FIGURE, schema.INTRODUCTION)
        and (f.turn, f.quote) not in have
        and verify.calls_to_action(f.quote, language)
    ]


async def _contact_details(
    provider: ChatLike,
    window: Window,
    facts: list[schema.Fact],
    language: str,
    hinted: list[int] | None,
) -> list[schema.Fact]:
    """A call-to-action line no fact states as a `next_step` is stated once by a
    call whose schema requires the sentence; verification checks it like any fact."""
    if not hinted:
        return []
    stated = {f.turn for f in facts if f.kind == schema.NEXT_STEP}
    turns = [t for t in window.turns if t.number in hinted and t.number not in stated]
    if not turns:
        return []
    try:
        answer = await provider.complete(
            prompts.lines_prompt([t.text for t in turns]),
            schema.contact_details_schema(len(turns)),
            max_tokens=FIGURE_DETAILS_MAX_TOKENS,
            temperature=0.0,
            system=prompts.contact_details_system(language),
        )
        parsed = schema.ContactDetailsOut.model_validate_json(_json_of(answer))
    except Exception:  # noqa: BLE001 — no Contact line is better than a guess
        logger.warning("meeting_doc.contact_details_failed", exc_info=True)
        return []
    out: list[schema.Fact] = []
    for detail in parsed.steps:
        if 1 <= detail.index <= len(turns) and detail.text.strip():
            turn = turns[detail.index - 1]
            out.append(
                schema.Fact(
                    kind=schema.NEXT_STEP,
                    text=detail.text.strip(),
                    quote=turn.text,
                    turn=turn.number,
                )
            )
    return out


def _without_figure_twins(facts: list[VerifiedFact]) -> list[VerifiedFact]:
    """A promoted figure or call to action that verified replaces the fact
    it was made from (same line, same quote): one statement, written once."""
    typed = {(f.line, f.quote) for f in facts if f.figure is not None or f.kind == schema.NEXT_STEP}
    return [
        f
        for f in facts
        if f.figure is not None or f.kind == schema.NEXT_STEP or (f.line, f.quote) not in typed
    ]


async def _person_details(
    provider: ChatLike, window: Window, extracted: schema.ExtractOut, language: str
) -> None:
    """The same one follow-up for introductions without a name."""
    bare = [f for f in extracted.facts if f.kind == schema.INTRODUCTION and not f.name]
    if not bare:
        return
    lines = []
    for fact in bare:
        turn = verify.locate_quote(fact.quote, window, fact.turn)
        if turn is None:
            lines.append(verify.strip_turn_header(fact.quote))
            continue
        # The sentence after an introduction often says the rest; verification reads it too.
        following = verify._next_line_same_speaker(window, turn)
        lines.append(f"{turn.text} {following}".strip())
    try:
        answer = await provider.complete(
            prompts.lines_prompt(lines),
            schema.person_details_schema(len(lines)),
            max_tokens=FIGURE_DETAILS_MAX_TOKENS,
            temperature=0.0,
            system=prompts.person_details_system(language),
        )
        parsed = schema.PersonDetailsOut.model_validate_json(_json_of(answer))
    except Exception:  # noqa: BLE001 — verification drops them instead
        logger.warning("meeting_doc.person_details_failed", exc_info=True)
        return
    for detail in parsed.people:
        if 1 <= detail.index <= len(bare):
            fact = bare[detail.index - 1]
            fact.name = detail.name.strip() or None
            fact.role = fact.role or detail.role.strip() or None
            fact.organisation = fact.organisation or detail.organisation.strip() or None
            fact.qualifier = fact.qualifier or detail.qualifier.strip() or None


async def _context(
    provider: ChatLike, facts: list[VerifiedFact], language: str, *, gate: _Gate | None = None
) -> Brief | None:
    """Read the facts as one conversation. Never sees the transcript.

    The framing sentence is the one line of the document that is written
    about the meeting rather than from a single fact, so it passes the
    same gate a summary sentence does, against the key facts it names
    (all facts when it names none).
    """
    gate = gate or _Gate(language=language)
    if len(facts) < 3:
        return None
    block = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    try:
        answer = await provider.complete(
            block,
            schema.REDUCE_CONTEXT_SCHEMA,
            max_tokens=gate.reduce_tokens,
            temperature=0.0,
            system=prompts.context_system(language),
        )
        parsed = schema.ContextOut.model_validate_json(_json_of(answer))
    except Exception:  # noqa: BLE001
        logger.warning("meeting_doc.context_failed", exc_info=True)
        return None
    by_id = {f.item_key: f for f in facts}
    key_fact_ids = [i for i in dict.fromkeys(parsed.key_fact_ids) if i in by_id][
        : schema.MAX_KEY_POINTS
    ]
    framing = parsed.framing.strip()
    if framing and not gate.ok(framing, [by_id[i] for i in key_fact_ids] or facts):
        framing = ""
    return Brief(
        conversation_type=parsed.conversation_type.strip(),
        subject=parsed.subject.strip(),
        themes=[t.strip() for t in parsed.themes if t.strip()][: schema.MAX_THEMES],
        framing=framing,
        key_fact_ids=key_fact_ids,
    )


def _with_brief(block: str, brief: Brief | None, language: str) -> str:
    context = brief.block(language) if brief else ""
    return f"{context}\n\n{block}" if context else block


def _children(
    bullet: schema.TopicBullet,
    parent: str,
    parent_ids: list[str],
    by_id: dict[str, VerifiedFact],
    gate: _Gate,
) -> list[tuple[str, list[str]]]:
    """A bullet's sub-points that cite a fact, pass the gate and do not restate the parent."""
    out: list[tuple[str, list[str]]] = []
    parent_words = support.merge_tokens(parent)
    for child in bullet.children[: schema.MAX_CHILDREN]:
        if child.quote_of:
            continue  # a quote sub-point is written by code
        text = gate.third_person(child.text.strip())
        ids = list(dict.fromkeys(i for i in child.fact_ids if i in by_id))
        if not text or not ids or not gate.ok(text, [by_id[i] for i in ids]):
            continue
        if set(ids) <= set(parent_ids) and (
            verify._jaccard(support.merge_tokens(text), parent_words) >= CHILD_RESTATES_JACCARD
        ):
            gate.children_restated += 1
            continue
        out.append((text, ids))
    return out


# A block's call is retried once; a heading once more.
BLOCK_ATTEMPTS: Final = 2
BLOCK_CONCURRENCY: Final = 4


def _heading_faults(heading: str, facts: Sequence[VerifiedFact], gate: _Gate) -> list[str]:
    """Why a model heading cannot head its block: form rules, a generic label, or an unsaid name."""
    faults = [f for f in doclint.heading_faults(heading) if f not in ("punctuation", "question")]
    if heading.casefold().rstrip(":.!?") in doclint.GENERIC_HEADINGS:
        faults.append("generic")
    evidence = " ".join(f"{f.text} {f.quote}" for f in facts)
    if doclint.unsupported_names(heading, evidence, gate.language, gate.people):
        faults.append("name")
    if gate.echo(heading):
        faults.append("example")
    return faults


def _speaker_name(fact: VerifiedFact, table: roles_table.RolesTable) -> str | None:
    speaker = table.speakers.get(fact.speaker_label or "")
    return (speaker.name if speaker else None) or support.real_name(fact.speaker_name)


async def _reduce_block(
    provider: ChatLike,
    block: compose.Block,
    language: str,
    budget: compose.VolumeBudget,
    *,
    brief: Brief | None,
    gate: _Gate,
    table: roles_table.RolesTable,
    small: bool = False,
) -> tuple[str, list[Bullet], list[str]] | None:
    """One block: a heading and gated bullets, kept to the budget by specificity and
    written in time order. Two failed calls or fewer than two bullets: the block's chapter.

    ``small``: heading and bullets are separate calls over at most fifteen facts, no sub-points."""
    facts = list(block.facts)
    by_id = {f.item_key: f for f in facts}
    if small:
        heading, bullets, parsed_any = await _block_small(
            provider, facts, by_id, language, budget, brief=brief, gate=gate, table=table
        )
    else:
        heading, bullets, parsed_any = await _block_capable(
            provider, facts, by_id, language, budget, brief=brief, gate=gate, table=table
        )
    if len(bullets) < MIN_BULLETS_PER_TOPIC:
        if parsed_any and not bullets:
            gate.block_failures["all_bullets_unsupported"] += 1
        chapter = _block_chapter(facts, language, gate, budget)
        if chapter is None:
            return None
        gate.block_chapters += 1
        return chapter
    if not heading:
        heading = compose.fallback_heading(facts, language, gate.people)
        gate.headings_fallback += 1

    # Within the budget, the most specific first; then in time order.
    def first_start(bullet: Bullet) -> int:
        return min((by_id[i].start_ms for i in bullet[1] if i in by_id), default=0)

    kept = sorted(
        bullets,
        key=lambda b: -support.specificity(b[0], language, known=gate.known),
    )[: budget.bullets_per_block]
    kept.sort(key=first_start)
    kept = introduce_first(kept, by_id)
    cited = [i for _t, ids, _c in kept for i in ids]
    return heading, kept, list(dict.fromkeys([*cited, *by_id]))


def introduce_first(bullets: list[Bullet], by_id: dict[str, VerifiedFact]) -> list[Bullet]:
    """A bullet introducing a person comes before any bullet naming them; else time order."""
    out = list(bullets)
    for bullet in bullets:
        people = [
            by_id[i].person.name
            for i in bullet[1]
            if i in by_id and by_id[i].person is not None and by_id[i].person.name
        ]
        if not people:
            continue
        here = out.index(bullet)
        last_words = [p.split()[-1].casefold() for p in people]
        earlier = [
            n
            for n, other in enumerate(out[:here])
            if any(
                re.search(rf"(?<!\w){re.escape(w)}(?!\w)", other[0].casefold()) for w in last_words
            )
        ]
        if earlier:
            out.insert(earlier[0], out.pop(here))
    return out


async def _block_capable(
    provider: ChatLike,
    facts: list[VerifiedFact],
    by_id: dict[str, VerifiedFact],
    language: str,
    budget: compose.VolumeBudget,
    *,
    brief: Brief | None,
    gate: _Gate,
    table: roles_table.RolesTable,
) -> tuple[str, list[Bullet], bool]:
    """Heading and bullets in one call, retried once when the heading is
    refused. ``(heading, bullets, whether any answer parsed)``."""
    listing = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    system = prompts.block_system(language, budget.bullets_per_block)
    heading = ""
    bullets: list[Bullet] = []
    parsed_any = False
    for attempt in range(BLOCK_ATTEMPTS):
        gate.block_calls += 1
        try:
            answer = await provider.complete(
                _with_brief(listing, brief, language),
                schema.BLOCK_SCHEMA,
                max_tokens=gate.reduce_tokens,
                temperature=0.0,
                system=system,
            )
            parsed = schema.BlockOut.model_validate_json(_json_of(answer))
        except ValueError:
            gate.block_failures["schema_invalid"] += 1
            logger.warning("meeting_doc.block_failed", exc_info=True)
            continue
        except Exception:  # noqa: BLE001 — one block must not cost the note
            gate.block_failures["provider_error"] += 1
            logger.warning("meeting_doc.block_failed", exc_info=True)
            continue
        parsed_any = True
        written = _block_bullets(parsed, by_id, language, gate, table)
        if len(written) >= len(bullets):
            bullets = written
        candidate = parsed.heading.strip().rstrip(":.!?").strip()
        if candidate and not _heading_faults(candidate, facts, gate):
            heading = candidate
        if heading and len(bullets) >= MIN_BULLETS_PER_TOPIC:
            break
        if attempt == 0 and not heading:
            gate.headings_retried += 1
            system = f"{system}\n\n{prompts.heading_retry(language)}"
    return heading, bullets, parsed_any


async def _small_call(
    provider: ChatLike,
    prompt: str,
    json_schema: dict[str, Any],
    model: type[Any],
    system: str,
    language: str,
    gate: _Gate,
    *,
    max_tokens: int = REDUCE_MAX_TOKENS,
) -> Any | None:
    """One reduce call under the profile: a malformed answer is asked once
    more with the schema echoed into the prompt; a provider error is not."""
    for _attempt in range(BLOCK_ATTEMPTS):
        gate.block_calls += 1
        try:
            answer = await provider.complete(
                prompt, json_schema, max_tokens=max_tokens, temperature=0.0, system=system
            )
            return model.model_validate_json(_json_of(answer))
        except ValueError:
            gate.block_failures["schema_invalid"] += 1
            logger.warning("meeting_doc.block_failed", exc_info=True)
            prompt = f"{prompt}\n\n{prompts.schema_echo(language, json_schema)}"
        except Exception:  # noqa: BLE001 — one block must not cost the note
            gate.block_failures["provider_error"] += 1
            logger.warning("meeting_doc.block_failed", exc_info=True)
            return None
    return None


async def _block_small(
    provider: ChatLike,
    facts: list[VerifiedFact],
    by_id: dict[str, VerifiedFact],
    language: str,
    budget: compose.VolumeBudget,
    *,
    brief: Brief | None,
    gate: _Gate,
    table: roles_table.RolesTable,
) -> tuple[str, list[Bullet], bool]:
    """The profile's reduce: bullets over at most ``SMALL_MODEL_REDUCE_FACTS``
    facts per call, no sub-points; then the heading, alone, over the block's
    first facts, retried once when refused."""
    chunks = [
        facts[k : k + SMALL_MODEL_REDUCE_FACTS]
        for k in range(0, len(facts), SMALL_MODEL_REDUCE_FACTS)
    ]
    per_call = max(MIN_BULLETS_PER_TOPIC, -(-budget.bullets_per_block // max(1, len(chunks))))
    bullets: list[Bullet] = []
    parsed_any = False
    for chunk in chunks:
        listing = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in chunk])
        parsed = await _small_call(
            provider,
            _with_brief(listing, brief, language),
            schema.BLOCK_BULLETS_SCHEMA,
            schema.BlockOut,
            prompts.block_bullets_system(language, per_call),
            language,
            gate,
        )
        if parsed is None:
            continue
        parsed_any = True
        bullets.extend(_block_bullets(parsed, by_id, language, gate, table))
    heading = ""
    listing = prompts.facts_block(
        [(f.item_key, f.kind, f.text, f.start_ms) for f in chunks[0]] if chunks else []
    )
    system = prompts.block_heading_system(language)
    for attempt in range(BLOCK_ATTEMPTS):
        parsed = await _small_call(
            provider,
            _with_brief(listing, brief, language),
            schema.HEADING_SCHEMA,
            schema.HeadingOut,
            system,
            language,
            gate,
            max_tokens=HEADING_MAX_TOKENS,
        )
        if parsed is None:
            break
        candidate = parsed.heading.strip().rstrip(":.!?").strip()
        if candidate and not _heading_faults(candidate, facts, gate):
            heading = candidate
            break
        if attempt == 0:
            gate.headings_retried += 1
            system = f"{system}\n\n{prompts.heading_retry(language)}"
    return heading, bullets, parsed_any


def _block_bullets(
    parsed: schema.BlockOut,
    by_id: dict[str, VerifiedFact],
    language: str,
    gate: _Gate,
    table: roles_table.RolesTable,
) -> list[Bullet]:
    out: list[Bullet] = []
    for bullet in parsed.bullets[: schema.MAX_BLOCK_BULLETS]:
        text = gate.third_person(bullet.text.strip())
        ids = list(dict.fromkeys(i for i in bullet.fact_ids if i in by_id))
        if not text:
            continue
        why = gate.reason(text, [by_id[i] for i in ids])
        if why == "name":
            # A name another fact of this block says: that fact is cited too
            # (code finds it; the bullet must still pass on its own facts).
            ids = _cite_names(text, ids, by_id, gate)
            why = gate.reason(text, [by_id[i] for i in ids])
        gate.counts[why or "kept"] += 1
        if why is not None:
            continue
        if support.pronoun_initial(text, language):
            gate.counts["subject"] += 1
            continue
        if (
            support.specificity(
                text, language, known=gate.known, has_date=verify._has_date_word(text)
            )
            == 0
        ):
            gate.counts["unspecific"] += 1
            continue
        children: list[Child] = list(_children(bullet, text, ids, by_id, gate))
        for child in bullet.children:
            if not child.quote_of or child.quote_of not in by_id:
                continue
            fact = by_id[child.quote_of]
            quoted = compose.quote_child(fact, _speaker_name(fact, table), language)
            if quoted and len(children) < schema.MAX_CHILDREN:
                children.append((quoted, [fact.item_key], QUOTE))
                gate.quote_children += 1
        out.append((text, ids, children))
    return out


def _cite_names(
    text: str, ids: list[str], by_id: dict[str, VerifiedFact], gate: _Gate
) -> list[str]:
    """The block's facts that say a name the bullet uses and its cited
    facts do not, added to its citations — never more than two."""
    evidence = " ".join(f"{by_id[i].text} {by_id[i].quote}" for i in ids)
    missing = support.new_names(text, evidence, gate.known)
    added: list[str] = []
    for name in missing:
        stem = name.casefold()[:5]
        source = next(
            (
                f.item_key
                for f in by_id.values()
                if f.item_key not in ids and stem in f"{f.text} {f.quote}".casefold()
            ),
            None,
        )
        if source and source not in added:
            added.append(source)
    return [*ids, *added[:2]]


def _block_chapter(
    facts: list[VerifiedFact], language: str, gate: _Gate, budget: compose.VolumeBudget
) -> tuple[str, list[Bullet], list[str]] | None:
    """One block's chapter: its statements by time (the specific ones when any), under its name."""
    usable = [
        f
        for f in facts
        if not f.evidence_only
        and f.figure is None
        and f.person is None
        and PARAPHRASE_UNSUPPORTED not in f.flags
    ]
    specific = [f for f in usable if compose.specificity(f, language, gate.people) > 0]
    shown = (specific or usable)[: budget.bullets_per_block]
    if len(shown) < MIN_BULLETS_PER_TOPIC:
        return None
    title = compose.fallback_heading(facts, language, gate.people)
    return (
        title,
        [(f.text, [f.item_key], []) for f in sorted(shown, key=lambda f: f.start_ms)],
        [f.item_key for f in facts],
    )


async def _reduce_blocks(
    provider: ChatLike,
    parts: list[compose.Block],
    language: str,
    budget: compose.VolumeBudget,
    *,
    brief: Brief | None,
    gate: _Gate,
    table: roles_table.RolesTable,
    minutes: float,
    small: bool = False,
) -> Topics | None:
    """Every block in parallel (a few at a time), then one tiny call over
    the headings for merges, applied only while the section band holds."""
    semaphore = asyncio.Semaphore(BLOCK_CONCURRENCY)

    async def one(block: compose.Block) -> tuple[str, list[Bullet], list[str]] | None:
        async with semaphore:
            return await _reduce_block(
                provider,
                block,
                language,
                budget,
                brief=brief,
                gate=gate,
                table=table,
                small=small,
            )

    results = await asyncio.gather(*(one(b) for b in parts))
    topics: Topics = [r for r in results if r is not None]
    gate.blocks = len(parts)
    if len(topics) < len(parts) and not gate.block_failures:
        gate.block_failures["too_few_topics"] += 1
    if gate.block_chapters == len(topics) and gate.block_failures:
        gate.topics_failure = max(gate.block_failures, key=lambda k: gate.block_failures[k])
    if not topics:
        gate.topics_failure = gate.topics_failure or "all_bullets_unsupported"
        return None
    return await _merge_headings(provider, topics, language, gate, minutes)


async def _merge_headings(
    provider: ChatLike, topics: Topics, language: str, gate: _Gate, minutes: float
) -> Topics:
    if len(topics) < 2:
        return topics
    floor = (
        max(doclint.SECTIONS_MIN, doclint.target_sections(minutes) - doclint.SECTIONS_TOLERANCE)
        if minutes >= doclint.SECTIONS_FROM_MINUTES
        else 1
    )
    listing = "\n".join(f"{n}. {title}" for n, (title, _b, _i) in enumerate(topics))
    try:
        answer = await provider.complete(
            f"{prompts.DATA_OPEN}\n{listing}\n{prompts.DATA_CLOSE}",
            schema.MERGE_SCHEMA,
            max_tokens=200,
            temperature=0.0,
            system=prompts.merge_system(language),
        )
        parsed = schema.MergeOut.model_validate_json(_json_of(answer))
    except Exception:  # noqa: BLE001 — merges are an improvement, never a need
        logger.warning("meeting_doc.merge_failed", exc_info=True)
        return topics
    pairs = sorted(
        {(i, j) for i, j in (m[:2] for m in parsed.merges if len(m) >= 2) if j == i + 1},
        reverse=True,
    )
    out = list(topics)
    for i, j in pairs:
        if j >= len(out) or len(out) - 1 < floor:
            gate.merges_refused += 1
            continue
        title, bullets, ids = out[i]
        _t2, more, more_ids = out[j]
        out[i : j + 1] = [(title, [*bullets, *more], list(dict.fromkeys([*ids, *more_ids])))]
        gate.topics_merged += 1
    return out


def _narrator_attribution(
    facts: list[VerifiedFact], table: roles_table.RolesTable, recording_type: str | None
) -> tuple[list[VerifiedFact], int]:
    """In a broadcast the dominant voice reports: its statement about somebody is
    that person's, unless said in the first person ("ich finde", "I think")."""
    if not any(s.role in (roles_table.NARRATOR, roles_table.HOST) for s in table.speakers.values()):
        return facts, 0
    out, changed = [], 0
    for fact in facts:
        role = table.role_of(fact.speaker_label)
        if role not in (roles_table.NARRATOR, roles_table.HOST) or roles_table.first_person(
            fact.quote
        ):
            out.append(fact)
            continue
        own = _speaker_name(fact, table)
        holder = fact.attributed_to
        if holder and own and holder.casefold() == own.casefold():
            holder = None
        if not holder and fact.certainty in support.UNSURE_CERTAINTIES:
            holder = fact.subject
        if holder != fact.attributed_to:
            fact = dataclasses.replace(fact, attributed_to=holder)
            changed += 1
        out.append(fact)
    return out, changed


def _gated_phrase(phrase: str, facts: list[VerifiedFact], gate: _Gate) -> str:
    """A subject or theme the context pass named, kept when the facts carry
    it (support ≥ the line bar, no new name) — else nothing."""
    phrase = " ".join(phrase.split())
    if not phrase:
        return ""
    evidence = " ".join(f"{f.text} {f.quote}" for f in facts)
    if support.new_names(phrase, evidence, gate.known):
        return ""
    if support.support_ratio(phrase, evidence, gate.language) < support.line_support_threshold(
        gate.language
    ):
        return ""
    return phrase


_DEFAULT_NAME = re.compile(r"(?i)^(?:speaker[ _]?\d+|unknown(?: speaker)?|sprecher(?:in)? \d+)$")


def _span(ids: list[str], by_id: dict[str, VerifiedFact]) -> tuple[int, int]:
    times = [by_id[i].start_ms for i in ids if i in by_id]
    return (min(times), max(times)) if times else (0, 0)


def _distance(
    topic: tuple[str, list[Bullet], list[str]],
    fact: VerifiedFact,
    by_id: dict[str, VerifiedFact],
) -> int:
    start, end = _span(topic[2], by_id)
    return abs((start + end) // 2 - fact.start_ms)


def _append_salient(
    topics: Topics,
    facts: list[VerifiedFact],
    gate: _Gate,
) -> None:
    """A key point with a number, a date or a person is kept even when no bullet
    wrote about it: it joins the topic nearest in time."""
    if not topics:
        return
    by_id = {f.item_key: f for f in facts}
    written = {i for _t, bullets, _ids in topics for bullet in bullets for i in bullet[1]}
    for fact in facts:
        if fact.kind != schema.KEY_POINT or not fact.salient or fact.item_key in written:
            continue
        # The fact's own text is the line here: evidence stays evidence.
        if fact.evidence_only:
            continue

        # Nearest topic in time with room under six points; a full topic keeps the
        # fact as a fact (it never moves to another part of the recording).
        index = min(range(len(topics)), key=lambda k, f=fact: _distance(topics[k], f, by_id))
        title, bullets, ids = topics[index]
        if len(bullets) >= compose.BULLETS[1]:
            gate.salient_skipped_full += 1
            continue

        def first_said(bullet: Bullet) -> int:
            return min((by_id[i].start_ms for i in bullet[1] if i in by_id), default=0)

        new: Bullet = (fact.text, [fact.item_key], [])
        placed = sorted([*bullets, new], key=first_said)
        topics[index] = (title, placed, [*ids, fact.item_key])
        written.add(fact.item_key)
        gate.salient_appended += 1


async def _summary(
    provider: ChatLike,
    facts: list[VerifiedFact],
    language: str,
    *,
    brief: Brief | None = None,
    gate: _Gate | None = None,
    headings: list[str] | None = None,
    skeleton_ids: list[str] | None = None,
    small: bool = False,
) -> list[tuple[str, list[str]]] | None:
    """``[(sentence, the fact ids it rests on)]``, or None.

    Rung 1 is told the block headings; rung 2 names the fact per sentence
    (``skeleton_ids``). Every sentence passes the gate or is dropped; above
    ``SUMMARY_FAIL_SHARE`` failures the model is asked once more strictly, then
    the overview is written by code. ``small`` runs the rungs in the other order."""
    gate = gate or _Gate(language=language)
    block = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    by_id = {f.item_key: f for f in facts}
    base = prompts.summary_system(language)
    if headings:
        base = f"{base}\n\n{prompts.summary_blocks(headings, language)}"
    # Rung 2's skeleton: the facts to use, in time order, one sentence per
    # one or two of them.
    if skeleton_ids:
        groups = [[i] for i in skeleton_ids][: schema.MAX_SUMMARY_SENTENCES + 1]
    else:
        ordered = [f.item_key for f in sorted(facts, key=lambda f: f.start_ms)][:12]
        groups = [ordered[k : k + 2] for k in range(0, len(ordered), 2)][:6]
    strict = f"{base}\n\n{prompts.strict_suffix(language)}\n{prompts.skeleton(groups, language)}"
    rungs = ("strict", "model") if small else ("model", "strict")
    for attempt, rung in enumerate(rungs):
        system = strict if rung == "strict" else base
        try:
            answer = await provider.complete(
                _with_brief(block, brief, language),
                schema.REDUCE_SUMMARY_SCHEMA,
                max_tokens=gate.reduce_tokens,
                temperature=0.0,
                system=system,
            )
            parsed = schema.ReduceOut.model_validate_json(_json_of(answer))
        except Exception:  # noqa: BLE001
            logger.warning("meeting_doc.summary_failed", exc_info=True)
            return None

        out: list[tuple[str, list[str]]] = []
        answered = 0
        for line in parsed.summary:
            sentence = gate.third_person(line.sentence.strip())
            if not sentence:
                continue
            answered += 1
            cited = [by_id[i] for i in dict.fromkeys(line.fact_ids) if i in by_id]
            # A cited id is not support (a prompt example once cited a real fact).
            if gate.ok(sentence, cited, claims=True):
                out.append((sentence, [f.item_key for f in cited]))
        failed = answered - len(out)
        if (answered and failed / answered > SUMMARY_FAIL_SHARE) or not answered:
            if attempt == 0:
                gate.retries += 1
                continue
            return None
        gate.summary_rung = rung
        return out[: schema.MAX_SUMMARY_SENTENCES] or None
    return None


def _unquoted(extracted: schema.ExtractOut) -> bool:
    """Every fact's quote is too short to be words someone said."""
    return bool(extracted.facts) and all(
        len(verify.strip_turn_header(f.quote).split()) < schema.MIN_QUOTE_WORDS
        for f in extracted.facts
    )


def _numbers_supported(sentence: str, cited: list[VerifiedFact]) -> bool:
    """Every number in a summary sentence must be in a fact it cites."""
    said = " ".join(f"{f.text} {f.quote}" for f in cited)
    known = {n.replace(",", "").replace(".", "") for n in verify._NUMBER.findall(said)}
    for match in verify._NUMBER.findall(sentence):
        plain = match.replace(",", "").replace(".", "")
        if plain and plain not in known:
            return False
    return True


def _json_of(answer: Any) -> str:
    """The provider's text, whatever wrapper it came in."""
    text = getattr(answer, "text", answer)
    return text if isinstance(text, str) else str(text)


__all__ = ["DocumentResult", "run", "section_hashes", "roles"]
