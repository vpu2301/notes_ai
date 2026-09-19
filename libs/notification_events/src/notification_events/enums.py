"""Closed vocabularies shared across the notification wire.

Every one of these is a ``StrEnum`` so it serialises as its literal value
in JSON and compares equal to the plain string a DB CHECK constraint
stores — the enum and the SQL constraint must be kept in lockstep.
"""

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

    # Producers retired with the finalize lifecycle (note-service 0042);
    # kept so rows already in the feed still render and preferences load.
    NOTE_FINALIZED = "note.finalized"
    NOTE_AMENDED = "note.amended"
    NOTE_CHAIN_FAILURE = "note.chain_failure"
    NOTE_SHARED_WITH_YOU = "note.shared_with_you"
    # Sprint 20: a recipient acted on the shared page (confirm/done/
    # dispute/flag). Debounced per link by the producer.
    NOTE_RECIPIENT_RESPONDED = "note.recipient_responded"
    # Sprint 22: a recipient link was opened. In-app only; feeds the
    # sender's "Sent → Opened" chips without polling.
    NOTE_LINK_STATUS_CHANGED = "note.link_status_changed"
    # Sprint 23: a recipient reported a shared page; the workspace's admins hear.
    SHARE_REPORTED = "share.reported"
    DICTATION_COMPLETED = "dictation.completed"
    TRANSCRIPTION_COMPLETED = "transcription.completed"
    TRANSCRIPTION_FAILED = "transcription.failed"
    # S21: an access review found this account without a second factor and
    # asked for one. The standing half of the reminder lives in
    # `mfa_reminders` and renders as a banner until enrolment; this is the
    # arriving half. `exclude_actor` is irrelevant here — the actor is the
    # reviewer, the audience is the subject, and they are never the same.
    SECURITY_MFA_REMINDER = "security.mfa_reminder"
    SYSTEM_DIGEST = "system.digest"


class Channel(StrEnum):
    """Delivery channels.

    ``apns``/``fcm`` are deliberately absent — sprint 18 adds them as new
    members plus a ``PushProvider``; the outbox schema already models one
    row per (notification, channel) so no migration is needed then.
    """

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
