"""Typed contract for ``NoteSection.field_specific_metadata``, enforced at the WRITE path (storage stays a plain dict).

Empty is always valid; ``source`` is required with any other key; ``confidence`` is required for ``extracted`` and
must be omitted for ``manual``; nothing auto-promotes extracted → manual. ``field_type`` is a ``str`` (leaf package).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class MetadataSource(StrEnum):
    EXTRACTED = "extracted"
    MANUAL = "manual"


class FieldMetadataError(ValueError):
    """Raised when a metadata dict violates the field-type contract."""

    def __init__(self, field_type: str, reason: str) -> None:
        self.field_type = field_type
        self.reason = reason
        super().__init__(f"field_specific_metadata invalid for {field_type!r}: {reason}")


class _StrictMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: MetadataSource
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _confidence_matches_source(self) -> _StrictMeta:
        if self.source is MetadataSource.EXTRACTED and self.confidence is None:
            raise ValueError("extracted metadata requires confidence")
        if self.source is MetadataSource.MANUAL and self.confidence is not None:
            raise ValueError("manual metadata must omit confidence")
        return self


class ChoiceMeta(_StrictMeta):
    """``choice`` — a single selected option ``value``."""

    selected: str = Field(min_length=1, max_length=64)


class MultiChoiceMeta(_StrictMeta):
    """``multi_choice`` — the selected option ``value``s (≥ 1; an empty
    selection is represented by an empty metadata dict, not an empty
    list)."""

    selected: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("selected")
    @classmethod
    def _unique(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v):
            raise ValueError("selected values must be unique")
        return v


class NumericMeta(_StrictMeta):
    """``numeric_with_unit`` — a bound value + unit."""

    value: float
    unit: str = Field(min_length=1, max_length=32)


class DateMeta(_StrictMeta):
    """``date`` / ``date_with_note`` — an ISO calendar date."""

    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("date")
    @classmethod
    def _real_date(cls, v: str) -> str:
        try:
            _dt.date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"date {v!r} is not a real calendar date") from exc
        return v


FieldMeta = ChoiceMeta | MultiChoiceMeta | NumericMeta | DateMeta

# Field types absent here (free_text) accept no metadata.
META_MODEL_BY_FIELD_TYPE: Final[Mapping[str, type[FieldMeta]]] = {
    "choice": ChoiceMeta,
    "multi_choice": MultiChoiceMeta,
    "numeric_with_unit": NumericMeta,
    "date": DateMeta,
    "date_with_note": DateMeta,
}


def parse_field_metadata(field_type: str, metadata: Mapping[str, Any]) -> FieldMeta | None:
    """Parse a metadata dict into its typed model; ``None`` for empty, :class:`FieldMetadataError` when invalid."""
    if not metadata:
        return None
    model = META_MODEL_BY_FIELD_TYPE.get(field_type)
    if model is None:
        raise FieldMetadataError(field_type, "this field_type accepts no metadata keys")
    try:
        return model.model_validate(dict(metadata))
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "<root>"
        raise FieldMetadataError(field_type, f"{loc}: {first['msg']}") from exc


def validate_field_metadata(field_type: str, metadata: Mapping[str, Any]) -> None:
    """Raise :class:`FieldMetadataError` unless ``metadata`` is valid (parse-and-discard)."""
    parse_field_metadata(field_type, metadata)
