"""The ``note.generate`` job (note-worker): a transcript becomes a document.

Writes twice: items after extract/verify/merge, then summary and topics after
reduce. Both go through `meeting_doc.writer`, which never overwrites a person's
text; a re-run after a crash writes nothing new because the section hashes match.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from db import tenant_connection
from note_models import NoteStatus

from .. import generation_metrics
from ..domain import carry_over, note_title
from ..domain import generation_repository as gen_repo
from ..domain import meetings_repository as meetings
from ..domain import notes_repository as repo
from ..domain.meeting_doc import (
    classify,
    doclint,
    pipeline,
    prompts,
    roles,
    types,
    windows,
    writer,
)
from ..domain.meeting_doc.render import RenderedSection

logger = logging.getLogger(__name__)

STEP_EXTRACT = "extract"
STEP_WRITE_ITEMS = "write_items"
STEP_REDUCE = "reduce"
STEP_WRITE_DOC = "write_doc"

# Roles the first write covers: what the reader came for.
ITEM_ROLES = frozenset(
    {roles.DECISIONS, roles.ACTION_ITEMS, roles.OPEN_QUESTIONS, roles.RISKS,
     roles.NEXT_MEETING, roles.AGENDA, roles.ATTENDEES}
)  # fmt: skip


class GenerationDeps:
    """What the handler needs; a plain object the tests fill with fakes."""

    def __init__(
        self,
        *,
        app_pool: Any,
        transcripts_store: Any,
        provider_for: Any,
        audit_writer: Any = None,
        shadow_provider_for: Any = None,
        shadow_percent: int = 0,
        entity_model_tier: bool = False,
        operation_provider_for: Any = None,
        coverage_retry_budget_s_per_hour: float | None = None,
    ) -> None:
        self.app_pool = app_pool
        self.transcripts_store = transcripts_store
        self.provider_for = provider_for
        # `(workspace_id, operation) -> provider` for the short calls; None: the writing model.
        self.operation_provider_for = operation_provider_for
        self.audit_writer = audit_writer
        # Candidate backend run beside the real one on a sample; output thrown away.
        self.shadow_provider_for = shadow_provider_for
        self.shadow_percent = shadow_percent
        self.entity_model_tier = entity_model_tier
        self.coverage_retry_budget_s_per_hour = coverage_retry_budget_s_per_hour


def _retry_budget(deps: GenerationDeps, built: list[Any] | None) -> float | None:
    """Seconds the generation may run before the coverage retry is skipped."""
    per_hour = getattr(deps, "coverage_retry_budget_s_per_hour", None)
    if per_hour is None or not built:
        return None
    hours = max(0, built[-1].end_ms - built[0].start_ms) / 3_600_000
    return per_hour * max(hours, 1 / 60)


async def handle_generate(deps: GenerationDeps, *, tenant_id: UUID, payload: dict) -> dict:
    """One generation, start to finish. Returns ids and counts only, never content."""
    generation_id = UUID(str(payload["generation_id"]))
    note_id = UUID(str(payload["note_id"]))

    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        generation = await gen_repo.fetch(conn, generation_id=generation_id)
        if generation is None:
            return {"skipped": "generation_gone"}
        note = await repo.fetch_note(conn, note_id=note_id)
        if note is None or note.status != NoteStatus.DRAFT:
            # Deleted or cancelled while queued. Not a failure.
            await gen_repo.mark(
                conn, generation_id=generation_id, status=gen_repo.SUPERSEDED, finished=True
            )
            return {"skipped": "note_gone"}
        previous = await gen_repo.last_written(conn, note_id=note_id, before=generation_id)
        previous_hashes = (previous.stats or {}).get("section_hashes", {}) if previous else {}
        template_roles, template_code = await _role_map(conn, note_id=note_id)
        template_family = types.family_for_template(template_code)
        # Still-open items from the previous meeting, so the extractor can tick them off.
        carried = await _carried(conn, note_id=note_id)
        meeting = await meetings.fetch(conn, note_id=note_id)
        counterpart = _counterpart(meeting)
        await gen_repo.mark(
            conn, generation_id=generation_id, status=gen_repo.RUNNING, step=STEP_EXTRACT
        )

    if not generation.snapshot_key:
        return await _fail(deps, tenant_id, generation_id, "no_snapshot")

    try:
        raw = await deps.transcripts_store.get(
            key=generation.snapshot_key, tenant_id=tenant_id, aad=generation_id.bytes
        )
        result = json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.warning("note_generate.snapshot_unreadable", exc_info=True)
        return await _fail(deps, tenant_id, generation_id, "snapshot_unreadable")

    provider = await deps.provider_for(str(tenant_id))
    classify_provider = await _operation_provider(deps, tenant_id, "classify", provider)
    title_provider = await _operation_provider(deps, tenant_id, "title", provider)
    entity_provider = await _operation_provider(deps, tenant_id, "entities", provider)
    language = str(result.get("language") or "en")
    # Relative dates resolve against the day it was RECORDED, not today.
    started = getattr(meeting, "started_at", None) if meeting else None
    meeting_date = (started or note.created_at or datetime.now(UTC)).date()

    # The recording type decides which kinds are extracted; classify what the
    # pipeline will read (adverts cut), windows sized to the writing model's context.
    turns = windows.turns_from_result(result)
    turns = windows.prepare_turns(turns).turns
    built = windows.build_windows(
        turns, max_chars=windows.window_chars(getattr(provider, "context_window", None))
    )
    recording_type, recording_source = await _recording_type(
        classify_provider,
        meeting=meeting,
        template_family=template_family,
        built=built,
        turns=turns,
        language=language,
    )
    family = types.family_for_recording_type(recording_type)
    await _store_detected_type(
        deps, tenant_id, note_id=note_id, recording_type=recording_type, source=recording_source
    )
    known_people, glossary = await _known_names(deps, tenant_id, result=result, meeting=meeting)

    document = await pipeline.run(
        result,
        provider=provider,
        role_by_key=template_roles,
        language=language,
        meeting_date=meeting_date,
        family=family,
        carried=carried,
        counterpart=counterpart,
        built=built,
        recording_type=recording_type,
        recording_type_source=recording_source,
        name_candidates=known_people,
        glossary=glossary,
        entity_model_tier=deps.entity_model_tier,
        entity_provider=entity_provider,
        retry_budget_s=_retry_budget(deps, built),
    )
    # Lint, repair, fall back, record (stats.lint). Never raises.
    document = await doclint.enforce(
        document, regenerate=document.regenerator, known=frozenset(known_people)
    )
    # The title comes after the whole recording was read; one short call that cannot stop the note.
    themes, title_facts = _title_context(document)
    await _name_note(
        deps,
        tenant_id,
        note_id=note_id,
        generation_id=generation_id,
        requested_by=generation.requested_by,
        result=result,
        provider=title_provider,
        language=language,
        themes=themes,
        facts=title_facts,
    )

    # ── Write #1: what the reader came for ──────────────────────────
    items_sections = [s for s in document.sections if s.role in ITEM_ROLES]
    doc_sections = [s for s in document.sections if s.role not in ITEM_ROLES]

    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        await gen_repo.mark(
            conn,
            generation_id=generation_id,
            step=STEP_WRITE_ITEMS,
            windows_total=document.windows_total,
            windows_done=document.windows_done,
            windows_failed=document.windows_failed,
            failed_ranges=document.failed_ranges,
            backend=document.backend,
            model_id=document.model_id,
        )
        first = await writer.apply(
            conn,
            note_id=note_id,
            sections=items_sections,
            requested_by=generation.requested_by,
            generation_id=generation_id,
            prompt_version=prompts.PROMPT_VERSION,
            step=STEP_WRITE_ITEMS,
            previous_hashes=previous_hashes,
        )
        await _store_items(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            generation_id=generation_id,
            sections=items_sections,
            outcome=first,
            family=family,
            facts=document.facts,
        )

    # ── Write #2: the summary and the topics ────────────────────────
    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        await gen_repo.mark(conn, generation_id=generation_id, step=STEP_WRITE_DOC)
        second = await writer.apply(
            conn,
            note_id=note_id,
            sections=doc_sections,
            requested_by=generation.requested_by,
            generation_id=generation_id,
            prompt_version=prompts.PROMPT_VERSION,
            step=STEP_WRITE_DOC,
            previous_hashes=previous_hashes,
        )
        await _store_items(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            generation_id=generation_id,
            sections=doc_sections,
            outcome=second,
            family=family,
            facts=document.facts,
        )
        # Verified facts no line cites: the "Detailed" view's rows.
        await gen_repo.put_lines(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            generation_id=generation_id,
            rows=uncited_rows(document, family=family),
        )

        # Completions and judgements are not lines of the note.
        ticked = await _apply_completions(conn, note_id=note_id, completions=document.completions)
        await _store_judgements(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            generation_id=generation_id,
            judgements=document.judgements,
            family=family,
        )

        stats = dict(document.stats)
        stats["section_hashes"] = {**first.section_hashes, **second.section_hashes}
        stats["suggested_sections"] = sorted(
            {*first.suggested_sections, *second.suggested_sections}
        )
        stats["carried_ticked"] = ticked
        stats["judgements"] = len(document.judgements)
        await gen_repo.supersede_previous(conn, note_id=note_id, keep=generation_id)
        await gen_repo.mark(
            conn,
            generation_id=generation_id,
            status=gen_repo.PARTIAL if document.partial else gen_repo.COMPLETE,
            step=None,
            stats=stats,
            finished=True,
        )

    await _shadow_run(
        deps,
        tenant_id,
        generation_id,
        result,
        document,
        role_by_key=template_roles,
        language=language,
        meeting_date=meeting_date,
        family=family,
        carried=carried,
        counterpart=counterpart,
    )

    # The transcript still lives in asr-service; a second copy is a retention decision
    # nobody made. The daily sweep catches snapshots whose worker died first.
    await _discard_snapshot(deps, tenant_id, generation_id)

    written = len(first.written_sections) + len(second.written_sections)
    suggested = len(first.suggested_sections) + len(second.suggested_sections)
    backend = document.backend or "unknown"
    generation_metrics.generations.add(
        1, {"outcome": "partial" if document.partial else "complete", "backend": backend}
    )
    generation_metrics.record_document(document.stats, backend=backend)
    unsupported = document.stats.get("lines_unsupported") or {}
    logger.info(
        "note_generate.done",
        extra={
            "windows": document.windows_total,
            "failed": document.windows_failed,
            "sections_written": written,
            "sections_suggested": suggested,
            # Counts only; never a line, a fact or a quote.
            "facts_kept": document.stats.get("facts_kept", 0),
            "facts_dropped_paraphrase": document.stats.get("facts_dropped_paraphrase", 0),
            "lines_kept": document.stats.get("lines_kept", 0),
            "lines_unsupported": sum(int(n) for n in unsupported.values()),
            "excluded_ms": document.stats.get("excluded_ms", 0),
            "speech_ms": document.stats.get("speech_ms", 0),
            "noise_overridden": document.stats.get("noise_overridden", 0),
            "summary_fallback": document.stats.get("summary_fallback"),
            "summary_ladder": document.stats.get("summary_ladder"),
            "topics_fallback": document.stats.get("topics_fallback"),
            "topics_failure": document.stats.get("topics_failure"),
            "adverts_cut": document.stats.get("adverts_cut", 0),
            "lint_unresolved": (document.stats.get("lint") or {}).get("unresolved"),
            "lint_error": bool((document.stats.get("lint") or {}).get("error")),
            "prompt_version": document.stats.get("prompt_version"),
        },
    )
    return {
        "windows": document.windows_total,
        "windows_failed": document.windows_failed,
        "sections_written": written,
        "sections_suggested": suggested,
        "facts": len(document.facts),
    }


async def _operation_provider(
    deps: GenerationDeps, tenant_id: UUID, operation: str, default: Any
) -> Any:
    """The provider routed for one short operation, else `default`; a routing problem never stops the note."""
    if deps.operation_provider_for is None:
        return default
    try:
        return await deps.operation_provider_for(str(tenant_id), operation)
    except Exception:  # noqa: BLE001
        logger.warning("note_generate.operation_provider_failed", extra={"operation": operation})
        return default


def _title_context(document: Any) -> tuple[list[str], list[str]]:
    """The note's themes and its five most specific statements, taken in turn from each third."""
    from note_service.domain.meeting_doc import support as support_rules
    from note_service.domain.meeting_doc import windows as windows_mod

    brief = getattr(document, "brief", None) or {}
    themes = [str(t) for t in brief.get("themes") or [] if str(t).strip()]
    facts = [
        f
        for f in getattr(document, "facts", None) or []
        if not f.evidence_only and f.person is None and f.figure is None
    ]
    if not facts:
        return themes, []
    language = str((document.stats or {}).get("language") or "en")
    start = min(f.start_ms for f in facts)
    end = max(f.end_ms for f in facts)
    by_third: dict[int, list[Any]] = {1: [], 2: [], 3: []}
    for fact in facts:
        by_third[windows_mod.third_of(fact.start_ms, start, end)].append(fact)
    for group in by_third.values():
        group.sort(key=lambda f: -support_rules.specificity(f.text, language))
    chosen: list[str] = []
    while len(chosen) < note_title.CONTEXT_FACTS and any(by_third.values()):
        for k in (1, 2, 3):
            if by_third[k] and len(chosen) < note_title.CONTEXT_FACTS:
                chosen.append(by_third[k].pop(0).text)
    return themes, chosen


