"""Default visibility of a note (W3, ADR-0071; W5).

A team workspace shares by default (members edit, viewers comment); a
personal workspace and the families marked sensitive
(`families.Family.default_visibility`: one-on-one, interview, memo)
stay private. W5 applied the same rule to the notes that existed before W3
(`scripts/ops/backfill_workspace_visibility.py`) and to a note that moves;
:func:`default_for_note` is that rule on a stored note, and
``public.default_visibility_for_note`` (0078) is its SQL twin — keep them equal.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from fastapi import HTTPException, status

from . import sharing_policy
from .access import VISIBILITY_PRIVATE, VISIBILITY_WORKSPACE
from .families import (
    FAMILIES,
    RECORDING_TYPES,
    detected_value,
    family_for_recording_type,
    family_for_template,
    family_for_type,
)

_PRIVATE_FAMILIES = [f for f in FAMILIES if f.default_visibility == VISIBILITY_PRIVATE]
# The three ways a stored note says it is person-centred: the author's meeting type,
# the detected recording type, the template's code prefix.
SENSITIVE_MEETING_TYPES: Final = frozenset(f.meeting_type for f in _PRIVATE_FAMILIES)
SENSITIVE_DETECTED: Final = frozenset(
    detected_value(r)
    for r in RECORDING_TYPES
    if family_for_recording_type(r).default_visibility == VISIBILITY_PRIVATE
)
SENSITIVE_TEMPLATE_PREFIXES: Final = tuple(sorted(f.template_prefix for f in _PRIVATE_FAMILIES))


def default_for(
    tenant_kind: str, *, meeting_type: str | None = None, template_code: str | None = None
) -> str:
    if tenant_kind != "team":
        return VISIBILITY_PRIVATE
    family = family_for_type(meeting_type) if meeting_type else family_for_template(template_code)
    return family.default_visibility


async def default_for_new_note(
    conn: Any, *, tenant_id: UUID, template_id: UUID | None, meeting_type: str | None = None
) -> str:
    """The default for a note about to be created in the connection's workspace."""
    kind = await sharing_policy.tenant_kind(conn, tenant_id=tenant_id)
    if kind != "team":
        return VISIBILITY_PRIVATE
    code = None
    if not meeting_type and template_id is not None:
        code = await conn.fetchval("SELECT code FROM templates WHERE id = $1", template_id)
    return default_for(kind, meeting_type=meeting_type, template_code=code)


def is_sensitive(
    *, meeting_type: str | None, meeting_type_detected: str | None, template_code: str | None
) -> bool:
    """Whether a stored note belongs to a person-centred family (any of the three signals)."""
    return (
        meeting_type in SENSITIVE_MEETING_TYPES
        or meeting_type_detected in SENSITIVE_DETECTED
        or (template_code or "").lower().startswith(SENSITIVE_TEMPLATE_PREFIXES)
    )


def default_for_note(
    tenant_kind: str,
    *,
    meeting_type: str | None,
    meeting_type_detected: str | None,
    template_code: str | None,
) -> str:
    """The default for a note that already exists (backfill, move); SQL twin in 0078."""
    if tenant_kind != "team":
        return VISIBILITY_PRIVATE
    sensitive = is_sensitive(
        meeting_type=meeting_type,
        meeting_type_detected=meeting_type_detected,
        template_code=template_code,
    )
    return VISIBILITY_PRIVATE if sensitive else VISIBILITY_WORKSPACE


async def require_allowed(conn: Any, *, tenant_id: UUID, visibility: str) -> None:
    """409 ``personal_workspace``: nothing in a personal workspace is workspace-visible."""
    if (
        visibility == VISIBILITY_WORKSPACE
        and await sharing_policy.tenant_kind(conn, tenant_id=tenant_id) == "personal"
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "personal_workspace",
                "detail": "a personal workspace has nobody to share with",
            },
        )
