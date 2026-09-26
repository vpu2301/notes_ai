"""Series, carry-over and the client version (Sprint 36).

    GET  /v1/notes/{id}/carried                  what is still open from last time
    POST /v1/notes/{id}/carried/{item_key}       tick it, re-open it, drop it
    POST /v1/notes/{id}/meeting/previous         "this continues…"
    GET  /v1/notes/{id}/client-version           exactly what a client would see
    GET  /v1/notes/{id}/client-version/check     what to look at before sharing

The carried routes read **another note**, so every one of them goes
through the visibility rule (ADR-0057): a previous note is used only when
the author of the new note may view it. `domain/series_service.py` holds
that rule; the routes never reach past it.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import ReadPurpose

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import access, carry_over, client_view, lines, series_service
from ..domain import generation_repository as gen_repo
from ..domain import meetings_repository as meetings
from ..domain import notes_repository as repo
from ..domain.meeting_doc import types as meeting_types
from .notes import _resolve_section_names

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

CarriedState = Literal["open", "done_marked", "dropped"]

# What each flag means to a person about to send this to a client.
# Plain language, because a checklist that says `owner_inferred` is a
# checklist nobody reads.
FLAG_WARNINGS: dict[str, str] = {
    "owner_inferred": "Some owners were worked out rather than stated — check them.",
    "no_owner": "Some tasks have nobody on them.",
    "due_unparsed": "A date was said but not understood; it is kept as text.",
    "number_unverified": "A number could not be confirmed against the recording.",
    "low_asr_confidence": "Some lines come from audio that was hard to hear.",
    "speaker_unnamed": "Someone who took a task on has not been named.",
    "side_unknown": "Some tasks are not clearly yours or the client's.",
}


class CarriedItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str
    text: str
    owner_label: str | None
    due_text: str | None
    state: str
    """Only on `done_mentioned`: the words that say it was done."""
    done_quote: str | None = None
    done_speaker: str | None = None


class CarriedView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CarriedItemView]
    """The meeting these came from — so the client can link to it."""
    from_note_id: UUID | None
    from_note_code: str | None
    from_date: date | None


class CarriedStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: CarriedState


class PreviousNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID


class ClientSectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_key: str
    role: str
    name: str
    text: str


class ClientVersionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    """False for a 1:1 or an interview debrief: those have no client."""
    reason: str | None
    title: str
    sections: list[ClientSectionView]
    hidden_lines: int
    hidden_sections: list[str]


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str
    count: int


class ClientVersionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    warnings: list[ChecklistItem]
    """Warnings, never blockers: ADR-0051 put no gates on a note's state,
    and this is the author's judgement to make."""
    is_empty: bool


async def _audit(claims: Claims, kind: str, note_id: UUID, payload: dict[str, object]) -> None:
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


# ── Carry-over ──────────────────────────────────────────────────────


@router.get("/{note_id}/carried", response_model=CarriedView)
async def list_carried(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: ReadPurpose | None = None,
) -> CarriedView:
    """What is still open from the previous meeting in this series."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        access.require_read_purpose(note, claims, purpose)
        items, previous = await series_service.carried_view(conn, note_id=note_id, claims=claims)
    return CarriedView(
        items=[
            CarriedItemView(
                item_key=i.item_key,
                text=i.text,
                owner_label=i.owner_label,
                due_text=i.due_text,
                state=i.state,
                done_quote=i.done_quote,
                done_speaker=i.done_speaker,
            )
            for i in items
        ],
        from_note_id=previous.id if previous else None,
        from_note_code=previous.code if previous else None,
        from_date=previous.updated_at.date() if previous else None,
    )


@router.post("/{note_id}/carried/{item_key}", response_model=CarriedItemView)
async def set_carried_state(
    note_id: UUID,
    item_key: str,
    body: CarriedStateRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> CarriedItemView:
    """Tick a carried item off, re-open it, or drop it.

    A tick by hand is `done_marked` and never `done_mentioned`: the
    latter means the recording said so, with a quote, and only the
    engine may claim that.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        ok = await meetings.set_carried_state(
            conn, note_id=note_id, item_key=item_key, state=body.state
        )
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="carried item not found")
        items, _ = await series_service.carried_view(conn, note_id=note_id, claims=claims)
    await _audit(
        claims,
        audit_kinds.NOTE_CARRIED_ITEM_UPDATED,
        note_id,
        {"item_key": item_key, "state": body.state},
    )
    found = next((i for i in items if i.item_key == item_key), None)
    return CarriedItemView(
        item_key=item_key,
        text=found.text if found else "",
        owner_label=found.owner_label if found else None,
        due_text=found.due_text if found else None,
        state=body.state,
    )