async def _name_note(
    deps: GenerationDeps,
    tenant_id: UUID,
    *,
    note_id: UUID,
    generation_id: UUID,
    requested_by: UUID,
    result: dict[str, Any],
    provider: Any,
    language: str,
    themes: list[str] | None = None,
    facts: list[str] | None = None,
) -> None:
    """Replace the placeholder title with one taken from the meeting.

    The title source is read before the call (a person's title costs no call) and
    again under the row lock in `note_title.apply`, so a concurrent rename wins.
    """
    try:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            if await note_title.source_of(conn, note_id=note_id) != note_title.DEFAULT:
                return
        title = await note_title.suggest(
            provider, result, language=language, themes=themes or (), facts=facts or ()
        )
        if title is None:
            logger.info("note_generate.title_skipped")
            return
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            written = await note_title.apply(
                conn,
                note_id=note_id,
                title=title,
                requested_by=requested_by,
                generation_id=generation_id,
            )
        logger.info("note_generate.title_done", extra={"written": written})
    except Exception:  # noqa: BLE001 — the note matters more than its name
        logger.warning("note_generate.title_failed", exc_info=True)


async def _store_items(
    conn: Any,
    *,
    tenant_id: UUID,
    note_id: UUID,
    generation_id: UUID,
    sections: list[RenderedSection],
    outcome: writer.WriteOutcome,
    family: Any = None,
    facts: list[Any] | None = None,
) -> None:
    """Every written LINE is a row: text, citations, evidence of the first cited fact.
    Placement: written when we wrote the section, suggested when the author had been in there."""
    by_id = {f.item_key: f for section in sections for f in section.facts}
    for fact in facts or []:
        by_id.setdefault(fact.item_key, fact)
    rows: list[dict[str, Any]] = []
    for section in sections:
        placement = (
            writer.WRITTEN
            if section.section_key in outcome.written_sections
            or section.section_key in outcome.section_hashes
            else writer.SUGGESTED
        )
        for line in section.lines:
            row = line_row(line, section.section_key, placement, by_id, family=family)
            if row is not None:
                rows.append(row)
    if rows:
        stored = await gen_repo.put_lines(
            conn, tenant_id=tenant_id, note_id=note_id, generation_id=generation_id, rows=rows
        )
        for row in rows:
            generation_metrics.lines_stored.add(1, {"kind": row["kind"]})
        logger.info("note_generate.lines_stored", extra={"rows": stored})


