"""Fixing a line without detaching it from its history.

    POST  /v1/notes/{id}/items/{item_key}/dismiss   {reason}
    POST  /v1/notes/{id}/items/{item_key}/restore
    PATCH /v1/notes/{id}/items/by-key/{item_key}    {owner_label?, due_text?}

A line's ``item_key`` hashes its body without marker, owner and due phrase
(`domain/lines.py`), so fixing owner or date keeps the key and everything
attached to it; changing what the line says changes the key. Every route
writes a real note version through the normal append path.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteContent, NoteStatus

from .. import audit_kinds, generation_metrics
from ..deps import get_state, requires
from ..domain import access, lines
from ..domain import generation_repository as gen_repo
from ..domain import glossary_repository as glossary_repo
from ..domain import notes_repository as repo
from ..domain.action_items import ACTION_SECTION_KEYS
from ..domain.conflicts import OptimisticLockMismatchError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

# How far back `restore` looks for the line it is bringing back.
RESTORE_LOOKBACK_VERSIONS = 25

DismissReason = Literal[
    "not_said",
    "not_a_decision",
    "not_a_task",
    "wrong_owner",
    "wrong_date",
    "duplicate",
    "not_relevant",
]


class DismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: DismissReason


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class PatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    # Absent = leave alone. Explicit null = clear.
    owner_label: str | None = Field(default=None, max_length=lines.MAX_OWNER)
    due_text: str | None = Field(default=None, max_length=120)
    clear_owner: bool = False
    clear_due: bool = False
    # A name the engine respelled: `accepted` keeps the line, `rejected` puts back `surface`.
    action: Literal["correction_accepted", "correction_rejected"] | None = None
    reason: Literal["wrong_name"] | None = None
    surface: str | None = Field(default=None, min_length=1, max_length=80)
    canonical: str | None = Field(default=None, min_length=1, max_length=80)
    # Where the engine got the spelling. Logged, never branched on.
    source: str | None = Field(default=None, max_length=32, pattern=r"^[a-z_]+$")


class CorrectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    item_key: str
    section_key: str
    version_number: int
    """The line as it now reads, so the client need not re-render it."""
    line: str | None


# ── Shared machinery ────────────────────────────────────────────────


def _locate(content: NoteContent, item_key: str) -> tuple[int, lines.Line] | None:
    """Which section holds the line, and the line; the first section wins."""
    for index, section in enumerate(content.sections):
        found = lines.find(section.text, item_key)
        if found is not None:
            return index, found
    return None


def _kind_of(section_key: str) -> str:
    """The item kind for the correction log."""
    return "action" if section_key in ACTION_SECTION_KEYS else "line"


def _with_section(content: NoteContent, index: int, text: str) -> NoteContent:
    sections = list(content.sections)
    sections[index] = sections[index].model_copy(update={"text": text})
    return content.model_copy(update={"sections": sections})


async def _write(
    conn: object,
    *,
    note_id: UUID,
    expected_version: int,
    content: NoteContent,
    claims: Claims,
) -> int:
    try:
        _, version_number = await repo.append_version(
            conn,  # type: ignore[arg-type]
            note_id=note_id,
            expected_version=expected_version,
            new_content=content,
            created_by=claims.sub,
            diff_jsonb={"source": "correction"},
        )
    except OptimisticLockMismatchError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "optimistic_lock_mismatch",
                "detail": "the note changed since you loaded it",
                "current_version": exc.current_version,
            },
        ) from None
    return version_number


async def _editable(conn: object, *, note_id: UUID, claims: Claims) -> object:
    note = access.require_manage(
        await repo.lock_note_for_update(conn, note_id=note_id),
        claims,  # type: ignore[arg-type]
    )
    if note.status != NoteStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "note_cancelled", "detail": "the note is no longer a draft"},
        )
    return note


async def _audit(claims: Claims, kind: str, note_id: UUID, payload: dict[str, object]) -> None:
    """Keys and closed vocabularies only — never the line's text."""
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload=payload,
        severity=Severity.INFO,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.post("/{note_id}/items/{item_key}/dismiss", response_model=CorrectionResponse)