@router.post("/{note_id}/meeting/previous", response_model=CarriedView)
async def set_previous_note(
    note_id: UUID,
    body: PreviousNoteRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> CarriedView:
    """ "This continues…" — link this meeting to an earlier one by hand.

    Restricted to notes this author may view, like every other path into
    another note's content.
    """
    state = get_state()
    if body.note_id == note_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "same_note", "detail": "a meeting cannot continue itself"},
        )
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        previous = await repo.fetch_note(conn, note_id=body.note_id)
        if previous is None or not access.can_view(previous, claims):
            # A 404 rather than a 403: whether a note the author cannot
            # see exists is not something to confirm by guessing ids.
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")

        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note has no version")
        content = await series_service.carry_into(
            conn,
            claims=claims,
            note_id=note_id,
            previous=previous,
            content=version.content,
        )
        if content != version.content:
            note = access.require_manage(
                await repo.lock_note_for_update(conn, note_id=note_id), claims
            )
            await repo.append_version(
                conn,
                note_id=note_id,
                expected_version=note.current_version_number,
                new_content=content,
                created_by=claims.sub,
                diff_jsonb={"source": "carry_over"},
            )
        items, resolved = await series_service.carried_view(conn, note_id=note_id, claims=claims)
    await _audit(
        claims,
        audit_kinds.NOTE_SERIES_LINKED,
        note_id,
        {"source": "manual", "carried": len(items)},
    )
    return CarriedView(
        items=[
            CarriedItemView(
                item_key=i.item_key,
                text=i.text,
                owner_label=i.owner_label,
                due_text=i.due_text,
                state=i.state,
            )
            for i in items
        ],
        from_note_id=resolved.id if resolved else None,
        from_note_code=resolved.code if resolved else None,
        from_date=resolved.updated_at.date() if resolved else None,
    )


# ── The client version ──────────────────────────────────────────────


@router.get("/{note_id}/client-version", response_model=ClientVersionView)
async def client_version(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
    purpose: ReadPurpose | None = None,
) -> ClientVersionView:
    """Exactly what an external surface would render.

    The preview and the shared page call the same pure builder, so "what
    I saw in the preview" and "what the client got" cannot differ.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        access.require_read_purpose(note, claims, purpose)
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note has no version")
        names = await _resolve_section_names(conn, content=version.content)
        code = await repo.template_code_for(conn, note_id=note_id)
        internal_keys = frozenset(await gen_repo.internal_item_keys(conn, note_id=note_id))

    family = meeting_types.family_for_template(code)
    if not meeting_types.supports_client_version(family):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "not_available_for_type",
                "detail": ("a one-to-one and an interview debrief have no client version"),
            },
        )
    document = client_view.build(
        version.content, family=family, section_names=names, internal_keys=internal_keys
    )
    return ClientVersionView(
        available=True,
        reason=None,
        title=document.title,
        sections=[
            ClientSectionView(section_key=s.section_key, role=s.role, name=s.name, text=s.text)
            for s in document.sections
        ],
        hidden_lines=document.hidden_lines,
        hidden_sections=list(document.hidden_sections),
    )


@router.get("/{note_id}/client-version/check", response_model=ClientVersionCheck)
async def client_version_check(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> ClientVersionCheck:
    """What is worth a second look before this goes to a client.

    Warnings, not blockers. The author decides — a gate on sharing would
    re-introduce exactly the lifecycle ADR-0051 removed.
    """
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note has no version")
        names = await _resolve_section_names(conn, content=version.content)
        code = await repo.template_code_for(conn, note_id=note_id)
        internal_keys = frozenset(await gen_repo.internal_item_keys(conn, note_id=note_id))
        flags = await gen_repo.flag_counts(conn, note_id=note_id)
        suggested = await gen_repo.suggested_count(conn, note_id=note_id)

    family = meeting_types.family_for_template(code)
    if not meeting_types.supports_client_version(family):
        return ClientVersionCheck(available=False, warnings=[], is_empty=True)

    document = client_view.build(
        version.content, family=family, section_names=names, internal_keys=internal_keys
    )
    warnings: list[ChecklistItem] = []

    # Sprint 36: what the engine was not sure about. These are the lines
    # a person should look at before they go to a client — an owner we
    # inferred, a number we could not confirm, words that were hard to
    # hear, a task neither side clearly owns.
    for flag, detail in FLAG_WARNINGS.items():
        count = flags.get(flag, 0)
        if count:
            warnings.append(ChecklistItem(code=flag, detail=detail, count=count))
    if suggested:
        warnings.append(
            ChecklistItem(
                code="suggestions_unresolved",
                detail="The engine offered lines you have not accepted or dismissed.",
                count=suggested,
            )
        )

    unnamed = _unnamed_owners(version.content)
    if unnamed:
        warnings.append(
            ChecklistItem(
                code="speaker_unnamed",
                detail="Some tasks are owned by an unnamed speaker.",
                count=unnamed,
            )
        )
    if document.hidden_lines:
        warnings.append(
            ChecklistItem(
                code="internal_lines_hidden",
                detail="Lines you marked internal are not in the client version.",
                count=document.hidden_lines,
            )
        )
    if document.hidden_sections:
        warnings.append(
            ChecklistItem(
                code="sections_hidden",
                detail="Whole sections stay internal (your notes, the transcript).",
                count=len(document.hidden_sections),
            )
        )
    return ClientVersionCheck(available=True, warnings=warnings, is_empty=document.is_empty)


def _unnamed_owners(content) -> int:  # noqa: ANN001
    """Tasks owned by "Speaker 2" — a client cannot act on those."""
    total = 0
    for section in content.sections:
        if meeting_types.role_of(section.section_key) != meeting_types.ACTION_ITEMS:
            continue
        for line in lines.split_section(section.text or ""):
            owner = lines.parts(line.content).owner or ""
            if owner.lower().startswith("speaker ") or owner.lower() == "unknown speaker":
                total += 1
    return total


__all__ = ["router", "carry_over"]