# A line written from one fact keeps that fact's kind (recipient page, corrections routes).
_ROW_KIND: Final[dict[str, str]] = {
    "summary": "summary_sentence",
    "framing": "framing",
    "bullet": "topic_bullet",
    "date": "date",
    # A quote sub-point is a topic bullet row.
    "quote": "topic_bullet",
}
# A line resting on several facts is as sure as its weakest one.
_CERTAINTY_RANK: Final[dict[str, int]] = {
    "fact": 0,
    "estimate": 1,
    "prediction": 2,
    "opinion": 3,
    "proposal": 4,
    "allegation": 5,
}


def line_row(
    line: Any, section_key: str, placement: str, by_id: dict[str, Any], *, family: Any = None
) -> dict[str, Any] | None:
    """The row for one written line, or None for a line with no evidence (a heading). Pure."""
    from ..domain import lines as line_rules

    cited = [by_id[i] for i in line.fact_ids if i in by_id]
    if not cited or line.kind == "heading":
        return None
    first = cited[0]
    content = line_rules.strip_marker(line.text)[1]
    certainties = [f.certainty for f in cited if f.certainty]
    holders = {f.attributed_to for f in cited}
    corrections = list(
        dict.fromkeys(
            (c.surface, c.canonical, c.source) for f in cited for c in getattr(f, "corrections", ())
        )
    )
    internal = family is not None and any(types.is_internal_kind(family, f.kind) for f in cited)
    return {
        # The corrections routes' own key rule: owner and due stripped.
        "item_key": line_rules.key_of(content),
        "kind": _ROW_KIND.get(line.kind, first.kind),
        "section_key": section_key,
        "text": content[:500],
        "owner_label": first.owner_label,
        "due_text": first.due_text,
        "due_date": first.due_date,
        "explicit": first.explicit,
        "confidence": first.confidence,
        "flags": list(first.flags),
        "quote": first.quote,
        "start_ms": first.start_ms,
        "end_ms": first.end_ms,
        "speaker_label": first.speaker_label,
        "speaker_name": first.speaker_name,
        "placement": placement,
        "audience": "internal" if internal else "all",
        "cites": [f.item_key for f in cited],
        "certainty": max(certainties, key=lambda c: _CERTAINTY_RANK.get(c, 0))
        if certainties
        else None,
        "attributed_to": next(iter(holders)) if len(holders) == 1 else None,
        "corrections": [{"surface": s, "canonical": c, "source": src} for s, c, src in corrections],
        # A figure row carries its verified fields, so a client draws the value without parsing.
        "payload": first.figure.payload()
        if getattr(first, "figure", None) is not None and line.kind == "figure"
        else None,
        # A sub-point names the bullet it sits under by that row's key.
        "parent_key": line_rules.key_of(line_rules.strip_marker(line.parent)[1])
        if getattr(line, "parent", None)
        else None,
        "mentions": [
            {
                "text": m.text,
                "date": m.resolved.isoformat(),
                "time": m.time.strftime("%H:%M") if m.time else None,
                "direction": m.direction,
            }
            for m in line.dates
        ],
    }


