"""Templates JSONB schema: ``extra="forbid"`` everywhere, additive bumps serialize old templates byte-identically.

``classify_edit`` (ADR-0016): cosmetic edits UPDATE in place + bump ``schema_version``; structural ones INSERT a new row.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

# Whisper's ``initial_prompt`` limit; runtime gates by an approximate character count (no tiktoken on the hot path).
ASR_PROMPT_MAX_TOKENS: Final = 224
_APPROX_CHARS_PER_TOKEN: Final = 4
_ASR_PROMPT_MAX_CHARS_APPROX: Final = ASR_PROMPT_MAX_TOKENS * _APPROX_CHARS_PER_TOKEN


class FieldType(StrEnum):
    """Sprint-06 shipped the first kinds; sprint-13 adds the two choice
    kinds. Adding enum members is additive to the *model*; changing an
    existing section's ``field_type`` remains a STRUCTURAL edit
    (ADR-0016)."""

    FREE_TEXT = "free_text"
    DATE = "date"
    DATE_WITH_NOTE = "date_with_note"
    NUMERIC_WITH_UNIT = "numeric_with_unit"
    CHOICE = "choice"
    MULTI_CHOICE = "multi_choice"


CHOICE_FIELD_TYPES: Final = frozenset({FieldType.CHOICE, FieldType.MULTI_CHOICE})


FIELD_TYPES: Final = frozenset(ft.value for ft in FieldType)

_SLUG_RE: Final = re.compile(r"^[a-z][a-z0-9_]*$")


class _Strict(BaseModel):
    """Base for every template-domain model. Strict by design."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ChoiceOption(_Strict):
    """One selectable option of a ``choice``/``multi_choice`` section.

    ``value`` is the stable identity persisted in note content
    (``field_specific_metadata``); renaming or removing a value is a
    STRUCTURAL template edit because stored selections would dangle.
    ``voice_aliases`` fuel the sprint-13 extractor and are normalized
    here (NFC, lower-case, stripped) so the extractor never
    re-normalizes template data.
    """

    value: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    voice_aliases: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("value")
    @classmethod
    def _validate_value_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                f"option.value {v!r} must be a URL-safe slug "
                "(lower-case, digits, underscores; starts with letter)"
            )
        return v

    @field_validator("voice_aliases")
    @classmethod
    def _normalize_option_aliases(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        out: list[str] = []
        for alias in v:
            cleaned = unicodedata.normalize("NFC", alias).strip().lower()
            if not cleaned:
                raise ValueError("option voice_aliases must not contain empty strings")
            if len(cleaned) > 64:
                raise ValueError(f"option voice_alias {cleaned!r} exceeds 64 characters")
            out.append(cleaned)
        seen: set[str] = set()
        deduped: list[str] = []
        for alias in out:
            if alias not in seen:
                seen.add(alias)
                deduped.append(alias)
        return tuple(deduped)


SectionRole = Literal[
    "summary",
    "attendees",
    "agenda",
    "topics",
    "decisions",
    "action_items",
    "open_questions",
    "risks",
    "next_meeting",
    "requests",
    "user_notes",
    "transcript",
    "judgement",
    "custom",
]
"""What a section is for. See `note_service.domain.meeting_doc.roles`."""


class TemplateSection(_Strict):
    """One section of a template. Each section is dictated separately
    in sprint-06 section-aware mode."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    voice_aliases: tuple[str, ...] = Field(default_factory=tuple)
    required: bool = True
    field_type: FieldType = FieldType.FREE_TEXT
    asr_prompt: str = Field(min_length=1, max_length=_ASR_PROMPT_MAX_CHARS_APPROX)
    min_chars: int = Field(default=0, ge=0, le=10_000)
    order: int = Field(default=0, ge=0)
    default_content: str = Field(default="", max_length=4_000)
    # Per-section synthesis guidance; empty = none. Editing it is cosmetic.
    synthesis_prompt: str = Field(default="", max_length=2_000)
    # What the section is FOR, independent of its name; consumers decide by role, not id.
    # Optional: older templates have none and `meeting_doc.roles.role_of` falls back to an id map.
    role: SectionRole | None = None
    # 2..50 for choice/multi_choice, empty for every other field_type.
    options: tuple[ChoiceOption, ...] = Field(default_factory=tuple)

    @field_validator("id")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                f"section.id {v!r} must be a URL-safe slug "
                "(lower-case, digits, underscores; starts with letter)"
            )
        return v

    @field_validator("voice_aliases")
    @classmethod
    def _normalize_aliases(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        out: list[str] = []
        for alias in v:
            cleaned = alias.strip().lower()
            if not cleaned:
                raise ValueError("voice_aliases must not contain empty strings")
            out.append(cleaned)
        seen: set[str] = set()
        deduped: list[str] = []
        for alias in out:
            if alias not in seen:
                seen.add(alias)
                deduped.append(alias)
        return tuple(deduped)

    @model_validator(mode="after")
    def _validate_options(self) -> TemplateSection:
        if self.field_type in CHOICE_FIELD_TYPES:
            if not 2 <= len(self.options) <= 50:
                raise ValueError(
                    f"section {self.id!r}: field_type={self.field_type} requires "
                    f"2..50 options, got {len(self.options)}"
                )
        elif self.options:
            raise ValueError(
                f"section {self.id!r}: field_type={self.field_type} must not "
                f"define options (got {len(self.options)})"
            )

        values: set[str] = set()
        labels_ci: set[str] = set()
        aliases: set[str] = set()
        for opt in self.options:
            if opt.value in values:
                raise ValueError(f"section {self.id!r}: option value {opt.value!r} duplicated")
            values.add(opt.value)
            label_key = opt.label.casefold()
            if label_key in labels_ci:
                raise ValueError(
                    f"section {self.id!r}: option label {opt.label!r} duplicated (case-insensitive)"
                )
            labels_ci.add(label_key)
            # An alias on two options would make extraction ambiguous.
            for alias in opt.voice_aliases:
                if alias in aliases:
                    raise ValueError(
                        f"section {self.id!r}: option voice_alias {alias!r} "
                        "duplicated across options"
                    )
                aliases.add(alias)
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_optionals(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Drop unset ``options`` and ``role`` so older templates serialize byte-identically to their pre-bump dump."""
        data: dict[str, Any] = handler(self)
        if isinstance(data, dict):
            if not data.get("options"):
                data.pop("options", None)
            if data.get("role") is None:
                data.pop("role", None)
        return data


class TemplateMetadata(_Strict):
    """Optional metadata attached to a template definition."""

    billing_code: str | None = Field(default=None, max_length=32)
    notes: str = Field(default="", max_length=2_000)


class TemplateDefinition(_Strict):
    """Full template definition. Stored as ``templates.schema_jsonb``.

    The top-level ``code`` + ``language`` pair is the human-readable
    identifier; the row's UUID is the system identifier. Notes persist
    the UUID + ``schema_version`` at finalization.
    """

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    language: str = Field(pattern="^(uk|en|de)$")
    # Browse facet; accepts the legacy key ``specialty`` on input, always serialises as ``category``.
    category: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("category", "specialty"),
    )
    schema_version: int = Field(default=1, ge=1)
    sections: tuple[TemplateSection, ...] = Field(min_length=1, max_length=32)
    metadata: TemplateMetadata = Field(default_factory=TemplateMetadata)

    @field_validator("code")
    @classmethod
    def _validate_code_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_]*$", v):
            raise ValueError(f"template.code {v!r} must be a URL-safe slug")
        return v

    @model_validator(mode="after")
    def _validate_aliases_unique(self) -> TemplateDefinition:
        """Voice aliases must be unique across sections, or the section command is ambiguous."""
        seen: dict[str, str] = {}
        for section in self.sections:
            for alias in section.voice_aliases:
                if alias in seen:
                    raise ValueError(
                        f"voice_alias {alias!r} duplicated across sections "
                        f"{seen[alias]!r} and {section.id!r}"
                    )
                seen[alias] = section.id
        return self

    @model_validator(mode="after")
    def _validate_section_ids_unique(self) -> TemplateDefinition:
        seen: set[str] = set()
        for section in self.sections:
            if section.id in seen:
                raise ValueError(f"section.id {section.id!r} duplicated")
            seen.add(section.id)
        return self


