"""Closed vocabularies for the notification wire; each enum must stay in lockstep with its DB CHECK constraint."""

from __future__ import annotations

from enum import StrEnum


class Category(StrEnum):
    """The v1 notification categories.

    Adding a member here is not enough to make it work: every category
    MUST also have an entry in ``notification_service.domain.catalog``.
    A test enforces the 1:1 mapping, so an un-catalogued category is a
    build failure rather than a silent no-op at runtime — the same
    "unknown intent is a bug" contract as nlp-service's operations map.
    """

    # Producers retired with the finalize lifecycle; kept so existing rows render and preferences load.
    NOTE_FINALIZED = "note.finalized"
    NOTE_AMENDED = "note.amended"
    NOTE_CHAIN_FAILURE = "note.chain_failure"
    NOTE_SHARED_WITH_YOU = "note.shared_with_you"
    # A recipient acted on the shared page; debounced per link by the producer.
    NOTE_RECIPIENT_RESPONDED = "note.recipient_responded"
    # A recipient link was opened; in-app only.
    NOTE_LINK_STATUS_CHANGED = "note.link_status_changed"
    # A recipient reported a shared page; the workspace's admins hear.
    SHARE_REPORTED = "share.reported"
    DICTATION_COMPLETED = "dictation.completed"
    TRANSCRIPTION_COMPLETED = "transcription.completed"
    TRANSCRIPTION_FAILED = "transcription.failed"
    # An access review asked this account to enrol a second factor (the standing half is `mfa_reminders`).
    SECURITY_MFA_REMINDER = "security.mfa_reminder"
    # Monthly AI budget spent; the admins hear.
    AI_BUDGET_REACHED = "ai.budget_reached"
    SYSTEM_DIGEST = "system.digest"


class Channel(StrEnum):
    """Delivery channels; push members can be added without a migration (one outbox row per (notification, channel))."""

    IN_APP = "in_app"
    EMAIL = "email"


class EmailMode(StrEnum):
    """Per-category email delivery mode."""

    IMMEDIATE = "immediate"
    DIGEST = "digest"
    OFF = "off"


class Severity(StrEnum):
    """Drives client-side presentation, not routing."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