def uncited_rows(document: Any, *, family: Any = None) -> list[dict[str, Any]]:
    """``suggested`` rows for uncited facts (under the nearest topic, else the overview)
    and ``evidence`` rows for evidence-only facts, cited or not. Pure."""
    from ..domain.meeting_doc import render as render_rules
    from ..domain.meeting_doc import roles as role_rules

    cited = {i for s in document.sections for line in s.lines for i in line.fact_ids}
    topics = [s for s in document.sections if s.role == role_rules.TOPICS and s.facts]
    out: list[dict[str, Any]] = []
    for fact in document.facts:
        if fact.kind in ("completion", "judgement"):
            continue
        # Evidence-only facts always get a row: the evidence popover resolves citations by row.
        if fact.item_key in cited and not fact.evidence_only:
            continue
        home = min(
            topics,
            key=lambda s, f=fact: min(abs(x.start_ms - f.start_ms) for x in s.facts),
            default=None,
        )
        line = render_rules.Line(fact.text, fact.kind, (fact.item_key,), fact.mentions)
        section_key = home.section_key if home else role_rules.OVERVIEW_KEY
        # Copies and unwritten figures are stored for evidence, never offered as a line.
        placement = (
            writer.EVIDENCE
            if fact.evidence_only or getattr(fact, "figure", None) is not None
            else writer.SUGGESTED
        )
        row = line_row(line, section_key, placement, {fact.item_key: fact}, family=family)
        if row is not None:
            out.append(row)
    return out


