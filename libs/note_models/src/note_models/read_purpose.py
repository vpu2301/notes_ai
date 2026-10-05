"""Read-purpose enum required on full-content GET by non-authors; captured into audit."""

from __future__ import annotations

from enum import StrEnum


class ReadPurpose(StrEnum):
    REVIEW = "review"
    AUDIT = "audit"
    LEGAL = "legal"
    EXPORT = "export"
    COLLABORATION = "collaboration"