async def dismiss_item(
    note_id: UUID,
    item_key: str,
    body: DismissRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> CorrectionResponse:
    """Take a line out of the note, and say why.

    The reason is the valuable part: it is a closed vocabulary, it carries
    no text, and it is what tells us next week which kinds of line we
    should stop writing. Idempotent — dismissing a line that is already
    gone answers 200 rather than 404, because the author's intent has been
    honoured either way.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = await _editable(conn, note_id=note_id, claims=claims)
        version = await repo.fetch_version(conn, version_id=note.current_version_id)  # type: ignore[attr-defined]
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note has no version")
        located = _locate(version.content, item_key)
        if located is None:
            already = item_key in await glossary_repo.dismissed_keys(conn, note_id=note_id)
            if already:
                return CorrectionResponse(
                    id=note_id,
                    item_key=item_key,
                    section_key="",
                    version_number=note.current_version_number,  # type: ignore[attr-defined]
                    line=None,
                )
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")

        index, line = located
        section = version.content.sections[index]
        text = lines.replace_line(section.text, item_key, None)
        if text is None:  # located it a moment ago; cannot happen
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")
        content = _with_section(version.content, index, text)
        version_number = await _write(
            conn,
            note_id=note_id,
            expected_version=body.expected_version,
            content=content,
            claims=claims,
        )
        kind = _kind_of(section.section_key)
        await glossary_repo.record_correction(
            conn,
            tenant_id=claims.tid,
            note_id=note_id,
            item_key=item_key,
            kind=kind,
            action="dismiss",
            reason=body.reason,
            flags_at_time=[],
            actor_sub=claims.sub,
        )

    await _audit(
        claims,
        audit_kinds.NOTE_ITEM_DISMISSED,
        note_id,
        {"item_key": item_key, "kind": kind, "reason": body.reason},
    )
    return CorrectionResponse(
        id=note_id,
        item_key=item_key,
        section_key=section.section_key,
        version_number=version_number,
        line=None,
    )


@router.post("/{note_id}/items/{item_key}/restore", response_model=CorrectionResponse)
async def restore_item(
    note_id: UUID,
    item_key: str,
    body: RestoreRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> CorrectionResponse:
    """Put a dismissed line back, exactly as it read.

    The text comes from the version history rather than from a column: the
    correction log holds no note text on purpose, and the hash chain
    already has every word. The line returns to the bottom of the section
    it came from — guessing its old position would be a second edit the
    author did not ask for.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = await _editable(conn, note_id=note_id, claims=claims)
        current = await repo.fetch_version(conn, version_id=note.current_version_id)  # type: ignore[attr-defined]
        if current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note has no version")
        if _locate(current.content, item_key) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "already_present", "detail": "that line is already in the note"},
            )

        found = await _find_in_history(
            conn,
            note_id=note_id,
            item_key=item_key,
            before=note.current_version_number,  # type: ignore[attr-defined]
        )
        if found is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail="that line is not in this note's history",
            )
        section_key, raw = found
        index = next(
            (i for i, s in enumerate(current.content.sections) if s.section_key == section_key),
            None,
        )
        if index is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "section_gone",
                    "detail": "the section that line came from is no longer in the note",
                },
            )
        text = lines.append_line(current.content.sections[index].text, raw)
        content = _with_section(current.content, index, text)
        version_number = await _write(
            conn,
            note_id=note_id,
            expected_version=body.expected_version,
            content=content,
            claims=claims,
        )
        kind = _kind_of(section_key)
        await glossary_repo.record_correction(
            conn,
            tenant_id=claims.tid,
            note_id=note_id,
            item_key=item_key,
            kind=kind,
            action="restore",
            reason=None,
            flags_at_time=[],
            actor_sub=claims.sub,
        )

    await _audit(
        claims,
        audit_kinds.NOTE_ITEM_RESTORED,
        note_id,
        {"item_key": item_key, "kind": kind},
    )
    return CorrectionResponse(
        id=note_id,
        item_key=item_key,
        section_key=section_key,
        version_number=version_number,
        line=raw,
    )