async def _recording_type(
    provider: Any,
    *,
    meeting: Any,
    template_family: types.Family,
    built: list[Any],
    turns: list[Any],
    language: str,
) -> tuple[str, str]:
    """``(recording_type, source)``: the author's meeting type or specific template wins;
    only an `auto` note on the generic template is classified."""
    chosen = getattr(meeting, "meeting_type", None) or "auto"
    if chosen != "auto":
        outcome = (types.recording_type_for_meeting_type(chosen), classify.SOURCE_USER)
    elif template_family.meeting_type != "auto":
        # A template the author picked is their choice too.
        outcome = (
            types.recording_type_for_meeting_type(template_family.meeting_type),
            classify.SOURCE_USER,
        )
    else:
        context = (getattr(meeting, "calendar_context", None) or {}) if meeting else {}
        span = (turns[-1].end_ms - turns[0].start_ms) if turns else 0
        outcome = await classify.classify(
            provider,
            head="\n".join(w.render() for w in built[:2]),
            language=language,
            speakers=len({t.speaker_label for t in turns if t.speaker_label}) or 1,
            minutes=span / 60_000,
            calendar_title=str(context.get("title") or "") or None,
            attendees=len(context.get("attendee_names") or []),
        )
    # `template` means the classifier could not answer: the meeting family.
    metric = "failed" if outcome[1] == classify.SOURCE_TEMPLATE else outcome[1]
    generation_metrics.classify.add(1, {"outcome": metric})
    return outcome


