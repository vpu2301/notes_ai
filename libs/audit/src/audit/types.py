"""Typed surfaces for libs/audit: severity enum, event-kind catalogue marker, receipt."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Severity(StrEnum):
    """Audit event severity, drives alerting + retention: ``sec`` triggers SIEM alerting."""

    INFO = "info"
    WARN = "warn"
    SEC = "sec"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AuditEventReceipt:
    """Returned by :meth:`AuditWriter.write_event` on success."""

    tenant_id: UUID
    seq: int
    payload_hash: bytes
