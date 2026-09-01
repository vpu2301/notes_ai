"""libs/template_models — Pydantic models for the templates JSONB schema.

The schema is a public contract: notes persist ``template_id`` +
``template_version`` at finalization, and typed fields (sprint 13)
read field types. Changing the shape requires either a cosmetic edit
(in-place, schema_version bump) or a structural edit (new row,
parent_template_id set) — see :func:`classify_edit`.
"""

from __future__ import annotations

from .schema import (
    ASR_PROMPT_MAX_TOKENS,
    CHOICE_FIELD_TYPES,
    FIELD_TYPES,
    ChoiceOption,
    EditKind,
    FieldType,
    TemplateDefinition,
    TemplateMetadata,
    TemplateSection,
    classify_edit,
)

__all__ = [
    "ASR_PROMPT_MAX_TOKENS",
    "CHOICE_FIELD_TYPES",
    "ChoiceOption",
    "EditKind",
    "FIELD_TYPES",
    "FieldType",
    "TemplateDefinition",
    "TemplateMetadata",
    "TemplateSection",
    "classify_edit",
]