async def _find_in_history(
    conn: object, *, note_id: UUID, item_key: str, before: int
) -> tuple[str, str] | None:
    """``(section_key, the line as it read)`` from the most recent version that still had it."""
    for number in range(before - 1, max(0, before - 1 - RESTORE_LOOKBACK_VERSIONS), -1):
        version = await repo.fetch_version_by_number(
            conn,  # type: ignore[arg-type]
            note_id=note_id,
            version_number=number,
        )
        if version is None:
            continue
        located = _locate(version.content, item_key)
        if located is not None:
            index, line = located
            return version.content.sections[index].section_key, line.raw
    return None


@router.patch("/{note_id}/items/by-key/{item_key}", response_model=CorrectionResponse)
async def patch_item(
    note_id: UUID,
    item_key: str,
    body: PatchItemRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> CorrectionResponse:
    """Fix a line's owner or its date, in place.

    The body is not touched, so the key does not change and everything
    attached to it survives: the recipient's confirmation on the shared
    page, this note's correction history, and the evidence chip once there
    is one. That is the whole reason this route exists rather than telling
    the author to edit the text.

    Addressed under ``/items/by-key/`` because ``PATCH /items/{item_id}``
    was already taken by the Sprint 20 status route, which addresses items
    by their row UUID.
    """
    if body.action is not None:
        return await _name_correction(note_id, item_key, body, claims)
    if not any((body.owner_label, body.due_text, body.clear_owner, body.clear_due)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "nothing_to_change", "detail": "send an owner or a due date"},
        )

    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = await _editable(conn, note_id=note_id, claims=claims)
        version = await repo.fetch_version(conn, version_id=note.current_version_id)  # type: ignore[attr-defined]
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note has no version")
        located = _locate(version.content, item_key)
        if located is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")
        index, line = located
        section = version.content.sections[index]

        # Same grammar the key came from, so unchanged parts come back exactly.
        parsed = lines.parts(line.content)
        owner = None if body.clear_owner else (body.owner_label or parsed.owner)
        due = None if body.clear_due else (body.due_text or parsed.due_text)
        rewritten = lines.render_item(
            marker=line.marker, owner=owner, body=parsed.body, due_text=due
        )

        # The key must survive, or everything attached would detach: refuse BEFORE writing.
        if lines.key_of(lines.strip_marker(rewritten)[1]) != item_key:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "key_would_change",
                    "detail": "that change would rewrite the line, not its owner or date",
                },
            )
        if rewritten == line.raw:
            return CorrectionResponse(
                id=note_id,
                item_key=item_key,
                section_key=section.section_key,
                version_number=note.current_version_number,  # type: ignore[attr-defined]
                line=line.raw,
            )

        text = lines.replace_line(section.text, item_key, rewritten)
        if text is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")
        content = _with_section(version.content, index, text)
        version_number = await _write(
            conn,
            note_id=note_id,
            expected_version=body.expected_version,
            content=content,
            claims=claims,
        )

        changed = "owner" if (body.owner_label or body.clear_owner) else "due"
        kind = _kind_of(section.section_key)
        await glossary_repo.record_correction(
            conn,
            tenant_id=claims.tid,
            note_id=note_id,
            item_key=item_key,
            kind=kind,
            action="owner_changed" if changed == "owner" else "due_changed",
            reason=None,
            flags_at_time=[],
            actor_sub=claims.sub,
        )

    await _audit(
        claims,
        audit_kinds.NOTE_ITEM_EDITED,
        note_id,
        {"item_key": item_key, "kind": kind, "field": changed},
    )
    return CorrectionResponse(
        id=note_id,
        item_key=item_key,
        section_key=section.section_key,
        version_number=version_number,
        line=rewritten,
    )


