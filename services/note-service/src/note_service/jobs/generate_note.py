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
from typing import Any
from uuid import UUID

from db import tenant_connection
from note_models import NoteStatus

from .. import generation_metrics
from ..domain import carry_over, note_title
from ..domain import generation_repository as gen_repo
from ..domain import meetings_repository as meetings
from ..domain import notes_repository as repo
from ..domain.meeting_doc import pipeline, prompts, roles, types, writer
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
        family = types.family_for_template(template_code)
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
    meeting_date = (note.created_at or datetime.now(UTC)).date()

    # 0057: the note gets its name first — one short call, seconds rather
    # than the minutes the document takes, and never able to stop it.
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

    document = await pipeline.run(
        result,
        provider=provider,
        role_by_key=template_roles,
        language=language,
        meeting_date=meeting_date,
        family=family,
        carried=carried,
        counterpart=counterpart,
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
    logger.info(
        "note_generate.done",
        extra={
            "windows": document.windows_total,
            "failed": document.windows_failed,
            "sections_written": written,
            "sections_suggested": suggested,
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
) -> None:
    """A fact's placement follows what happened to its section: written
    when we wrote it, suggested when the author had been in there."""
    rows = []
    for section in sections:
        placement = (
            writer.WRITTEN
            if section.section_key in outcome.written_sections
            or section.section_key in outcome.section_hashes
            else writer.SUGGESTED
        )
        rows.extend((fact, section.section_key, placement) for fact in section.facts)
    if rows:
        await gen_repo.put_items(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            generation_id=generation_id,
            facts=rows,
            audience_of=lambda f: (
                "internal"
                if family is not None and types.is_internal_kind(family, f.kind)
                else "all"
            ),
        )


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
