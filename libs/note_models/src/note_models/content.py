"""NoteContent — the JSON shape stored in ``note_versions.content_jsonb``.

Design notes:

- ``extra='forbid'`` everywhere. The shape is the contract the
  hash-chain commits to; unknown keys silently dropped would
  invalidate chain hashes.
- ``NoteSection.field_specific_metadata`` is an open dict — this is
  the documented escape hatch for typed fields (sprint-13) and note
  review (sprint-15) to attach typed metadata without re-versioning
  every template. The allowed keys per ``field_type`` are documented
  in ``docs/architecture/notes.md``.
- ``canonical_content_bytes`` produces the RFC-8785 JCS serialisation
  used as input to the version hash-chain. The model JSON dump is
  sorted by Pydantic; we re-sort defensively here.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NoteStatus(StrEnum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    AMENDED = "amended"
    CANCELLED = "cancelled"


class NoteAmendmentType(StrEnum):
    CORRECTION = "correction"
    ADDITION = "addition"
    CLARIFICATION = "clarification"


class NoteSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_key: str = Field(min_length=1, max_length=64)
    text: str = ""
    transcript_segment_ids: list[UUID] = Field(default_factory=list)
    field_specific_metadata: dict[str, Any] = Field(default_factory=dict)


class NoteContent(BaseModel):
    """The full content_jsonb body for one version."""

    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    template_schema_version: int = Field(ge=1)
    title: str = ""
    sections: list[NoteSection] = Field(default_factory=list)

    @field_validator("sections")
    @classmethod
    def _unique_section_keys(cls, v: list[NoteSection]) -> list[NoteSection]:
        keys = [s.section_key for s in v]
        if len(keys) != len(set(keys)):
            raise ValueError("section_key values must be unique within a note")
        return v


def canonical_content_bytes(content: NoteContent) -> bytes:
    """RFC-8785 canonical JSON of the content. Used by the hash-chain.

    Stable across Python versions because:
    - keys sorted alphabetically;
    - no whitespace;
    - UTF-8 with no non-ASCII escape;
    - no Pydantic round-trip drift (model_dump → json with sort_keys).
    """
    obj = content.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        obj,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def rendered_text_from_content(content: NoteContent) -> str:
    """Plain-text projection used for ``rendered_text`` + FTS.

    Concatenates section title + body, separated by double newlines.
    Order follows ``content.sections`` (template-order, by convention).
    """
    parts: list[str] = []
    if content.title:
        parts.append(content.title)
    for s in content.sections:
        header = s.section_key
        body = s.text.strip()
        if body:
            parts.append(f"{header}\n{body}")
    return "\n\n".join(parts)