async def _keys_respelled(conn: object, *, note_id: UUID, body: PatchItemRequest) -> list[str]:
    """Every line of the current generation the engine gave this respelling."""
    rows = await gen_repo.items_for_note(conn, note_id=note_id, current_only=True)  # type: ignore[arg-type]
    keys: list[str] = []
    for row in rows:
        try:
            raw = row["corrections"]
        except (KeyError, IndexError):
            continue
        corrections = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if any(
            isinstance(c, dict)
            and c.get("surface") == body.surface
            and c.get("canonical") == body.canonical
            for c in corrections
        ):
            keys.append(str(row["item_key"]))
    return keys


async def _name_correction(
    note_id: UUID, item_key: str, body: PatchItemRequest, claims: Claims
) -> CorrectionResponse:
    """Accept or reject a name the engine respelled. Rejecting rewrites the line (the
    key changes; the response carries the new one); accepting changes nothing in the note."""
    if not body.surface or not body.canonical:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "correction_incomplete", "detail": "send surface and canonical"},
        )
    rejected = body.action == "correction_rejected"
    tag = glossary_repo.name_review_tag(body.surface, body.canonical)
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = await _editable(conn, note_id=note_id, claims=claims)
        version = await repo.fetch_version(conn, version_id=note.current_version_id)  # type: ignore[attr-defined]
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note has no version")
        version_number = note.current_version_number  # type: ignore[attr-defined]
        # The decision covers every line the respelling was applied to.
        keys = [item_key] + [
            k for k in await _keys_respelled(conn, note_id=note_id, body=body) if k != item_key
        ]
        touched: list[tuple[str, str, str]] = []  # (old key, section key, line)
        if rejected:
            pattern = re.compile(rf"(?<!\w){re.escape(body.canonical)}(?!\w)")
            content = version.content
            for key in keys:
                located = _locate(content, key)
                if located is None or not pattern.search(located[1].raw):
                    continue
                index, line = located
                written = pattern.sub(body.surface, line.raw)
                text = lines.replace_line(content.sections[index].text, key, written)
                if text is None:
                    continue
                content = _with_section(content, index, text)
                touched.append((key, content.sections[index].section_key, written))
            if not touched:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "correction_not_in_line", "detail": "the name is not there"},
                )
            version_number = await _write(
                conn,
                note_id=note_id,
                expected_version=body.expected_version,
                content=content,
                claims=claims,
            )
        else:
            # Accepting writes nothing, so a line that has moved on is no reason to refuse.
            located = _locate(version.content, item_key)
            if located is None:
                touched.append((item_key, "", ""))
            else:
                index, line = located
                touched.append((item_key, version.content.sections[index].section_key, line.raw))
        for key, section_key, _ in touched:
            await glossary_repo.record_correction(
                conn,
                tenant_id=claims.tid,
                note_id=note_id,
                item_key=key,
                kind=_kind_of(section_key),
                action=str(body.action),
                reason="wrong_name" if rejected else None,
                flags_at_time=["entity_corrected", tag],
                actor_sub=claims.sub,
            )
    # The line the client asked about when it was changed, else the first.
    first = next((t for t in touched if t[0] == item_key), touched[0])
    _, section_key, written_line = first
    new_key = lines.key_of(lines.strip_marker(written_line)[1]) if rejected else item_key
    outcome = "rejected" if rejected else "accepted"
    await _audit(
        claims,
        audit_kinds.NOTE_CORRECTION_REJECTED if rejected else audit_kinds.NOTE_CORRECTION_ACCEPTED,
        note_id,
        {"item_key": item_key, "source": body.source or "unknown"},
    )
    generation_metrics.corrections_counter.add(1, {"action": outcome})
    return CorrectionResponse(
        id=note_id,
        item_key=new_key,
        section_key=section_key,
        version_number=version_number,
        line=written_line or None,
    )
