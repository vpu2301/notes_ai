"""NoteContent, the ``note_versions.content_jsonb`` shape: ``extra='forbid'`` because the hash-chain commits to it;
``canonical_content_bytes`` is the RFC-8785 input to that chain.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NoteStatus(StrEnum):
    DRAFT = "draft"
    # Legacy (finalize retired, ADR-0051): kept so history decodes, never produced.
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
    """The heading, for a section the template does not name — one the
    engine made from the conversation ("Transfer strategy"). None means
    no heading: the block is read as the note itself. A template section
    is named by the template and leaves this unset."""
    title: str | None = Field(default=None, max_length=120)


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
    """RFC-8785 canonical JSON of the content (sorted keys, no whitespace, no ASCII escaping) for the hash-chain."""
    obj = content.model_dump(mode="json", exclude_none=False)
    # An absent title stays absent, not null, so versions hashed before titles existed re-canonicalise identically.
    for section in obj.get("sections", []):
        if section.get("title") is None:
            section.pop("title", None)
    return json.dumps(
        obj,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def rendered_text_from_content(content: NoteContent) -> str:
    """Plain-text projection for ``rendered_text`` + FTS: title, then each section heading + body."""
    parts: list[str] = []
    if content.title:
        parts.append(content.title)
    for s in content.sections:
        header = s.title or s.section_key
        body = s.text.strip()
        if body:
            parts.append(f"{header}\n{body}")
    return "\n\n".join(parts)
