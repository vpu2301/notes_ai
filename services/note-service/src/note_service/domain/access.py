"""Who may see, comment on, edit, share, and delete a note, in one place (W3, ADR-0071).

Effective access is the highest of: the author team (manage), a per-note
collaborator role (view/comment/edit), the workspace grant of a
``workspace``-visible note (member → edit, viewer → comment, guest → nothing),
tenant_admin (manage) and auditor oversight (view). A note the caller may not
see is a 404, never a 403; a note they see but may not change is a 403
``insufficient_role`` naming the level that was required.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from fastapi import HTTPException, status

from auth import Claims
from note_models import ReadPurpose

from ..collaboration_metrics import access_refused
from .notes_repository import NoteRow

VISIBILITY_PRIVATE: Final = "private"
VISIBILITY_WORKSPACE: Final = "workspace"
VISIBILITIES: Final = (VISIBILITY_PRIVATE, VISIBILITY_WORKSPACE)

# Ordered lowest → highest; the index is the rank.
LEVELS: Final = ("view", "comment", "edit", "manage")
COLLABORATOR_ROLES: Final = ("view", "comment", "edit")

# Roles that read across the whole tenant regardless of visibility.
_OVERSIGHT_ROLES: Final = frozenset({"tenant_admin", "auditor"})
_ADMIN_ROLES: Final = frozenset({"tenant_admin"})


def _rank(level: str | None) -> int:
    return LEVELS.index(level) + 1 if level in LEVELS else 0


def _highest(*levels: str | None) -> str | None:
    best = max(levels, key=_rank, default=None)
    return best if _rank(best) else None


def sees_whole_tenant(claims: Claims) -> bool:
    """tenant_admin / auditor read across the tenant regardless of visibility."""
    return bool(_OVERSIGHT_ROLES & set(claims.roles))


def is_guest(claims: Claims) -> bool:
    """A guest membership's token: it reaches only notes it was given (W3)."""
    return "guest" in claims.roles and not (
        {"member", "viewer", "tenant_admin"} & set(claims.roles)
    )


def is_author_team(note: NoteRow, user_sub: UUID) -> bool:
    return user_sub == note.primary_author_id or user_sub in note.co_author_ids


def collaborator_role(note: NoteRow, user_sub: UUID) -> str | None:
    """The per-note grant (`note_collaborators`, loaded with the note), or None."""
    return note.collaborators.get(user_sub)


def workspace_grant(note: NoteRow, claims: Claims) -> str | None:
    """What visibility ``workspace`` gives this person: member → edit, viewer → comment, guest → none."""
    if note.visibility != VISIBILITY_WORKSPACE or is_guest(claims):
        return None
    roles = set(claims.roles)
    if "member" in roles:
        return "edit"
    if "viewer" in roles:
        return "comment"
    return None


def level(note: NoteRow, claims: Claims) -> str | None:
    """'manage' | 'edit' | 'comment' | 'view', or None when the note is not theirs to see."""
    return level_of(
        primary_author_id=note.primary_author_id,
        co_author_ids=note.co_author_ids,
        visibility=note.visibility,
        collaborator=collaborator_role(note, claims.sub),
        claims=claims,
    )


def level_of(
    *,
    primary_author_id: UUID,
    co_author_ids: list[UUID],
    visibility: str,
    collaborator: str | None,
    claims: Claims,
) -> str | None:
    """The matrix itself, on plain fields (search hits carry no NoteRow)."""
    if claims.sub == primary_author_id or claims.sub in co_author_ids:
        return "manage"
    if _ADMIN_ROLES & set(claims.roles):
        return "manage"
    grant = None
    if visibility == VISIBILITY_WORKSPACE and not is_guest(claims):
        roles = set(claims.roles)
        grant = "edit" if "member" in roles else "comment" if "viewer" in roles else None
    oversight = "view" if sees_whole_tenant(claims) else None
    return _highest(collaborator, grant, oversight)


def reads_as_collaborator(note: NoteRow, claims: Claims) -> bool:
    """The author team, plus anyone the note was shared with.

    These readers never declare a purpose: the note is theirs to read.
    Everyone else — a workspace member reading a ``workspace``-visible
    note, a tenant_admin or auditor reading across the tenant — is an
    oversight read and must say why (``?purpose=``).
    """
    return is_author_team(note, claims.sub) or collaborator_role(note, claims.sub) is not None


def require_read_purpose(note: NoteRow, claims: Claims, purpose: ReadPurpose | None) -> bool:
    """Returns whether the caller reads as a collaborator.

    Raises 422 ``missing-read-purpose`` when an oversight reader omits
    ``?purpose=``. Called after :func:`require_view`, so a note the caller
    may not see at all is already a 404 by the time this runs.
    """
    collaborator = reads_as_collaborator(note, claims)
    if not collaborator and purpose is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "https://errors.notes-ai/missing-read-purpose",
                "title": "Read purpose required",
                "detail": "Non-author reads must include ?purpose=<value>",
                "allowed": [p.value for p in ReadPurpose],
            },
        )
    return collaborator


def can_view(note: NoteRow, claims: Claims) -> bool:
    return level(note, claims) is not None


def can_comment(note: NoteRow, claims: Claims) -> bool:
    return _rank(level(note, claims)) >= _rank("comment")


def can_edit(note: NoteRow, claims: Claims) -> bool:
    return _rank(level(note, claims)) >= _rank("edit")


def can_manage(note: NoteRow, claims: Claims) -> bool:
    """Change visibility, share, create or revoke links."""
    return level(note, claims) == "manage"


def can_delete(note: NoteRow, claims: Claims) -> bool:
    """Only the person whose note it is, or an admin. A co-author edits;
    they do not get to make the note disappear for the author."""
    return claims.sub == note.primary_author_id or bool(_ADMIN_ROLES & set(claims.roles))


def can_read_transcript(note: NoteRow, claims: Claims) -> bool:
    """Transcript and audio: edit or above, or any reader once the author turned it on.
    Nobody while a moved note's media is still on its way (W5 ``media_state``)."""
    if note.media_state != "ready":
        return False
    found = level(note, claims)
    return _rank(found) >= _rank("edit") or (found is not None and note.transcript_shared)


def require_view(note: NoteRow | None, claims: Claims) -> NoteRow:
    if note is None or not can_view(note, claims):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")
    return note


def _require_level(note: NoteRow | None, claims: Claims, required: str, detail: str) -> NoteRow:
    note = require_view(note, claims)
    if _rank(level(note, claims)) < _rank(required):
        access_refused.add(1, {"level_required": required})
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "insufficient_role", "required": required, "detail": detail},
        )
    return note


def require_comment(note: NoteRow | None, claims: Claims) -> NoteRow:
    return _require_level(note, claims, "comment", "you can view this note but not comment on it")


def require_edit(note: NoteRow | None, claims: Claims) -> NoteRow:
    return _require_level(note, claims, "edit", "you can see this note but not change it")


def require_manage(note: NoteRow | None, claims: Claims) -> NoteRow:
    return _require_level(note, claims, "manage", "only the note's authors can change who sees it")


def require_transcript(note: NoteRow | None, claims: Claims) -> NoteRow:
    """Transcript or audio of a note: 404 (not 403) when it is not shared with this reader."""
    note = require_view(note, claims)
    if not can_read_transcript(note, claims):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="transcript not found")
    return note


def require_delete(note: NoteRow | None, claims: Claims) -> NoteRow:
    note = require_view(note, claims)
    if not can_delete(note, claims):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="only the note's author can delete it",
        )
    return note
