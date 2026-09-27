"""Transcript in, document out.

    windows → extract (one model call each) → verify → merge
            → context (one model call) → reduce (two, in parallel) → render

The context pass reads the verified facts once and says what the
conversation was — its type, subject, themes, the facts a reader must
know first — before anything is written. Topics and summary are then
written about that conversation rather than about a pile of facts, and
the overview opens with a sentence a reader who was not there can use.

The shape is the sprint's architecture decision, and the reason for it is
in the middle of that line: **verify**. Every claim the model makes has to
survive a check against the words that were actually spoken before it can
reach a note. A window whose call fails is reported, not silently
dropped; a meeting where nothing verifies produces an empty document
rather than filler.

`run()` is used by the worker and, unchanged, by the eval harness — the
harness measures the production code or it measures nothing.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final, Protocol

from . import (
    entities,
    lint,
    numbers,
    overview,
    prompts,
    render,
    roles,
    schema,
    support,
    types,
    verify,
    windows,
)
from . import merge as merge_rules
from .verify import VerifiedFact
from .windows import Window

logger = logging.getLogger(__name__)

# One retry on a malformed answer; a second failure means this window is
# reported as failed rather than retried forever.
EXTRACT_ATTEMPTS = 2
# Output budgets are sized from the schema's own caps, not from a typical
# answer: a window may legally carry MAX_FACTS_PER_WINDOW facts of up to
# MAX_FACT_CHARS plus a 400-character quote each (~3 000 tokens), and a
# topics answer MAX_TOPICS × MAX_BULLETS_PER_TOPIC bullets. With 900 / 700
# a small model that used its allowance was cut off mid-JSON, the
# provider reported `context_exceeded`, and every window "failed" —
# the note stayed a bare transcript. Unused budget costs nothing.
EXTRACT_MAX_TOKENS = 3000
REDUCE_MAX_TOKENS = 2500
# F2, decision 2 — a window whose verified facts copy the transcript into
# `text` is asked once more, told which rule it broke. Tuned (as the work
# order says to when recall drops): the 40 % share it named left windows
# of three copies in eight unasked, and each copy is a fact the note loses;
# the 2026-09-26 eval on Gemma 3 4B lost 2 of 3 key facts on m04 that way.
# Any copy now asks — still at most one extra call per window.
RESTATE_COPY_SHARE: Final = 0.0
RESTATE_MIN_FACTS: Final = 1
# A sub-point that cites only its parent's facts and says mostly the same
# words is the parent again, not an elaboration.
CHILD_RESTATES_JACCARD: Final = 0.6

# A topic bullet with its sub-points: ``(text, fact ids, [(text, ids)])``.
Bullet = tuple[str, list[str], list[tuple[str, list[str]]]]
Topics = list[tuple[str, list[Bullet], list[str]]]


class ChatLike(Protocol):
    backend: str
    model_id: str

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> Any: ...


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
    stats: dict[str, Any] = field(default_factory=dict)
    backend: str | None = None
    model_id: str | None = None
    """Sprint 36 — carried items the recording says are done, and
    judgement values offered for a person to accept. Neither is a line
    of the document."""
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
    """Q2 — the lines left out, CONFIRMED by code (``verify.confirm_noise``)
    and within the cap. ``noise`` and ``noise_ranges`` are derived from it."""
    excluded: list[verify.Exclusion] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return self.windows_failed > 0

    @property
    def lines(self) -> list[tuple[str, render.Line]]:
        """``[(section_key, line)]`` — every written line of the document,
        in the order the sections are written."""
        return [(s.section_key, line) for s in self.sections for line in s.lines]


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
) -> DocumentResult:
    """Build a document from an ASR result.

    ``family`` (Sprint 36) decides which fact kinds this call may return
    and where each lands; ``carried`` is ``[(item_key, text)]`` for the
    items still open from the previous meeting, which the extractor may
    mark done — by their NUMBER in this list, never by free text.
    """
    family = family or types.FALLBACK
    kinds = types.fact_kinds(family)
    # `user_point` is the author's own; the engine never proposes one.
    offered = tuple(k for k in kinds if k != "user_point")
    if family.judgement_fields:
        offered = (*offered, schema.JUDGEMENT)
    carried = carried or []
    carried_keys = tuple(key for key, _ in carried)
    turns = windows.turns_from_result(result)
    # F3 amendment: adverts and trailers are cut before windowing (the
    # extractor never sees them) and one-word turns inside somebody's
    # sentence are merged into it. When that changed anything, the windows
    # the worker built for classification are rebuilt from the result.
    prepared = windows.prepare_turns(turns)
    if prepared.adverts or prepared.microturns_merged:
        turns = prepared.turns
        built = None
    # The worker builds the windows once, to classify the recording from
    # the first of them before extraction (Q3), and hands them in.
    built = built if built is not None else windows.build_windows(turns)
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

    # F3 — lines with an introduction in the first windows, pointed out to
    # the extractor when this family writes introductions.
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
        budget = fact_budget(window)
        window_schema = schema.extract_schema(
            offered,
            judgement_fields=family.judgement_fields,
            carried_items=len(carried),
            max_facts=budget,
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
    out.noise = sorted({(e.start_ms, e.reason) for e in excluded})
    out.noise_ranges = sorted({(e.start_ms, e.end_ms, e.reason) for e in excluded})

    # F3 amendment §2.8 — what the recording itself spells three times or more.
    rec_names = support.recording_names([t.text for t in turns])

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
    # F3 amendment §2.4 — a table is for a demonstration or a lecture.
    tables = recording_type is None or recording_type in TABLE_TYPES
    for window, extracted in extracted_windows:
        if extracted is None:
            out.windows_failed += 1
            out.failed_ranges.append([window.start_ms, window.end_ms])
            continue
        out.windows_done += 1
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
            # A verified figure replaces the key point it was promoted from
            # only where figures are written as a table; elsewhere the
            # statement stays and the figure is stored as a row.
            kept = _without_figure_twins(kept)
        # A figure or introduction is written from its payload: its text
        # being a copy is no reason to ask again, nor to replace it.
        copies = sum(1 for f in kept if f.copied and f.figure is None and f.person is None)
        if copies and len(kept) >= RESTATE_MIN_FACTS and copies / len(kept) > RESTATE_COPY_SHARE:
            # F2, decision 2: once per window, told the rule it broke, with
            # no more facts than it gave the first time.
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
                ),
                carried=carried,
                max_facts=again_budget,
                max_tokens=extract_tokens(again_budget),
                system_suffix=prompts.restate_suffix(language),
            )
            second = check(again.facts, window, verify.VerifyStats()) if again else []
            kept, replaced = restated(kept, second)
            restate["improved" if replaced else "unchanged"] += 1
        verified.extend(kept)

    facts = merge_rules.merge_facts(verified)
    # F3 amendment — who an introduced person is to this recording.
    facts = [
        dataclasses.replace(f, person=dataclasses.replace(f.person, standing=standing_of(f, turns)))
        if f.person is not None
        else f
        for f in facts
    ]
    out.facts = facts
    # Completions and judgements are not lines of the document: one
    # ticks a carried item off, the other is offered under a field.
    document_facts = [f for f in facts if f.kind not in (schema.COMPLETION, schema.JUDGEMENT)]
    out.completions = [f for f in facts if f.kind == schema.COMPLETION]
    out.judgements = [f for f in facts if f.kind == schema.JUDGEMENT]

    topics: Topics | None = None
    summary: list[tuple[str, list[str]]] | None = None
    brief: Brief | None = None
    entity_stats: dict[str, int] = {"seen": 0, "model_failed": 0, "marked": 0, "model": 0}
    # F3 — a person introduced in the recording is somebody a line may name.
    introduced = {f.person.name for f in document_facts if f.person is not None}
    gate = _Gate(
        language=language,
        known=frozenset(
            {t.speaker_name for t in turns if t.speaker_name}
            | set(name_candidates)
            | introduced
            | rec_names
        ),
    )

    if document_facts:
        # Understand the conversation first; then write topics and the
        # summary about it, side by side.
        brief = await _context(provider, document_facts, language, gate=gate)
        # Q4, tier (b): names nobody in the workspace knows, asked of the
        # model once — before anything is written from the facts.
        people = gate.known | {g.term for g in glossary if getattr(g, "kind", "") == "person"}
        renamed = await _model_names(
            provider,
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
        long_run = len(document_facts) > TWO_STAGE_MIN_FACTS
        topics, summary = await asyncio.gather(
            _topics_by_block(provider, document_facts, language, gate=gate)
            if long_run
            else _topics(provider, document_facts, language, brief=brief, gate=gate),
            _summary(provider, document_facts, language, brief=brief, gate=gate),
        )
    # §2.6 — a long recording whose topics failed is chaptered by time, from
    # data the engine has; a model failure no longer collapses it.
    duration = (turns[-1].end_ms - turns[0].start_ms) if turns else 0
    topics_fallback: str | None = None
    if document_facts and topics is None and duration > overview.CHAPTERS_AFTER_MS:
        chaptered = overview.chapters(document_facts, language=language, known=gate.known)
        if chaptered:
            topics = chaptered
            topics_fallback = "chapters"
    # §2.9, ladder rung 3 — the summary is prose, always: composed from the
    # most specific facts when both model rungs failed.
    ladder = "model" if summary else None
    if summary and gate.retries:
        ladder = "strict"
    if document_facts and not summary:
        summary = (
            overview.composed_sentences(
                document_facts,
                language=language,
                known=gate.known,
                key_ids=brief.key_fact_ids if brief else None,
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
    # §2.9, paragraph 1 — what this recording is, composed by code from
    # verified values; the model's framing replaces only its first clause.
    opening = ""
    if document_facts:
        opening = overview.first_paragraph(
            language=language,
            recording_type=recording_type,
            subject=_gated_phrase(brief.subject if brief else "", document_facts, gate),
            framing=brief.framing if brief else "",
            speakers=_speakers(turns, document_facts, language),
            guests=_guests(document_facts),
            themes=[
                t for t in (brief.themes if brief else []) if _gated_phrase(t, document_facts, gate)
            ],
        )

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
    # D1 — the document lint: what is wrong with the note's form, by
    # taxonomy code. Counts only; it rewrites nothing.
    linted = lint.lint(
        lint.from_rendered(out.sections),
        language=language,
        duration_ms=duration,
        fact_start_ms={f.item_key: f.start_ms for f in document_facts},
        known=gate.known,
    )
    thirds = windows.thirds(built)
    by_third = [0, 0, 0]
    for fact in document_facts:
        by_third[thirds.get(fact.window_index, 1) - 1] += 1
    excluded_ms = sum(max(0, e.end_ms - e.start_ms) for e in excluded)
    out.stats = {
        "facts_kept": stats.kept,
        "facts_dropped_quote": stats.dropped_quote,
        "facts_dropped_noise": stats.dropped_noise,
        "facts_dropped_example": stats.dropped_example,
        "facts_dropped_paraphrase": stats.dropped_paraphrase,
        "facts_flagged_paraphrase": stats.flagged_paraphrase,
        # F2 — copies in the final document (evidence only), windows asked
        # to restate and how that went, and what code dropped or fixed.
        "facts_copied": sum(1 for f in facts if f.copied),
        "windows_restated": restate["improved"] + restate["unchanged"],
        "restate_outcomes": dict(restate),
        "dropped_no_information": stats.dropped_no_information,
        "dropped_first_person": stats.dropped_first_person,
        "facts_descriptive": stats.descriptive,
        "recording_names": len(rec_names),
        "third_person_fixed": stats.third_person_fixed + gate.third_person_fixed,
        "children_restated": gate.children_restated,
        # F3 amendment — the engine's view of the turns.
        "microturns_merged": prepared.microturns_merged,
        "adverts_cut": len(prepared.adverts),
        # F3 — figures, introductions, calls to action.
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
        "excluded_ranges": [[e.start_ms, e.end_ms, e.reason] for e in excluded],
        "facts_by_third": by_third,
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
        "topics_merged": gate.topics_merged,
        "lines_by_third": _lines_by_third(out.sections, document_facts, thirds),
        "lines_total": sum(len(s.lines) for s in out.sections),
        "lint": linted.by_code(),
        "lint_rules": linted.by_rule(),
        "language": language,
        "recording_type": recording_type,
        "recording_type_source": recording_type_source,
    }
    return out


# F3 — introductions happen at the start: the first windows are searched.
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

# F3 amendment §2.1 — the presenter is the recording's own voice.
PRESENTER_MIN_SHARE: Final = 0.15
SPEAKER_MIN_TURNS: Final = 3
AD_CUE_AFTER_MS: Final = 20_000


def standing_of(fact: VerifiedFact, turns: list[windows.Turn]) -> str:
    """``presenter`` — the introducing voice is the recording's dominant
    speaker (≥ 15 % of speech, ≥ 3 turns) and no broadcast cue follows the
    name within 20 s; ``guest`` — any other speaker with ≥ 3 turns;
    ``clip`` — a trailer or a sound bite. A name is never inferred from a
    channel or a show."""
    speech: dict[str | None, int] = {}
    count: dict[str | None, int] = {}
    for turn in turns:
        speech[turn.speaker_label] = speech.get(turn.speaker_label, 0) + max(
            0, turn.end_ms - turn.start_ms
        )
        count[turn.speaker_label] = count.get(turn.speaker_label, 0) + 1
    label = fact.speaker_label
    total = sum(speech.values()) or 1
    if count.get(label, 0) < SPEAKER_MIN_TURNS or label in (None, "", "UNKNOWN"):
        return "clip"
    cued = any(
        t.speaker_label == label
        and fact.start_ms <= t.start_ms <= fact.start_ms + AD_CUE_AFTER_MS
        and windows.AD_CUES.search(t.text)
        for t in turns
    )
    if cued:
        return "clip"
    known = {k: v for k, v in speech.items() if k not in (None, "", "UNKNOWN")}
    dominant = max(known, key=lambda k: known[k]) if known else None
    if label == dominant and speech[label] / total >= PRESENTER_MIN_SHARE:
        return "presenter"
    return "guest"


def restated(
    first: list[VerifiedFact], second: list[VerifiedFact]
) -> tuple[list[VerifiedFact], int]:
    """F2's merge rule: each copied fact of the first answer is replaced by
    a second-answer fact that cites the same line and is not a copy; every
    other fact stays as it was. ``(facts, how many were replaced)``."""
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


def fact_budget(window: Window) -> int:
    """How many facts a window may carry: one per ~250 characters, between
    8 and 24. A dense news passage holds far more than twelve points, and
    a cap below that is how the audit's note lost most of a story."""
    return min(MAX_FACTS_BUDGET, max(MIN_FACTS_BUDGET, len(window.text) // 250))


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
    """Tier (b): the names in the facts nobody in the workspace knows, asked
    of the model once. Returns ``{old item_key: new item_key}`` for the
    facts whose text changed (a fact's key is its text).

    A proposal is applied only when it is close to what was heard
    (similarity ≥ ``entities.MODEL_THRESHOLD``) and is not a person already
    in the recording — the model may respell a name, never swap one
    participant for another. A proposal far from what was heard is not
    applied; the spelling stays and is marked "(?)"."""
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
    sections: list[render.RenderedSection], facts: list[VerifiedFact], thirds: dict[int, int]
) -> list[int]:
    """Written lines per third of the recording, by their first cited fact."""
    by_id = {f.item_key: f for f in facts}
    out = [0, 0, 0]
    for section in sections:
        for line in section.lines:
            cited = [by_id[i] for i in line.fact_ids if i in by_id]
            if cited:
                out[thirds.get(cited[0].window_index, 1) - 1] += 1
    return out


def _earliest_per_window(facts: list[VerifiedFact]) -> list[str]:
    """The first fact said in each window, for a code-only overview."""
    seen: dict[int, VerifiedFact] = {}
    for fact in sorted(facts, key=lambda f: f.start_ms):
        seen.setdefault(fact.window_index, fact)
    return [f.item_key for f in seen.values()][: schema.MAX_KEY_POINTS]


def section_hashes(sections: list[render.RenderedSection]) -> dict[str, str]:
    """``{section_key: sha256 of the text we wrote}``.

    The writer compares against these next time: a section whose text
    still equals what the last generation put there has not been touched
    by a person and may be rewritten. Anything else is the author's.
    """
    import hashlib

    return {s.section_key: hashlib.sha256(s.text.encode("utf-8")).hexdigest() for s in sections}


def _language_lines(window: Window, language: str) -> list[tuple[int, int, int, str]]:
    """Sprint I2: lines the ASR decoded in another language are flagged by
    CODE, whether or not the extractor noticed; ``confirm_noise`` confirms
    them from the same field."""
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


# A composed line must carry at least this share of its content from the
# facts it cites (Q2). Half: a sentence may connect and condense, it may
# not add. Per language since the F3 amendment (§2.10):
# ``support.line_support_threshold``.
# More than this share of a summary failing the gate means the model is
# writing from somewhere other than the facts: ask once more, strictly.
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
            ),
            0,
        )
    )
    retries: int = 0
    salient_appended: int = 0
    topics_merged: int = 0
    """F2 — sub-points that restated their parent; openers dropped."""
    children_restated: int = 0
    third_person_fixed: int = 0
    """A-12 — why the topics pass gave nothing (None when it did)."""
    topics_failure: str | None = None

    @property
    def dropped(self) -> int:
        """Q1's name for the example count."""
        return self.counts["example"]

    def echo(self, text: str) -> bool:
        if prompts.echoes_example(text):
            self.counts["example"] += 1
            return True
        return False

    def reason(self, text: str, cited: list[VerifiedFact], *, claims: bool = False) -> str | None:
        """Why this line may not be written, or None when it may.

        ``claims`` (summary sentences, Q4): a sentence resting on somebody's
        opinion or forecast must name them and keep its hedge. A sentence
        is prose and is dropped, not patched; a bullet is a record and is
        patched by render."""
        plain = render.strip_inline_ids(text)[0]
        if prompts.echoes_example(plain):
            return "example"
        if not cited:
            return "unsupported"
        # F2 — a transcript sentence is evidence, not a line; a remark that
        # informs nobody, or a line in the speaker's own voice, is not one.
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
        """Decision 4's one mechanical rewrite: a leading "So," / "Again,"
        / "Also," goes. Nothing else is ever changed in code."""
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
) -> schema.ExtractOut | None:
    """One window. ``None`` when the model could not answer in shape.
    ``system_suffix`` (F2) is the rule the last answer broke;
    ``introduction_lines`` (F3) the lines code found an introduction in."""
    prompt = prompts.extract_prompt(
        window.render(),
        language,
        carried=carried,
        max_facts=max_facts,
        introduction_lines=introduction_lines,
        contact_lines=contact_lines,
    )
    system = prompts.extract_system(language)
    if system_suffix:
        system = f"{system}\n\n{system_suffix}"
    for attempt in range(EXTRACT_ATTEMPTS):
        try:
            answer = await provider.complete(
                prompt,
                extract_schema or schema.EXTRACT_SCHEMA,
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
    """F3: fill the fields of figures the extraction left bare, with one
    call per window whose schema REQUIRES them. Fields the model already
    gave are kept; everything is still verified against the words. Returns
    ``(how many figures were asked about, the promoted twins)`` — the twins
    are NOT added to the model's answer (its size is the restate budget).

    ``promote``: a fact of another kind whose quote says a number is asked
    about too, as a figure next to it (a small model files "the beam is
    sixteen and a half feet" as a key point). The key point stays unless
    its figure verifies (:func:`_without_figure_twins`)."""
    bare = [f for f in extracted.facts if f.kind == schema.FIGURE and not (f.value and f.name)]
    twins: list[schema.Fact] = []
    if promote:
        figured = {(f.turn, f.quote) for f in extracted.facts if f.kind == schema.FIGURE}
        for fact in list(extracted.facts):
            if (
                fact.kind not in (schema.FIGURE, schema.INTRODUCTION, schema.JUDGEMENT)
                and (fact.turn, fact.quote) not in figured
                # The words, not the "[4] Speaker 1 (00:23):" header the
                # window shows: its digits are not anything anyone said.
                and numbers.numbers_in(verify.strip_turn_header(fact.quote), language)
            ):
                twin = fact.model_copy(update={"kind": schema.FIGURE})
                twins.append(twin)
                bare.append(twin)
        # A line that says a number and that no fact covers at all: a small
        # model extracting a long window stops early, and "length overall,
        # sixty six feet" two minutes in is exactly what it skips. Code only
        # picks the line; the model names the quantity; code verifies it.
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
    # One line per call: asked about a dozen lines at once, a small model
    # answers the first few and skips the rest. Bounded per window.
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
    """F3: a fact of another kind whose quote asks the listener to act
    ("email me or leave a comment") gets a `next_step` twin — a small model
    files the call to action as a key point. Verification still decides."""
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
    """F3: a line that asks the listener to act and that no fact states as a
    `next_step` is stated once, by one call whose schema requires the
    sentence. The sentence is a fact like any other: its quote is the line,
    and verification checks it (a copy of the line is evidence only)."""
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
    """F3: the same one follow-up for introductions without a name."""
    bare = [f for f in extracted.facts if f.kind == schema.INTRODUCTION and not f.name]
    if not bare:
        return
    lines = []
    for fact in bare:
        turn = verify.locate_quote(fact.quote, window, fact.turn)
        if turn is None:
            lines.append(verify.strip_turn_header(fact.quote))
            continue
        # The sentence after an introduction often says the rest ("We are
        # the … dealer for the Great Lakes") — verification reads it too.
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
            max_tokens=REDUCE_MAX_TOKENS,
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


async def _topics(
    provider: ChatLike,
    facts: list[VerifiedFact],
    language: str,
    *,
    brief: Brief | None = None,
    gate: _Gate | None = None,
) -> Topics | None:
    """Cluster facts into topics. Never sees the transcript.

    ``[(title, [(bullet, its fact ids)], the topic's fact ids)]`` — each
    bullet keeps what it cites, so every written line can say where it
    came from. A bullet that fails the gate is dropped; a topic left with
    fewer than two bullets is not a topic; fewer than two topics is one
    list, written by render."""
    gate = gate or _Gate(language=language)
    if len(facts) < schema.MIN_FACTS_FOR_TOPICS:
        # Too little to head: `render` writes one list, which is honest,
        # rather than inventing topics for a short conversation.
        return None
    block = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    try:
        answer = await provider.complete(
            _with_brief(block, brief, language),
            schema.REDUCE_TOPICS_SCHEMA,
            max_tokens=REDUCE_MAX_TOKENS,
            temperature=0.0,
            system=prompts.topics_system(language),
        )
        parsed = schema.ReduceOut.model_validate_json(_json_of(answer))
    except ValueError:
        gate.topics_failure = "schema_invalid"
        logger.warning("meeting_doc.topics_failed", exc_info=True)
        return None
    except Exception:  # noqa: BLE001
        gate.topics_failure = "provider_error"
        logger.warning("meeting_doc.topics_failed", exc_info=True)
        return None
    topics = _topics_from(parsed, facts, gate)
    if topics is None and gate.topics_failure is None:
        gate.topics_failure = (
            "too_few_topics" if len(parsed.topics) < 2 else "all_bullets_unsupported"
        )
    return topics


def _topics_from(parsed: schema.ReduceOut, facts: list[VerifiedFact], gate: _Gate) -> Topics | None:
    """Parsed topics → the gated structure render writes (≥ 2 topics)."""
    by_id = {f.item_key: f for f in facts}
    out: Topics = []
    for topic in parsed.topics:
        if not topic.title.strip() or gate.echo(topic.title):
            continue
        bullets: list[Bullet] = []
        for bullet in topic.bullets:
            text = gate.third_person(bullet.text.strip())
            ids = list(dict.fromkeys(i for i in bullet.fact_ids if i in by_id))
            # A bullet citing nothing we verified was written from memory;
            # one the cited facts do not carry says more than they do.
            if text and gate.ok(text, [by_id[i] for i in ids]):
                bullets.append((text, ids, _children(bullet, text, ids, by_id, gate)))
        if len(bullets) < MIN_BULLETS_PER_TOPIC:
            continue
        cited = [i for _t, ids, _c in bullets for i in ids]
        cited += [i for _t, _ids, kids in bullets for _k, child_ids in kids for i in child_ids]
        cited += [i for i in topic.fact_ids if i in by_id]
        out.append((topic.title.strip(), bullets, list(dict.fromkeys(cited))))
    out = _merge_overlapping(out, by_id, gate)
    _append_salient(out, facts, gate)
    if len(out) < 2:
        return None
    return out[: schema.MAX_TOPICS]


def _children(
    bullet: schema.TopicBullet,
    parent: str,
    parent_ids: list[str],
    by_id: dict[str, VerifiedFact],
    gate: _Gate,
) -> list[tuple[str, list[str]]]:
    """A bullet's sub-points that pass on their own (F2, decision 5): each
    cites a fact, passes the gate, and is not the parent said again."""
    out: list[tuple[str, list[str]]] = []
    parent_words = support.merge_tokens(parent)
    for child in bullet.children[: schema.MAX_CHILDREN]:
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


TWO_STAGE_MIN_FACTS: Final = 40
# §2.9 — an unnamed voice with this share of the talk is the narrator.
NARRATOR_MIN_SHARE: Final = 0.6
BLOCK_HEADINGS_MERGE_JACCARD: Final = 0.6


async def _topics_by_block(
    provider: ChatLike, facts: list[VerifiedFact], language: str, *, gate: _Gate
) -> Topics | None:
    """A-12 — a long recording's topics in two stages: time-contiguous
    blocks (≤ 8, ≥ 4 facts each, code), one call per block for a phase
    heading and its bullets, then adjacent blocks whose headings say the
    same are merged (code — a small model merging its own headings is one
    more place to fail)."""
    out: Topics = []
    for block in overview.reduce_blocks(facts):
        listing = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in block])
        try:
            answer = await provider.complete(
                listing,
                schema.BLOCK_TOPIC_SCHEMA,
                max_tokens=REDUCE_MAX_TOKENS,
                temperature=0.0,
                system=prompts.block_system(language),
            )
            parsed = schema.ReduceOut.model_validate_json(_json_of(answer))
        except Exception:  # noqa: BLE001 — one block must not cost the note
            logger.warning("meeting_doc.block_failed", exc_info=True)
            continue
        by_id = {f.item_key: f for f in block}
        for topic in parsed.topics[:1]:
            title = topic.title.strip()
            if not title or gate.echo(title):
                continue
            bullets: list[Bullet] = []
            for bullet in topic.bullets:
                text = gate.third_person(bullet.text.strip())
                ids = list(dict.fromkeys(i for i in bullet.fact_ids if i in by_id))
                if text and gate.ok(text, [by_id[i] for i in ids]):
                    bullets.append((text, ids, _children(bullet, text, ids, by_id, gate)))
            if bullets:
                cited = [i for _t, ids, _c in bullets for i in ids]
                out.append((title, bullets, list(dict.fromkeys([*cited, *by_id]))))
    merged: Topics = []
    for heading in out:
        if (
            merged
            and verify._jaccard(
                support.merge_tokens(merged[-1][0]), support.merge_tokens(heading[0])
            )
            >= BLOCK_HEADINGS_MERGE_JACCARD
        ):
            title, bullets, ids = merged[-1]
            merged[-1] = (title, [*bullets, *heading[1]], list(dict.fromkeys([*ids, *heading[2]])))
            gate.topics_merged += 1
            continue
        merged.append(heading)
    if len(merged) < 2:
        gate.topics_failure = "too_few_topics" if merged else "all_bullets_unsupported"
        return None
    return merged


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


