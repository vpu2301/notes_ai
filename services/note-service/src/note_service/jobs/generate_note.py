"""The ``note.generate`` job (note-worker): a transcript becomes a note.

    load the note and the transcript snapshot (tenant context)
    → writer.write(...)                         # Sprint P1: one call per window + a merge
    → store the Markdown as written, and the items parsed from it, in order
    → stats, usage, build stamp

No branch, no flag, no fallback: a failed model call is retried by the job runner and
nothing else. Sprint R0 removed the old path (extract / verify / compose / lint).
Window outputs are cached in the transcript store beside the snapshot, so a worker that
dies mid-window does not pay for the finished windows again.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from db import tenant_connection
from models import throttle
from note_models import NoteStatus

from .. import build_info, generation_metrics
from ..domain import (
    checker,
    families,
    lines,
    model_params,
    note_apply,
    note_markdown,
    prompts,
    transcript,
    writer,
)
from ..domain import generation_repository as gen_repo
from ..domain import meetings_repository as meetings
from ..domain import note_instructions_repository as note_instructions_repo
from ..domain import notes_repository as repo
from ..domain import templates_repository as templates_repo
from ..domain.action_items import item_key, normalise_text

logger = logging.getLogger(__name__)

STEP_WRITE: Final = "write"
# The window outputs of a run in progress, beside its transcript snapshot.
PARTS_SUFFIX: Final = ".parts.json"


class GenerationDeps:
    """What the handler needs; a plain object the tests fill with fakes."""

    def __init__(
        self,
        *,
        app_pool: Any,
        transcripts_store: Any,
        provider_for: Any,
        build_sha: str = "",
        fallbacks: Any = None,
        note_instructions: bool = False,
        check_enabled: bool = False,
        settings_row: Any = None,
    ) -> None:
        self.app_pool = app_pool
        self.transcripts_store = transcripts_store
        # `(workspace_id) -> provider`: the workspace's routed writer.
        self.provider_for = provider_for
        # P3: the optional check call after writing (MDX_NOTE_CHECK).
        self.check_enabled = check_enabled
        # This process's code, and `() -> [{kind, backend, primary, reason}]`: routing
        # overrides that landed on their fallback. Both go into every run's provenance.
        self.build_sha = build_sha
        self.fallbacks = fallbacks
        # N1: read the stored note-writing text (MDX_NOTE_INSTRUCTIONS_ENABLED).
        self.note_instructions = note_instructions
        # N0: `tenant_id -> SettingsRow` as of the refresh before this run (writing style,
        # model parameters); None: the defaults.
        self.settings_row = settings_row


@dataclass(frozen=True, slots=True)
class _ModelSettings:
    """The workspace's model parameters for this run (N0), capped by the backend."""

    params: Any
    version: int

    @property
    def ref(self) -> dict[str, Any]:
        return {"version": self.version, "hash": model_params.canonical_hash(self.params)}


def model_settings(deps: Any, tenant_id: UUID, provider: Any) -> _ModelSettings:
    """The row as refreshed before this run, validated and capped by the writer's backend.
    No row (or no source): the defaults."""
    from ..domain import ai_settings

    source = getattr(deps, "settings_row", None)
    row = source(tenant_id) if source is not None else ai_settings.SettingsRow(tenant_id=tenant_id)
    params = model_params.effective(
        model_params.from_stored(
            row.model_params, tenant_id=tenant_id, version=row.model_params_version
        ),
        max_concurrency=getattr(provider, "max_concurrency", None),
    )
    return _ModelSettings(params, row.model_params_version)


