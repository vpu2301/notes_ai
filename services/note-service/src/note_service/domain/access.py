"""Who may see, share, and delete a note (0016).

The rules in one place, so the read routers, the search filter and the
sharing endpoints cannot drift apart:

* **Author team** — primary author and co-authors — can do everything.
* **Shared-with** members can read, whatever the visibility.
* **Workspace** visibility lets every member read (the pre-0016 rule).
* **tenant_admin / auditor** can read anything in the tenant (they
  still declare a read purpose, as before) and admins can also manage
  and delete on the author's behalf.
* Anyone else gets a 404 — a private note is not something whose
  existence should be confirmable by guessing ids.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from fastapi import HTTPException, status

from auth import Claims

from .notes_repository import NoteRow

VISIBILITY_PRIVATE: Final = "private"
VISIBILITY_WORKSPACE: Final = "workspace"
VISIBILITIES: Final = (VISIBILITY_PRIVATE, VISIBILITY_WORKSPACE)

# Roles that read across the whole tenant regardless of visibility.
_OVERSIGHT_ROLES: Final = frozenset({"tenant_admin", "auditor"})
_ADMIN_ROLES: Final = frozenset({"tenant_admin"})


def sees_whole_tenant(claims: Claims) -> bool:
    """tenant_admin / auditor read across the tenant regardless of visibility."""
    return bool(_OVERSIGHT_ROLES & set(claims.roles))


def is_author_team(note: NoteRow, user_sub: UUID) -> bool:
    return user_sub == note.primary_author_id or user_sub in note.co_author_ids


def can_view(note: NoteRow, claims: Claims) -> bool:
    if is_author_team(note, claims.sub) or claims.sub in note.shared_with_ids:
        return True
    if note.visibility == VISIBILITY_WORKSPACE:
        return True
    return sees_whole_tenant(claims)


def can_manage(note: NoteRow, claims: Claims) -> bool:
    """Change visibility, share, create or revoke links."""
    return is_author_team(note, claims.sub) or bool(_ADMIN_ROLES & set(claims.roles))


def can_delete(note: NoteRow, claims: Claims) -> bool:
    """Only the person whose note it is, or an admin. A co-author edits;
    they do not get to make the note disappear for the author."""
    return claims.sub == note.primary_author_id or bool(_ADMIN_ROLES & set(claims.roles))


def require_view(note: NoteRow | None, claims: Claims) -> NoteRow:
    if note is None or not can_view(note, claims):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")
    return note


def require_manage(note: NoteRow | None, claims: Claims) -> NoteRow:
    note = require_view(note, claims)
    if not can_manage(note, claims):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="only the note's authors can change who sees it",
        )
    return note


def require_delete(note: NoteRow | None, claims: Claims) -> NoteRow:
    note = require_view(note, claims)
    if not can_delete(note, claims):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="only the note's author can delete it",
        )
    return note