async def _known_names(
    deps: GenerationDeps, tenant_id: UUID, *, result: dict, meeting: Any
) -> tuple[frozenset[str], tuple[Any, ...]]:
    """``(known people, glossary terms)``: ASR name candidates, roster, calendar
    attendees, glossary persons. The glossary is read inside THIS tenant's
    connection; an unreadable glossary costs the glossary tier, not the note."""
    from ..domain import glossary_repository

    people = {str(n) for n in result.get("name_candidates") or [] if n}
    people |= {
        str(n)
        for n in (result.get("speaker_names") or {}).values()
        if n and not str(n).startswith("Speaker ")
    }
    context = (getattr(meeting, "calendar_context", None) or {}) if meeting else {}
    people |= {str(n) for n in context.get("attendee_names") or [] if n}
    terms: tuple[Any, ...] = ()
    try:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            terms = tuple(await glossary_repository.terms_for_matching(conn))
    except Exception:  # noqa: BLE001
        logger.warning("note_generate.glossary_unavailable", exc_info=True)
    people |= {t.term for t in terms if t.kind == "person"}
    return frozenset(people), terms


async def _store_detected_type(
    deps: GenerationDeps, tenant_id: UUID, *, note_id: UUID, recording_type: str, source: str
) -> None:
    """Record it on the note's meeting row; never stops a generation."""
    detected_by = "user" if source == classify.SOURCE_USER else "model"
    try:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            await meetings.set_detected_type(
                conn,
                note_id=note_id,
                detected=types.detected_value(recording_type),
                detected_by=detected_by,
            )
    except Exception:  # noqa: BLE001 — e.g. 0058 not applied yet
        logger.warning("note_generate.recording_type_not_stored", exc_info=True)