async def _instructions_text(
    conn: Any, deps: Any, tenant_id: UUID, note_id: UUID, family: str | None
) -> str | None:
    """The stored note-writing text this run writes under: the note's own (N4), else its
    meeting type's, else the workspace's; None when off or nothing is stored. The text is
    passed as written — nothing compiles it (Sprint R0)."""
    if not getattr(deps, "note_instructions", False):
        return None
    own = await note_instructions_repo.fetch_note(conn, note_id=note_id)
    if own is not None and own.text.strip():
        return own.text
    scope = family if family in note_instructions_repo.TYPE_SCOPES else None
    scopes = (
        (note_instructions_repo.WORKSPACE, scope) if scope else (note_instructions_repo.WORKSPACE,)
    )
    rows = await note_instructions_repo.fetch_many(conn, tenant_id=tenant_id, scopes=scopes)
    for key in (scope, note_instructions_repo.WORKSPACE):
        row = rows.get(key) if key else None
        if row is not None and row.text.strip():
            return row.text
    return None


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
        meeting = await meetings.fetch(conn, note_id=note_id)
        meeting_type = getattr(meeting, "meeting_type", None)
        family = families.family_for_type(meeting_type)
        instructions = await _instructions_text(conn, deps, tenant_id, note_id, family.meeting_type)
        template_code = await _template_code(conn, note_id=note_id)
        await gen_repo.mark(
            conn, generation_id=generation_id, status=gen_repo.RUNNING, step=STEP_WRITE
        )
    template_name = writer.template_name_for(
        meeting_type,
        template_code,
        chosen=getattr(note, "template_source", None) == "user",
        note_template=getattr(note, "template", None),
    )
    started_at = getattr(meeting, "started_at", None) if meeting else None
    recording_date = started_at.date() if started_at else None

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
    settings = model_settings(deps, tenant_id, provider)
    language = str(result.get("language") or "en")
    template_override = await _template_override(deps, tenant_id, template_name, language)
    turns = transcript.turns_from_result(result)
    turns = transcript.prepare_turns(turns, language=language).turns
    if not turns:
        return await _fail(deps, tenant_id, generation_id, "empty_transcript")
    parts_key = generation.snapshot_key + PARTS_SUFFIX
    done_parts = await _cached_parts(deps, tenant_id, generation_id, parts_key)

    async def cache_parts(parts: list[str]) -> None:
        await _cache_parts(deps, tenant_id, generation_id, parts_key, parts)

    throttle.begin()
    try:
        written = await writer.write(
            turns,
            provider=provider,
            language=language,
            recording_date=recording_date,
            instruction_text=instructions,
            template_name=template_name,
            template_override=template_override,
            temperature=settings.params.temperature,
            max_output_tokens=settings.params.max_output_tokens,
            done_parts=done_parts,
            on_part=cache_parts,
        )
    except Exception:
        # The job runner retries; the finished windows wait in the cache.
        throttle.end()
        raise

    parsed = note_markdown.parse(written.text, turns)
    rows = item_rows(parsed, turns)
    stats = dict(written.stats)
    stats["items"] = len(rows)
    stats["sections"] = len(parsed.sections)
    stats["items_cited"] = sum(1 for r in rows if r["cites"])
    # P3: the optional check — a mark on the rows, never a change to them or the text.
    checked: checker.Checked | None = None
    if deps.check_enabled and rows:
        checked = await checker.check(rows, turns, provider=provider, language=language)
        stats["check"] = checked.stats
    stats["bad_cites"] = parsed.bad_cites
    stats["unstructured"] = parsed.unstructured
    # The template the note was written with: the one requested, or, under `auto`, the one
    # the model named on its second line (``template_requested`` keeps the request).
    stats["template_requested"] = template_name
    stats["template_chosen"] = parsed.template_name
    if template_name == writer.AUTO and parsed.template_name in writer.TEMPLATES:
        stats["template"] = parsed.template_name
    # 429s waited out under this run; the code that wrote it; the routing that answered.
    stats["throttle"] = throttle.end()
    stats["build"] = build_info.stamp(
        build_sha=getattr(deps, "build_sha", "") or None,
        prompt_version=prompts.PROMPT_VERSION,
        effective_version=prompts.PROMPT_VERSION,
        flags={},
    )
    stats["runtime"] = provenance(deps)
    stats["language"] = language
    # N0: the parameter set that wrote it — the pointer, never the values.
    stats["model_params"] = settings.ref
    stats["instructed"] = instructions is not None

    backend = written.backend or getattr(provider, "backend_name", None) or "unknown"
    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        stored = await gen_repo.replace_lines(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            generation_id=generation_id,
            rows=rows,
        )
        await gen_repo.supersede_previous(conn, note_id=note_id, keep=generation_id)
        if checked is not None:
            by_position = {int(r["position"]): str(r["item_key"]) for r in rows}
            await gen_repo.set_checks(
                conn,
                generation_id=generation_id,
                unsupported={
                    by_position[p]: reason
                    for p, reason in checked.unsupported.items()
                    if p in by_position
                },
            )
        # P3: the note itself — the writer's sections and title into a new version,
        # beside what the author typed. Nothing changed = no version.
        applied = await note_apply.apply(
            conn,
            note_id=note_id,
            parsed=parsed,
            requested_by=generation.requested_by,
            prompt_version=prompts.PROMPT_VERSION,
            generation_id=generation_id,
        )
        stats["section_hashes"] = applied.section_hashes
        stats["sections_written"] = len(applied.written_sections)
        stats["version_number"] = applied.version_number
        stats["title_written"] = applied.title_written
        await gen_repo.mark(
            conn,
            generation_id=generation_id,
            status=gen_repo.COMPLETE,
            step=None,
            backend=written.backend,
            model_id=written.model_id,
            text=written.text,
            stats=stats,
            finished=True,
        )
    for row in rows:
        generation_metrics.lines_stored.add(1, {"kind": str(row.get("kind") or "unknown")})

    # The transcript still lives in asr-service; a second copy is a retention decision
    # nobody made. The daily sweep catches snapshots whose worker died first.
    await _discard_snapshot(deps, tenant_id, generation_id, parts_key=parts_key)

    generation_metrics.generations.add(
        1,
        {
            "outcome": "complete",
            "backend": backend,
            "instructed": "yes" if instructions else "no",
        },
    )
    logger.info(
        "note_generate.done",
        extra={
            # Counts only; never a line or a quote.
            "items_stored": stored,
            "text_chars": len(written.text),
            "words": stats.get("words"),
            "windows": stats.get("windows"),
            "calls": stats.get("calls"),
            "bad_cites": parsed.bad_cites,
            "unstructured": parsed.unstructured,
            "merge_failed": stats.get("merge_failed"),
            "prompt_version": prompts.PROMPT_VERSION,
            "backend": backend,
            "instructed": instructions is not None,
            "temperature": settings.params.temperature,
            "max_concurrency": settings.params.max_concurrency,
        },
    )
    return {"items_stored": stored, "text_chars": len(written.text)}


