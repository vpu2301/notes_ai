"""Tamper-evident hash-chained audit event log (ADR-0008)."""

from __future__ import annotations

from .canonical import canonicalize, canonicalize_str
from .exceptions import (
    AuditError,
    CanonicalizationError,
    ChainWriteError,
    TenantMismatchError,
)
from .types import AuditEventReceipt, Severity
from .verifier import AuditVerifier, DivergenceReason, VerificationReport
from .writer import GENESIS_PREV_HASH, AuditWriter

__all__ = [
    "AuditError",
    "AuditEventReceipt",
    "AuditVerifier",
    "AuditWriter",
    "CanonicalizationError",
    "ChainWriteError",
    "DivergenceReason",
    "GENESIS_PREV_HASH",
    "Severity",
    "TenantMismatchError",
    "VerificationReport",
    "canonicalize",
    "canonicalize_str",
]
