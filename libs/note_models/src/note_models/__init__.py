"""Strict Pydantic shapes for ``notes`` + ``note_versions``; ``canonical_content_bytes()`` feeds the hash-chain."""

from note_models.content import (
    NoteAmendmentType,
    NoteContent,
    NoteSection,
    NoteStatus,
    canonical_content_bytes,
    rendered_text_from_content,
)
from note_models.diff import (
    DiffResponse,
    DiffSectionEntry,
    DiffSegment,
    MetadataDiff,
)
from note_models.field_metadata import (
    META_MODEL_BY_FIELD_TYPE,
    ChoiceMeta,
    DateMeta,
    FieldMeta,
    FieldMetadataError,
    MetadataSource,
    MultiChoiceMeta,
    NumericMeta,
    parse_field_metadata,
    validate_field_metadata,
)
from note_models.read_purpose import ReadPurpose

__all__ = [
    "META_MODEL_BY_FIELD_TYPE",
    "ChoiceMeta",
    "DateMeta",
    "DiffResponse",
    "DiffSectionEntry",
    "DiffSegment",
    "FieldMeta",
    "FieldMetadataError",
    "MetadataDiff",
    "MetadataSource",
    "MultiChoiceMeta",
    "NumericMeta",
    "ReadPurpose",
    "NoteAmendmentType",
    "NoteContent",
    "NoteSection",
    "NoteStatus",
    "canonical_content_bytes",
    "parse_field_metadata",
    "rendered_text_from_content",
    "validate_field_metadata",
]