# The words a cited turn carries with the row: a short turn whole, a long one cut around
# the cited moment (``excerpt``), so the popover and the judge see what the bullet rests on.
TURN_TEXT_WHOLE = 1_200
TURN_TEXT_REACH = 700


def cited_turn(turn: Any, times_ms: list[int]) -> dict[str, Any]:
    text = str(turn.text)
    start, end = int(turn.start_ms), int(turn.end_ms)
    out: dict[str, Any] = {
        "turn": int(turn.number),
        "start_ms": start,
        "end_ms": end,
        "speaker": getattr(turn, "display_name", None) or turn.speaker_name or turn.speaker_label,
    }
    if len(text) <= TURN_TEXT_WHOLE:
        out["text"] = text
        return out
    inside = [t for t in times_ms if start <= t <= end]
    at = inside[0] if inside else start
    share = (at - start) / (end - start) if end > start else 0.0
    centre = int(len(text) * min(1.0, max(0.0, share)))
    lo, hi = max(0, centre - TURN_TEXT_REACH), min(len(text), centre + TURN_TEXT_REACH)
    # Cut at word boundaries.
    if lo > 0 and text.find(" ", lo) != -1:
        lo = text.find(" ", lo) + 1
    if hi < len(text):
        space = text.rfind(" ", 0, hi)
        hi = space if space > lo else hi
    out["text"] = ("… " if lo > 0 else "") + text[lo:hi].strip() + (" …" if hi < len(text) else "")
    out["excerpt"] = True
    out["at_ms"] = at
    return out