def _speakers(turns: list[windows.Turn], facts: list[VerifiedFact], language: str) -> list[str]:
    """Named speakers in order of appearance; the presenter by name; an
    unnamed dominant voice as the narrator. Never a name nobody verified."""
    named: list[str] = []
    for turn in turns:
        if _a_real_name(turn) and turn.speaker_name not in named:
            named.append(turn.speaker_name or "")
    presenter = [
        f.person.name
        for f in facts
        if f.person is not None and f.person.standing == "presenter" and f.person.self_introduction
    ]
    for name in presenter[:1]:
        if name not in named:
            named.insert(0, name)
    if not named and turns:
        # One unnamed voice that carries the recording is its narrator; two
        # or more unnamed voices sharing it are nobody the note can name.
        talk: dict[str, int] = {}
        for turn in turns:
            label = turn.speaker_label or ""
            talk[label] = talk.get(label, 0) + turn.end_ms - turn.start_ms
        total = sum(talk.values())
        if total and max(talk.values()) / total >= NARRATOR_MIN_SHARE:
            return [str(overview._pick(overview.NARRATOR, language))]
    return named


_DEFAULT_NAME = re.compile(r"(?i)^(?:speaker[ _]?\d+|unknown(?: speaker)?|sprecher(?:in)? \d+)$")


