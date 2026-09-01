"""Read-purpose enum required on full-content GET by non-authors.

Captured into audit on every read so tenant admins can audit access
patterns.
"""

from __future__ import annotations

from enum import StrEnum


class ReadPurpose(StrEnum):
    REVIEW = "review"
    AUDIT = "audit"
    LEGAL = "legal"
    EXPORT = "export"
    COLLABORATION = "collaboration"
