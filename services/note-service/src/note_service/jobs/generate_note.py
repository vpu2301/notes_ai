"""The ``note.generate`` job: a transcript becomes a document.

Runs in `note-worker`, not in the API. A model call over ten windows of
an hour-long meeting takes minutes and holds a lot of memory; doing that
inside a request would tie a user's browser to it and let one slow
meeting starve every other note operation.

The handler writes **twice**, on purpose:

1. after extract/verify/merge — the tasks and decisions, which are what
   the user opened the note for;
2. after reduce — the summary and the topics, which take longer and
   matter less in the first thirty seconds.

Both writes go through `meeting_doc.writer`, which never overwrites
anything a person typed. A crash between them re-runs the whole job, and
the second attempt writes nothing new because the section hashes match.
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
from ..domain.meeting_doc import classify, pipeline, prompts, roles, types, windows, writer
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
    """What the handler needs. A plain object so the worker wires it once
    and the tests hand in fakes without a DI framework."""

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
    ) -> None:
        self.app_pool = app_pool
        self.transcripts_store = transcripts_store
        self.provider_for = provider_for
        self.audit_writer = audit_writer
        # Sprint 37 B-1: a candidate backend running beside the real one
        # on a sample of meetings, whose output is thrown away. This is
        # what a routing flip is rehearsed with.
        self.shadow_provider_for = shadow_provider_for
        self.shadow_percent = shadow_percent
        # Q4: whether the engine may ask the model to respell unknown names.
        self.entity_model_tier = entity_model_tier


async def handle_generate(deps: GenerationDeps, *, tenant_id: UUID, payload: dict) -> dict:
    """One generation, start to finish. Returns a result dict for the job
    row — ids and counts only, never content."""
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
        # Sprint 36: the items still open from the previous meeting, so
        # the extractor can say which of them this recording finishes.
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
    language = str(result.get("language") or "en")
    # Relative dates resolve against the day it was RECORDED (Q3): a note
    # made from an upload days later is not "today" in its own words.
    started = getattr(meeting, "started_at", None) if meeting else None
    meeting_date = (started or note.created_at or datetime.now(UTC)).date()

    # Q3: what the recording IS decides which kinds are extracted — before
    # extraction, so a podcast is never offered "decision" or "action".
    turns = windows.turns_from_result(result)
    built = windows.build_windows(turns)
    recording_type, recording_source = await _recording_type(
        provider,
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
    # 0057: the note gets its name before the long pass (Q6 order:
    # classify → name → extract) — one short call, never able to stop it.
    await _name_note(
        deps,
        tenant_id,
        note_id=note_id,
        generation_id=generation_id,
        requested_by=generation.requested_by,
        result=result,
        provider=provider,
        language=language,
    )

    # Q4: every name this recording may mean, and the workspace's glossary.
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
        # Q5: the verified facts no line cites — what the reader's
        # "Detailed" view lists under each topic, without another model call.
        await gen_repo.put_lines(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            generation_id=generation_id,
            rows=uncited_rows(document, family=family),
        )

        # Sprint 36: what the recording says was finished, and what it
        # offers for a person to accept. Neither is a line of the note.
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

    # The snapshot has done its job: the document is written and the
    # transcript still lives in asr-service. Keeping a second encrypted
    # copy of every meeting would be a data-retention decision nobody
    # made. The daily sweep catches the ones whose worker died first.
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
            # Q2 — counts only; never a line, a fact or a quote.
            "facts_kept": document.stats.get("facts_kept", 0),
            "facts_dropped_paraphrase": document.stats.get("facts_dropped_paraphrase", 0),
            "lines_kept": document.stats.get("lines_kept", 0),
            "lines_unsupported": sum(int(n) for n in unsupported.values()),
            "excluded_ms": document.stats.get("excluded_ms", 0),
            "speech_ms": document.stats.get("speech_ms", 0),
            "noise_overridden": document.stats.get("noise_overridden", 0),
            "summary_fallback": document.stats.get("summary_fallback"),
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
) -> None:
    """Replace the placeholder title with one taken from the meeting.

    The source is read before the model is asked, so a note that already
    has a person's title (or this job's, from an earlier attempt) costs no
    call — and read again under the row lock inside `note_title.apply`,
    so a rename made while the model was answering is the one that stays.
    """
    try:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            if await note_title.source_of(conn, note_id=note_id) != note_title.DEFAULT:
                return
        title = await note_title.suggest(provider, result, language=language)
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
    """Every written LINE is a row (Summary Engine v2, Q5): its text, what
    it cites, and the evidence of the first fact it cites. A line's
    placement follows what happened to its section: written when we wrote
    it, suggested when the author had been in there."""
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


# Line kinds as rows. A line written from one fact keeps that fact's kind,
# so the recipient page and the corrections routes read it as before.
_ROW_KIND: Final[dict[str, str]] = {
    "summary": "summary_sentence",
    "framing": "framing",
    "bullet": "topic_bullet",
    "date": "date",
}
# Least sure last: a line resting on several facts is as sure as its
# weakest one.
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
    """The row for one written line, or None for a line with no evidence
    (a heading). Pure — the tests build rows without a database."""
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
    """Rows for the verified facts no written line cites, each placed under
    the topic nearest to it in time (else the overview) as ``suggested``.
    Pure."""
    from ..domain.meeting_doc import render as render_rules
    from ..domain.meeting_doc import roles as role_rules

    cited = {i for s in document.sections for line in s.lines for i in line.fact_ids}
    topics = [s for s in document.sections if s.role == role_rules.TOPICS and s.facts]
    out: list[dict[str, Any]] = []
    for fact in document.facts:
        if fact.item_key in cited or fact.kind in ("completion", "judgement"):
            continue
        home = min(
            topics,
            key=lambda s, f=fact: min(abs(x.start_ms - f.start_ms) for x in s.facts),
            default=None,
        )
        line = render_rules.Line(fact.text, fact.kind, (fact.item_key,), fact.mentions)
        section_key = home.section_key if home else role_rules.OVERVIEW_KEY
        row = line_row(line, section_key, writer.SUGGESTED, {fact.item_key: fact}, family=family)
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
    """``(recording_type, source)``. The author's choice wins: a meeting
    type they set, or a specific template they picked (a client-call
    template is a client call). Only an `auto` note on the generic
    template is classified."""
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
    """``(known people, glossary terms)`` for one generation (Q4).

    People: the ASR's name candidates (calendar invitees sent at capture),
    the roster's names, the calendar event's attendees, and the glossary's
    persons. The glossary is read inside THIS tenant's connection — another
    workspace's spellings are never applied. A glossary that cannot be read
    costs the glossary tier, not the note."""
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
    """Record it on the note's meeting row. Never stops a generation: the
    generation's own stats are what the view reads."""
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
    """The other side's name, for the "Acme does" heading.

    Taken from the calendar event's title when there was one — it is the
    only place we have a name for the other party without asking.
    """
    if meeting is None:
        return ""
    title = str((meeting.calendar_context or {}).get("title") or "")
    # "Acme <> Us — Weekly" → "Acme"; anything without a separator is
    # not a party name and is left alone.
    for sep in ("<>", "—", "–", "|", "/"):
        if sep in title:
            head = title.split(sep)[0].strip()
            return head if 1 < len(head) <= 40 else ""
    return ""