def _counterpart(meeting: Any) -> str:
    """The other side's name for the "Acme does" heading, from the calendar event's title."""
    if meeting is None:
        return ""
    title = str((meeting.calendar_context or {}).get("title") or "")
    # "Acme <> Us — Weekly" → "Acme"; no separator, no party name.
    for sep in ("<>", "—", "–", "|", "/"):
        if sep in title:
            head = title.split(sep)[0].strip()
            return head if 1 < len(head) <= 40 else ""
    return ""


async def _carried(conn: Any, *, note_id: UUID) -> list[tuple[str, str]]:
    """``[(item_key, text)]`` of still-open items, read from THIS note's "Still open"
    block: the visibility rule (ADR-0057) was applied at carry-in, and the worker
    has no claims to re-apply it, so it must not reach into another note."""
    rows = [
        r
        for r in await meetings.carried_items(conn, note_id=note_id)
        if str(r["state"]) == carry_over.OPEN
    ]
    if not rows:
        return []
    note = await repo.fetch_note(conn, note_id=note_id)
    version = await repo.fetch_version(conn, version_id=note.current_version_id) if note else None
    if version is None:
        return []

    from ..domain import lines as line_rules

    by_key: dict[str, str] = {}
    for section in version.content.sections:
        for line in line_rules.split_section(section.text or ""):
            parts = line_rules.parts(line.content)
            # The key is over the body of "- [ ] Owner: task — due".
            by_key.setdefault(line_rules.key_of(parts.body), parts.body)

    out: list[tuple[str, str]] = []
    for row in rows[: carry_over.MAX_CARRIED]:
        key = str(row["item_key"])
        text = by_key.get(key)
        if text:
            out.append((key, text))
    return out


async def _apply_completions(conn: Any, *, note_id: UUID, completions: list[Any]) -> int:
    """Tick off what the recording says was done, with the words: `done_mentioned`
    (the machine heard so), never `done_marked` (a person ticked it)."""
    ticked = 0
    for fact in completions:
        if not fact.refers_to_key:
            continue
        updated = await meetings.set_carried_state(
            conn,
            note_id=note_id,
            item_key=fact.refers_to_key,
            state=carry_over.DONE_MENTIONED,
            done_quote=fact.quote,
            done_start_ms=fact.start_ms,
            done_end_ms=fact.end_ms,
            done_speaker=fact.speaker_name,
        )
        ticked += 1 if updated else 0
    return ticked


async def _store_judgements(
    conn: Any,
    *,
    tenant_id: UUID,
    note_id: UUID,
    generation_id: UUID,
    judgements: list[Any],
    family: Any,
) -> None:
    """Judgement values are stored as SUGGESTIONS only; the engine never writes field metadata."""
    if not judgements:
        return
    await gen_repo.put_items(
        conn,
        tenant_id=tenant_id,
        note_id=note_id,
        generation_id=generation_id,
        facts=[(f, f.judgement_field or "", writer.SUGGESTED) for f in judgements],
        audience_of=lambda _f: "internal",
    )