def item_rows(parsed: note_markdown.ParsedNote, turns: list[Any]) -> list[dict[str, Any]]:
    """One row per item, in the Markdown's order: the text as written, the turn it cites
    as its evidence (quote, span, speaker), its kind and position. Pure."""
    by_number = {int(t.number): t for t in turns}
    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    for position, (section, item) in enumerate(parsed.items):
        key = lines.key_of(item.text) if item.text.strip() else ""
        if not key or key in keys:
            # Two lines with the same key (the same words, or an "Owner: task — due" line
            # whose owner and due differ): both rows stay, the second under a key that
            # includes its position. Never a dropped line.
            key = item_key(normalise_text(f"{position}:{item.text}"))
        keys.add(key)
        cited = [by_number[n] for n in item.cites if n in by_number]
        first = cited[0] if cited else None
        # P3: every cited turn travels with the row, so a client lists them without the
        # transcript. A long turn (a monologue of minutes) is cut to the words around the
        # cited moment, placed by proportion since the turn has no word timings.
        payload = {"turns": [cited_turn(t, item.times_ms) for t in cited[:8]]}
        rows.append(
            {
                "item_key": key,
                "kind": item.kind,
                "section_key": section.key[:64],
                "text": item.text,
                "quote": (first.text if first is not None else "")[:2000],
                "start_ms": int(first.start_ms) if first is not None else 0,
                "end_ms": int(first.end_ms) if first is not None else 0,
                "speaker_label": first.speaker_label if first is not None else None,
                "speaker_name": first.speaker_name if first is not None else None,
                "placement": "written",
                "audience": "all",
                "explicit": True,
                "confidence": 1.0,
                "flags": ["cite_nearest"] if item.cite_nearest else [],
                "cites": [f"turn:{n}" for n in item.cites][:16],
                "position": position,
                "table_row": item.table_row,
                "cite_nearest": item.cite_nearest,
                "provenance": None,
                "payload": payload if cited else None,
            }
        )
    return rows


async def _template_override(
    deps: GenerationDeps, tenant_id: UUID, name: str, language: str
) -> str | None:
    """The workspace's own text for the template (P2), in the note's language, else None."""
    try:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            row = await templates_repo.fetch(
                conn, tenant_id=tenant_id, name=name, language=prompts.language_of(language)
            )
    except Exception:  # noqa: BLE001 — an unreadable override costs the override, not the note
        logger.warning("note_generate.template_override_unavailable", exc_info=True)
        return None
    return row.markdown if row is not None else None


async def _template_code(conn: Any, *, note_id: UUID) -> str | None:
    """The code of the note's template (``meeting_notes_de``), or None."""
    return await conn.fetchval(
        "SELECT t.code FROM notes n JOIN templates t ON t.id = n.template_id WHERE n.id = $1",
        note_id,
    )


async def _cached_parts(
    deps: GenerationDeps, tenant_id: UUID, generation_id: UUID, key: str
) -> list[str]:
    """Window outputs an earlier attempt of this generation finished; [] when none."""
    try:
        raw = await deps.transcripts_store.get(
            key=key, tenant_id=tenant_id, aad=generation_id.bytes
        )
        parts = json.loads(raw)
        return [str(p) for p in parts] if isinstance(parts, list) else []
    except Exception:  # noqa: BLE001 — no cache is the normal case
        return []


async def _cache_parts(
    deps: GenerationDeps, tenant_id: UUID, generation_id: UUID, key: str, parts: list[str]
) -> None:
    try:
        await deps.transcripts_store.put(
            key=key,
            plaintext=json.dumps(parts).encode("utf-8"),
            tenant_id=tenant_id,
            aad=generation_id.bytes,
        )
    except Exception:  # noqa: BLE001 — a cache miss costs a window, never the note
        logger.warning("note_generate.parts_not_cached", exc_info=True)


def provenance(deps: Any) -> dict[str, Any]:
    """What produced this run: this worker's code and every routing override that landed
    on its fallback. Names and versions only."""
    fallbacks = getattr(deps, "fallbacks", None)
    try:
        landed = list(fallbacks()) if fallbacks is not None else []
    except Exception:  # noqa: BLE001 — provenance never stops a note
        landed = []
    return {
        "run_kind": "generation",
        "build_sha": getattr(deps, "build_sha", "") or None,
        "prompt_version": prompts.PROMPT_VERSION,
        "fallbacks": landed,
    }


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


async def _discard_snapshot(
    deps: GenerationDeps, tenant_id: UUID, generation_id: UUID, *, parts_key: str | None = None
) -> None:
    """Drop the run's transcript snapshot and its window cache: row first, then the
    objects (an orphan object is swept within the day; a dangling row is not)."""
    try:
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            key = await gen_repo.clear_snapshot(conn, generation_id=generation_id)
        if key:
            await deps.transcripts_store.delete(key=key)
            await deps.transcripts_store.delete(key=parts_key or key + PARTS_SUFFIX)
    except Exception:  # noqa: BLE001 — the note is written; this is tidying
        logger.warning("note_generate.snapshot_not_discarded", exc_info=True)