def _a_real_name(turn: windows.Turn) -> bool:
    """A person named this voice — not the diarizer's label or the ASR
    view's default ("Speaker 2", "UNKNOWN")."""
    name = (turn.speaker_name or "").strip()
    return bool(name) and name != turn.speaker_label and not _DEFAULT_NAME.match(name)


def _guests(facts: list[VerifiedFact]) -> list[str]:
    out: list[str] = []
    for fact in sorted(facts, key=lambda f: f.start_ms):
        person = fact.person
        if person is None or person.standing != "guest" or person.name in out:
            continue
        where = ", ".join(p for p in (person.organisation, person.qualifier) if p)
        out.append(f"{person.name} ({where})" if where else person.name)
    return out


def _span(ids: list[str], by_id: dict[str, VerifiedFact]) -> tuple[int, int]:
    times = [by_id[i].start_ms for i in ids if i in by_id]
    return (min(times), max(times)) if times else (0, 0)


def _merge_overlapping(
    topics: Topics,
    by_id: dict[str, VerifiedFact],
    gate: _Gate,
) -> Topics:
    """Two topics, next to each other in time, whose stretches of the
    recording overlap by more than half of the shorter one are one subject
    the model split (Q4)."""
    ordered = sorted(topics, key=lambda t: _span(t[2], by_id)[0])
    out: Topics = []
    for topic in ordered:
        if out:
            (a0, a1), (b0, b1) = _span(out[-1][2], by_id), _span(topic[2], by_id)
            shorter = min(a1 - a0, b1 - b0)
            overlap = min(a1, b1) - max(a0, b0)
            if shorter > 0 and overlap > shorter / 2:
                title, bullets, ids = out[-1]
                out[-1] = (title, [*bullets, *topic[1]], list(dict.fromkeys([*ids, *topic[2]])))
                gate.topics_merged += 1
                continue
        out.append(topic)
    return out


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
    """A key point with a number, a date or a person in it is kept even
    when no bullet wrote about it (Q4): it joins the topic nearest to it in
    time. Coverage is a budget, not a hope."""
    if not topics:
        return
    by_id = {f.item_key: f for f in facts}
    written = {i for _t, bullets, _ids in topics for bullet in bullets for i in bullet[1]}
    for fact in facts:
        if fact.kind != schema.KEY_POINT or not fact.salient or fact.item_key in written:
            continue
        # F2 — the fact's own text is the line here: evidence stays evidence.
        if fact.evidence_only:
            continue

        index = min(range(len(topics)), key=lambda k, f=fact: _distance(topics[k], f, by_id))
        title, bullets, ids = topics[index]
        topics[index] = (
            title,
            [*bullets, (fact.text, [fact.item_key], [])],
            [*ids, fact.item_key],
        )
        written.add(fact.item_key)
        gate.salient_appended += 1


