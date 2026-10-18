"""Where a moved note went (W5).

A move leaves a stub in the source workspace (`note_relocations`, written only by
``public.move_note_to_workspace``). An old deep link or code then answers
404 ``note_moved {to_workspace_id}`` — but only to someone who could have seen the
note here: its author team, a collaborator, a tenant_admin/auditor, or (when it was
workspace-visible) a member or viewer. Everyone else gets the plain 404, so the stub
is no oracle for a private note's existence.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from auth import Claims

from . import access


@dataclass(slots=True)
class Relocation:
    note_id: UUID
    to_tenant_id: UUID
    old_code: str
    new_code: str
    was_workspace_visible: bool
    author_team: list[UUID]
    collaborator_subs: list[UUID]


_COLUMNS = (
    "note_id, to_tenant_id, old_code, new_code, was_workspace_visible,"
    " author_team, collaborator_subs"
)


def _row(r: asyncpg.Record) -> Relocation:
    return Relocation(
        note_id=r["note_id"],
        to_tenant_id=r["to_tenant_id"],
        old_code=r["old_code"],
        new_code=r["new_code"],
        was_workspace_visible=bool(r["was_workspace_visible"]),
        author_team=list(r["author_team"] or []),
        collaborator_subs=list(r["collaborator_subs"] or []),
    )


def may_be_told(stub: Relocation, claims: Claims) -> bool:
    """Whether this person could have seen the note before it moved."""
    if claims.sub in stub.author_team or claims.sub in stub.collaborator_subs:
        return True
    if access.sees_whole_tenant(claims):
        return True
    if stub.was_workspace_visible and not access.is_guest(claims):
        return bool({"member", "viewer"} & set(claims.roles))
    return False


def moved_error(stub: Relocation) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={
            "code": "note_moved",
            "detail": "this note was moved to another workspace",
            "to_workspace_id": str(stub.to_tenant_id),
        },
    )


async def fetch_by_note(conn: asyncpg.Connection, *, note_id: UUID) -> Relocation | None:
    row = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM note_relocations WHERE note_id = $1", note_id
    )
    return _row(row) if row else None


async def raise_if_moved(conn: asyncpg.Connection, *, note_id: UUID, claims: Claims) -> None:
    """Call when a note id was not found here: 404 ``note_moved`` if it left and they may know."""
    stub = await fetch_by_note(conn, note_id=note_id)
    if stub is not None and may_be_told(stub, claims):
        raise moved_error(stub)


async def raise_if_code_moved(conn: asyncpg.Connection, *, code: str, claims: Claims) -> None:
    """The same for an old code typed into search (``N-0412``)."""
    rows = await conn.fetch(
        f"SELECT {_COLUMNS} FROM note_relocations WHERE old_code = $1 ORDER BY moved_at DESC",
        code,
    )
    for row in rows:
        stub = _row(row)
        if may_be_told(stub, claims):
            raise moved_error(stub)
