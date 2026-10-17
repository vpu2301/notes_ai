"""Default visibility of a new note (W3, ADR-0071).

A team workspace shares by default (members edit, viewers comment); a
personal workspace and the families marked sensitive
(`meeting_doc.types.Family.default_visibility`: one-on-one, interview, memo)
stay private. Existing notes are untouched — their visibility is the author's
to change.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from . import sharing_policy
from .access import VISIBILITY_PRIVATE
from .meeting_doc.types import family_for_template, family_for_type


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
