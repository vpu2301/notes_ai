"""Move and copy a note between workspaces (W5).

A **move** keeps the note id: ``public.move_note_to_workspace`` (0078) re-parents the
note and everything that hangs off it in one transaction, re-checks every
permission itself and queues the ``note.rehome_media`` job that brings the objects
after it (`jobs/rehome_media.py`). A **copy** is a new note in the target made from the current
version — no recording, no comments, links or collaborators.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException, status

from db import tenant_connection
from note_models import NoteContent

from . import code_sequence, sharing_policy
from . import notes_repository as repo
from .visibility import default_for_note

# Queued by `move_note_to_workspace` itself (0078), in the move's transaction.
REHOME_JOB_KIND: Final = "note.rehome_media"
# Roles that may create notes in the destination; the client filters its switcher list by it.
ELIGIBLE_ROLES: Final = ("owner", "admin", "member")

# The function's refusals → HTTP. The message is the code (0078 raises it that way).
_REFUSALS: Final[dict[str, tuple[int, str]]] = {
    "note_not_found": (status.HTTP_404_NOT_FOUND, "note not found"),
    "same_workspace": (status.HTTP_409_CONFLICT, "the note is already in this workspace"),
    "insufficient_role": (
        status.HTTP_403_FORBIDDEN,
        "only the note's authors or a workspace admin can move it",
    ),
    "not_a_member": (
        status.HTTP_403_FORBIDDEN,
        "you cannot create notes in that workspace",
    ),
    "target_unavailable": (status.HTTP_409_CONFLICT, "that workspace is not active"),
    "media_shared": (
        status.HTTP_409_CONFLICT,
        "another note here uses the same recording",
    ),
    "generation_in_progress": (
        status.HTTP_409_CONFLICT,
        "the note is being written; try again in a minute",
    ),
    "media_in_progress": (
        status.HTTP_409_CONFLICT,
        "the recording is still being transcribed; try again when it is done",
    ),
    "custom_template": (
        status.HTTP_409_CONFLICT,
        "the note uses this workspace's own template, which the other workspace cannot read",
    ),
}


class RefusedError(HTTPException):
    def __init__(self, code: str, **extra: str) -> None:
        http_status, detail = _REFUSALS[code]
        super().__init__(http_status, detail={"code": code, "detail": detail, **extra})
        self.code = code


@dataclass(slots=True)
class Moved:
    note_id: UUID
    from_tenant_id: UUID
    to_tenant_id: UUID
    code: str
    visibility: str
    media_state: str
    job_id: UUID | None
    audio_ids: list[UUID]


async def blockers(conn: asyncpg.Connection, *, note: repo.NoteRow) -> list[str]:
    """What would refuse a move right now, so the sheet can say so before the user picks."""
    row = await conn.fetchrow(
        """
        WITH job AS (
            SELECT COALESCE(n.source_asr_job_id,
                            (SELECT m.asr_job_id FROM note_meetings m WHERE m.note_id = n.id)) AS id
              FROM notes n WHERE n.id = $1
        )
        SELECT
          EXISTS (SELECT 1 FROM notes o, job WHERE job.id IS NOT NULL AND o.id <> $1
                     AND (o.source_asr_job_id = job.id OR o.id IN
                          (SELECT m.note_id FROM note_meetings m WHERE m.asr_job_id = job.id)))
              AS media_shared,
          EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'note.generate'
                     AND j.payload->>'note_id' = $1::text
                     AND j.status IN ('queued', 'running', 'waiting_on_model'))
              AS generation_in_progress,
          EXISTS (SELECT 1 FROM transcription_jobs t, job WHERE t.id = job.id
                     AND (t.status IN ('queued', 'running')
                          OR t.diarization_status IN ('queued', 'running')))
              AS media_in_progress,
          EXISTS (SELECT 1 FROM notes n JOIN templates t ON t.id = n.template_id
                   WHERE n.id = $1 AND t.tenant_id IS NOT NULL)
              AS custom_template
        """,
        note.id,
    )
    names = ("media_shared", "generation_in_progress", "media_in_progress", "custom_template")
    found = [name for name in names if row and row[name]]
    if note.media_state == "rehoming" and "media_in_progress" not in found:
        found.append("media_in_progress")  # the last move's media is still on its way
    return found


async def move(
    *,
    app_pool: asyncpg.Pool,
    note: repo.NoteRow,
    actor: UUID,
    to_tenant_id: UUID,
) -> Moved:
    """Re-parent the note. The function decides everything; this only draws the code."""
    async with tenant_connection(app_pool, note.tenant_id) as conn:
        may_create = await conn.fetchval(
            "SELECT public.can_create_in_workspace($1, $2)", to_tenant_id, actor
        )
    new_code = ""
    if may_create and to_tenant_id != note.tenant_id:
        # The target's own sequence; an unused code after a refusal is an accepted gap.
        async with tenant_connection(app_pool, to_tenant_id) as target:
            new_code = await code_sequence.next_code(target, tenant_id=to_tenant_id)

    async with tenant_connection(app_pool, note.tenant_id) as conn:
        try:
            row = await conn.fetchrow(
                "SELECT * FROM public.move_note_to_workspace($1, $2, $3, $4)",
                note.id,
                to_tenant_id,
                actor,
                new_code,
            )
        except asyncpg.PostgresError as exc:
            # plpgsql RAISE maps to several asyncpg classes by ERRCODE; the message is the code.
            code = getattr(exc, "message", "") or ""
            if code in _REFUSALS:
                raise RefusedError(code) from exc
            raise
    assert row is not None  # noqa: S101 — the function always returns one row
    # RLS hides the moved row from the source connection now; read it where it lives.
    async with tenant_connection(app_pool, to_tenant_id) as target:
        state = await target.fetchrow(
            "SELECT visibility::text AS visibility, media_state FROM notes WHERE id = $1", note.id
        )
    assert state is not None  # noqa: S101
    return Moved(
        note_id=note.id,
        from_tenant_id=note.tenant_id,
        to_tenant_id=to_tenant_id,
        code=new_code,
        visibility=str(state["visibility"]),
        media_state=str(state["media_state"]),
        job_id=row["job_id"],
        audio_ids=list(row["audio_ids"] or []),
    )


def _without_citations(content: NoteContent) -> NoteContent:
    """Evidence points into a transcript the copy does not have."""
    return content.model_copy(
        update={
            "sections": [
                s.model_copy(update={"transcript_segment_ids": []}) for s in content.sections
            ]
        }
    )


async def copy(
    *,
    app_pool: asyncpg.Pool,
    note: repo.NoteRow,
    actor: UUID,
    to_tenant_id: UUID,
) -> tuple[UUID, str]:
    """A new note in the target from the source's current version. Returns (id, code)."""
    if to_tenant_id == note.tenant_id:
        raise RefusedError("same_workspace")
    async with tenant_connection(app_pool, note.tenant_id) as conn:
        if not await conn.fetchval(
            "SELECT public.can_create_in_workspace($1, $2)", to_tenant_id, actor
        ):
            raise RefusedError("not_a_member")
        if await conn.fetchval(
            "SELECT t.tenant_id IS NOT NULL FROM notes n JOIN templates t ON t.id = n.template_id"
            " WHERE n.id = $1",
            note.id,
        ):
            raise RefusedError("custom_template")
        version = await repo.fetch_version(conn, version_id=note.current_version_id)
        source = await conn.fetchrow(
            """
            SELECT n.template_schema_version, t.code AS template_code,
                   m.meeting_type, m.meeting_type_detected, m.started_at
              FROM notes n
              LEFT JOIN templates t ON t.id = n.template_id
              LEFT JOIN note_meetings m ON m.note_id = n.id
             WHERE n.id = $1
            """,
            note.id,
        )
    if version is None or source is None:
        raise RefusedError("note_not_found")
    content = _without_citations(version.content)

    async with tenant_connection(app_pool, to_tenant_id) as target:
        kind = await sharing_policy.tenant_kind(target, tenant_id=to_tenant_id)
        if kind == "team" and note.visibility == "private" and note.visibility_source == "author":
            # The author's lock travels with their document.
            visibility, visibility_source = "private", "author"
        else:
            visibility = default_for_note(
                kind,
                meeting_type=source["meeting_type"],
                meeting_type_detected=source["meeting_type_detected"],
                template_code=source["template_code"],
            )
            visibility_source = "default"
        code = await code_sequence.next_code(target, tenant_id=to_tenant_id)
        new_id, _version_id = await repo.create_note_with_v1(
            target,
            tenant_id=to_tenant_id,
            code=code,
            primary_author_id=actor,
            co_author_ids=[],
            template_id=content.template_id,
            template_schema_version=int(source["template_schema_version"] or 1),
            source_session_id=None,
            content=content,
            visibility=visibility,
            visibility_source=visibility_source,
            copied_from_note_id=note.id,
            copied_from_tenant_id=note.tenant_id,
            version_metadata={"copied_from_version_id": str(note.current_version_id)},
        )
        if source["meeting_type"] is not None:
            await target.execute(
                """
                INSERT INTO note_meetings (note_id, tenant_id, created_by, state, client_capture_id,
                                           meeting_type, meeting_type_detected, started_at)
                VALUES ($1, $2, $3, 'ready', $4, $5, $6, $7)
                """,
                new_id,
                to_tenant_id,
                actor,
                uuid4(),
                source["meeting_type"],
                source["meeting_type_detected"],
                source["started_at"],
            )
    return new_id, code