async def _carried(conn: Any, *, note_id: UUID) -> list[tuple[str, str]]:
    """``[(item_key, text)]`` for the items still open from last time.

    Read from THIS note's own "Still open" block, not from the previous
    note. The visibility rule (ADR-0057) was applied once, when the items
    were carried in by the user's own request; the worker has no claims
    to re-apply it with, so it must not reach into another note at all.
    """
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
            # The block renders as "- [ ] Owner: task — due"; the key is
            # over the body, which is what `parts` gives back.
            by_key.setdefault(line_rules.key_of(parts.body), parts.body)

    out: list[tuple[str, str]] = []
    for row in rows[: carry_over.MAX_CARRIED]:
        key = str(row["item_key"])
        text = by_key.get(key)
        if text:
            out.append((key, text))
    return out


async def _apply_completions(conn: Any, *, note_id: UUID, completions: list[Any]) -> int:
    """Tick off what the recording says was done — with the words.

    `done_mentioned`, never `done_marked`: the distinction is who is
    claiming it. A person ticking a box is a person; this is the machine
    saying it heard so, and the quote is what lets a reader check.
    """
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
    """Judgement values are stored as SUGGESTIONS and nothing else.

    The engine never writes a `choice` or `date` field's metadata: a deal
    stage or a hire recommendation is a person's call, and a machine that
    sets one has made a decision nobody asked it to make.
    """
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

    The runner's probe runs BEFORE :func:`handle_generate`, so a backend
    that is down ("connection refused" on a dev Mac with Ollama stopped)
    exhausts the job's attempts without this module ever marking the row
    `running`, let alone `failed`. Left alone, the row stays `queued`
    forever: the client spins, the shared page is empty, and the live-
    generation index refuses every regenerate as "already being written".
    Only a live row is touched — a run that already wrote the note keeps
    its `complete`.
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
    """Drop the transcript snapshot this run was given.

    Row first, then the object: a row pointing at a deleted object is a
    generation that cannot explain itself, while an object no row points
    at is swept within the day.
    """
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
    """Run a candidate backend on this meeting and keep only the numbers.

    Nothing it produces is written: not a version, not an item, not a
    second snapshot. The output exists inside this function and is
    counted — how many facts survived verification against the same
    transcript, how long it took — and then dropped. That is the whole
    contract, and it is why a flip can be rehearsed on real meetings
    without processing anyone's words twice into storage.

    Sampled deterministically on the generation id, so a re-run of the
    same generation makes the same choice and a 5 % sample is 5 % of
    meetings rather than 5 % of attempts.
    """
    if not deps.shadow_provider_for or deps.shadow_percent <= 0:
        return
    if generation_id.int % 100 >= deps.shadow_percent:
        return

    backend = "unknown"
    started = time.monotonic()
    try:
        provider = await deps.shadow_provider_for(str(tenant_id))
        if provider is None:
            # Not eligible: this workspace has not acknowledged the
            # candidate's processor. Silence is correct — it is not an
            # error, and it must not become one per meeting.
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
    # What the live run found is the only yardstick we have here; the
    # gold-set harness is where quality is actually measured.
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