class EditKind(StrEnum):
    """Whether the edit can be applied in place or requires a new row."""

    COSMETIC = "cosmetic"
    STRUCTURAL = "structural"
    NO_CHANGE = "no_change"


@dataclass(frozen=True, slots=True)
class EditClassification:
    kind: EditKind
    reasons: tuple[str, ...]


def classify_edit(old: TemplateDefinition, new: TemplateDefinition) -> EditClassification:
    """Structural (new row) when a section is added/removed/renamed, its ``field_type`` or ``required`` changes,
    ``min_chars`` increases, or an option ``value`` is removed (stored selections would dangle); else cosmetic
    or :class:`EditKind.NO_CHANGE`."""
    reasons: list[str] = []

    if old.code != new.code:
        reasons.append(f"code changed: {old.code} → {new.code}")
    if old.language != new.language:
        reasons.append(f"language changed: {old.language} → {new.language}")

    old_ids = {s.id for s in old.sections}
    new_ids = {s.id for s in new.sections}
    if old_ids != new_ids:
        added = new_ids - old_ids
        removed = old_ids - new_ids
        if added:
            reasons.append(f"sections added: {sorted(added)}")
        if removed:
            reasons.append(f"sections removed: {sorted(removed)}")

    old_by_id = {s.id: s for s in old.sections}
    new_by_id = {s.id: s for s in new.sections}
    for sid in old_ids & new_ids:
        a = old_by_id[sid]
        b = new_by_id[sid]
        if a.field_type != b.field_type:
            reasons.append(f"section {sid!r}: field_type changed {a.field_type} → {b.field_type}")
        if a.required != b.required:
            reasons.append(f"section {sid!r}: required flipped {a.required} → {b.required}")
        if b.min_chars > a.min_chars:
            reasons.append(f"section {sid!r}: min_chars increased {a.min_chars} → {b.min_chars}")
        removed_values = {o.value for o in a.options} - {o.value for o in b.options}
        if removed_values:
            reasons.append(
                f"section {sid!r}: option values removed/renamed: {sorted(removed_values)}"
            )

    if reasons:
        return EditClassification(kind=EditKind.STRUCTURAL, reasons=tuple(reasons))

    if old.model_dump() == new.model_dump():
        return EditClassification(kind=EditKind.NO_CHANGE, reasons=())
    return EditClassification(kind=EditKind.COSMETIC, reasons=())
