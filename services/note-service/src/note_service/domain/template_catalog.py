"""The active templates a note may be created with, and the one taken when the request
names none: the general meeting-notes template, else any general one, else whatever is
active. Sprint R0 removed the transcript keyword matcher; nothing scores a transcript.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import asyncpg

from template_models import TemplateDefinition

logger = logging.getLogger(__name__)

DEFAULT_PREFIX: Final = "meeting_notes"
GENERAL_CATEGORY: Final = "general"


@dataclass(frozen=True, slots=True)
class TemplateCandidate:
    id: UUID
    code: str
    name: str
    category: str
    schema_version: int
    definition: TemplateDefinition
    is_system: bool


async def load_candidates(conn: asyncpg.Connection, *, language: str) -> list[TemplateCandidate]:
    """Active templates (system + this tenant's, via RLS) with parsed schema.

    Rows whose schema fails to parse are skipped with a warning — one
    malformed tenant template must not break note creation.
    """
    rows = await conn.fetch(
        """
        SELECT id, code, name, category, schema_version, schema_jsonb, is_system
        FROM templates
        WHERE language = $1 AND status = 'active'
        ORDER BY is_system, name, id
        """,
        language,
    )
    out: list[TemplateCandidate] = []
    # The dev seed is not idempotent for SYSTEM templates (tenant_id IS
    # NULL escapes the (tenant_id, code, schema_version) UNIQUE — NULLs
    # compare distinct), so identical rows pile up. Keep the first id per
    # (code, schema_version) — rows are byte-identical duplicates.
    seen: set[tuple[str, int]] = set()
    for row in rows:
        dedupe_key = (str(row["code"]), int(row["schema_version"]))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        raw = row["schema_jsonb"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        try:
            definition = TemplateDefinition.model_validate(raw)
        except Exception:  # noqa: BLE001 — tolerate one bad row
            logger.warning("template_catalog.schema_invalid", extra={"template_id": str(row["id"])})
            continue
        out.append(
            TemplateCandidate(
                id=row["id"],
                code=str(row["code"]),
                name=row["name"],
                category=row["category"],
                schema_version=int(row["schema_version"]),
                definition=definition,
                is_system=bool(row["is_system"]),
            )
        )
    return out


def default_template(candidates: list[TemplateCandidate]) -> TemplateCandidate | None:
    """The meeting-notes template, then any general template, then whatever exists;
    ``None`` only when the catalogue is empty."""
    if not candidates:
        return None
    return next(
        (c for c in candidates if c.code.startswith(DEFAULT_PREFIX)),
        next((c for c in candidates if c.category == GENERAL_CATEGORY), candidates[0]),
    )