async def _summary(
    provider: ChatLike,
    facts: list[VerifiedFact],
    language: str,
    *,
    brief: Brief | None = None,
    gate: _Gate | None = None,
) -> list[tuple[str, list[str]]] | None:
    """``[(sentence, the fact ids it rests on)]``, or None.

    Every sentence passes the gate or is dropped. When more than
    ``SUMMARY_FAIL_SHARE`` of an answer fails, the model is asked once
    more with the strict suffix ("use the wording of the facts"); failing
    that too, there is no summary and the overview is written by code."""
    gate = gate or _Gate(language=language)
    block = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    by_id = {f.item_key: f for f in facts}
    system = prompts.summary_system(language)
    for attempt in range(2):
        try:
            answer = await provider.complete(
                _with_brief(block, brief, language),
                schema.REDUCE_SUMMARY_SCHEMA,
                max_tokens=REDUCE_MAX_TOKENS,
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
            # "Der Start im November bleibt das Ziel": the 2026-09-22
            # audit's invented sentence was the prompt's own example and
            # cited a real fact. A cited id is not support.
            if gate.ok(sentence, cited, claims=True):
                out.append((sentence, [f.item_key for f in cited]))
        failed = answered - len(out)
        if (answered and failed / answered > SUMMARY_FAIL_SHARE) or not answered:
            if attempt == 0:
                gate.retries += 1
                # Rung 2: the facts to use, in time order, one sentence per
                # one or two of them.
                ordered = [f.item_key for f in sorted(facts, key=lambda f: f.start_ms)][:12]
                groups = [ordered[k : k + 2] for k in range(0, len(ordered), 2)][:6]
                system = (
                    f"{system}\n\n{prompts.strict_suffix(language)}\n"
                    f"{prompts.skeleton(groups, language)}"
                )
                continue
            return None
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