async def _role_map(conn: Any, *, note_id: UUID) -> tuple[dict[str, str], str | None]:
    """``({section_key: role}, template code)`` for the note's template."""
    from ..domain.repository import get_template

    template_id = await conn.fetchval("SELECT template_id FROM notes WHERE id = $1", note_id)
    if template_id is None:
        return {}, None
    row = await get_template(conn, template_id=template_id)
    if row is None:
        return {}, None
    raw = row["schema_jsonb"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    from template_models import TemplateDefinition

    try:
        definition = TemplateDefinition.model_validate(raw)
    except Exception:  # noqa: BLE001
        return {}, None
    return roles.role_map(definition), str(row["code"])


async def mark_dead(
    deps: GenerationDeps, *, tenant_id: UUID, payload: dict, error_kind: str
) -> None:
    """The job will never run again: settle the generation row.

    The runner's probe runs BEFORE :func:`handle_generate`, so a down backend can
    exhaust the attempts with the row still `queued` (client spins, regenerate
    refused). Only a live row is touched; a `complete` run keeps its status.
    """
    generation_id = UUID(str(payload["generation_id"]))
    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        generation = await gen_repo.fetch(conn, generation_id=generation_id)
    if generation is None or generation.status not in gen_repo.LIVE_STATUSES:
        return
    await _fail(deps, tenant_id, generation_id, error_kind)


async def _fail(
    deps: GenerationDeps, tenant_id: UUID, generation_id: UUID, error_kind: str
) -> dict:
    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        await gen_repo.mark(
            conn,
            generation_id=generation_id,
            status=gen_repo.FAILED,
            error_kind=error_kind,
            finished=True,
        )
    generation_metrics.generations.add(1, {"outcome": "failed", "backend": "unknown"})
    await _discard_snapshot(deps, tenant_id, generation_id)
    return {"error_kind": error_kind}


async def _discard_snapshot(deps: GenerationDeps, tenant_id: UUID, generation_id: UUID) -> None:
    """Drop the run's transcript snapshot: row first, then the object (an orphan
    object is swept within the day; a dangling row is not)."""
    try:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            key = await gen_repo.clear_snapshot(conn, generation_id=generation_id)
        if key:
            await deps.transcripts_store.delete(key=key)
    except Exception:  # noqa: BLE001 — the note is written; this is tidying
        logger.warning("note_generate.snapshot_not_discarded", exc_info=True)


async def _shadow_run(
    deps: GenerationDeps,
    tenant_id: UUID,
    generation_id: UUID,
    transcript: dict,
    live: Any,
    **pipeline_kwargs: Any,
) -> None:
    """Run a candidate backend on this meeting and keep only the numbers; nothing it
    produces is written. Sampled deterministically on the generation id, so a
    re-run makes the same choice."""
    if not deps.shadow_provider_for or deps.shadow_percent <= 0:
        return
    if generation_id.int % 100 >= deps.shadow_percent:
        return

    backend = "unknown"
    started = time.monotonic()
    try:
        provider = await deps.shadow_provider_for(str(tenant_id))
        if provider is None:
            # Workspace has not acknowledged the candidate's processor: silently skip.
            return
        backend = getattr(provider, "backend_name", None) or backend
        shadow = await pipeline.run(transcript, provider=provider, **pipeline_kwargs)
    except Exception:  # noqa: BLE001 — a shadow run can never fail a note
        generation_metrics.shadow_runs.add(1, {"backend": backend, "outcome": "error"})
        logger.warning("note_generate.shadow_failed", extra={"backend": backend}, exc_info=True)
        return

    seconds = time.monotonic() - started
    generation_metrics.shadow_seconds.record(seconds, {"backend": backend})
    generation_metrics.shadow_runs.add(1, {"backend": backend, "outcome": "ok"})
    generation_metrics.shadow_facts.add(len(shadow.facts), {"backend": backend, "verdict": "kept"})
    # The live run is the only yardstick here; quality is measured by the gold-set harness.
    delta = len(live.facts) - len(shadow.facts)
    if delta > 0:
        generation_metrics.shadow_facts.add(delta, {"backend": backend, "verdict": "missed"})
    logger.info(
        "note_generate.shadow_done",
        extra={
            "backend": backend,
            "seconds": round(seconds, 1),
            "facts": len(shadow.facts),
            "live_facts": len(live.facts),
            "windows_failed": shadow.windows_failed,
        },
    )
