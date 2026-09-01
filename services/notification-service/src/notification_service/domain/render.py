"""Renders a fact into the content-free text a user actually sees.

The content boundary (no note content, no personal data — pointers only,
ADR-0031) is enforced by ALLOW-LISTING payload keys per category rather
than by scrubbing what a producer sent. Scrubbing is a losing game — it
can only remove the patterns someone thought of, and a person's surname
is not a pattern. An allow-list inverts the burden: a producer that adds
`author_name` to a payload finds it silently unused here, and adding it
to a template requires an explicit edit that shows up in the diff a
privacy review reads (ADR-0031).

Every string that reaches this module is additionally clamped, so even
an allow-listed field cannot become an exfiltration channel by being
very long.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final
from uuid import UUID

from notification_events import Category, NotificationEvent

from .catalog import spec_for

# The ONLY payload keys any template may read, per category. A key not
# listed here is invisible to rendering no matter what a producer sends.
ALLOWED_PAYLOAD_KEYS: Final[dict[Category, frozenset[str]]] = {
    Category.NOTE_FINALIZED: frozenset({"note_code"}),
    Category.NOTE_AMENDED: frozenset({"note_code", "version"}),
    Category.NOTE_CHAIN_FAILURE: frozenset({"note_code", "detected_at", "check_name"}),
    Category.NOTE_SHARED_WITH_YOU: frozenset({"note_code", "shared_by_display"}),
    # Counts and durations only. The transcript is the sensitive content
    # here, and no amount of it — not even a leading fragment as a
    # "preview" — is admissible: this row is read back by the digest
    # renderer too.
    Category.DICTATION_COMPLETED: frozenset({"duration_ms", "segments"}),
    # Same counts-only rule as a dictation. Deliberately NOT the audio
    # filename: a user naming an upload `ivanenko_2026-04-12.wav`
    # would put a surname and a date in a notification title.
    Category.TRANSCRIPTION_COMPLETED: frozenset({"duration_ms", "segments", "language", "model"}),
    # `error_kind` is a closed vocabulary (corrupt_audio / timeout /
    # gpu_oom). `error_detail` is NOT admitted: it is free text built
    # from an exception, and an exception that quotes the transcript it
    # choked on would carry note content straight into the feed.
    Category.TRANSCRIPTION_FAILED: frozenset({"error_kind"}),
    # No third party ever appears in this one — it is about the
    # recipient's own account. `requested_by_role` is the closed
    # vocabulary from the mfa_reminders CHECK (tenant_admin | auditor),
    # not a name: who filed an access-review finding is between the
    # reviewer and the audit log, and naming them turns a security ask
    # into an interpersonal one. `reminder_count` is admitted so a
    # second ask reads as a second ask.
    Category.SECURITY_MFA_REMINDER: frozenset({"requested_by_role", "reminder_count"}),
    Category.SYSTEM_DIGEST: frozenset({"count", "period"}),
}

# Labels for the reminder's requester vocabulary.
_REMINDER_ROLE_LABELS: Final[dict[str, str]] = {
    "tenant_admin": "Your workspace administrator",
    "auditor": "An auditor",
}

# Field clamp. Long enough for a note code or an error kind, far too
# short to carry a narrative.
MAX_FIELD_LEN: Final = 120


def safe_payload(event: NotificationEvent) -> dict[str, str]:
    """Project a payload down to its allow-listed, clamped, stringified keys."""
    allowed = ALLOWED_PAYLOAD_KEYS.get(event.category, frozenset())
    out: dict[str, str] = {}
    for key in allowed:
        if key not in event.payload:
            continue
        value = event.payload[key]
        if value is None:
            continue
        out[key] = str(value)[:MAX_FIELD_LEN]
    return out


def _code(fields: Mapping[str, str]) -> str:
    """The note's human-facing code — a pointer, never a title.

    Note titles are NOT used: a user-authored title routinely contains
    the very content this boundary exists to keep out of an email
    subject line.
    """
    return fields.get("note_code", "—")


def deep_link(event: NotificationEvent, *, base_url: str) -> str:
    """A path into the SPA. Carries ids, never content."""
    return notification_deep_link(event.resource_type, event.resource_id, base_url=base_url)


def render_title(event: NotificationEvent) -> str:
    fields = safe_payload(event)
    code = _code(fields)
    match event.category:
        case Category.NOTE_FINALIZED:
            return f"Note {code} finalized"
        case Category.NOTE_AMENDED:
            return f"Note {code} amended"
        case Category.NOTE_CHAIN_FAILURE:
            return f"Version-chain integrity failure ({code})"
        case Category.NOTE_SHARED_WITH_YOU:
            return f"Note {code} was shared with you"
        case Category.DICTATION_COMPLETED:
            return "Dictation completed"
        case Category.TRANSCRIPTION_COMPLETED:
            return "Audio transcription completed"
        case Category.TRANSCRIPTION_FAILED:
            return "Audio transcription failed"
        case Category.SECURITY_MFA_REMINDER:
            return "Enable two-factor authentication"
        case Category.SYSTEM_DIGEST:
            return f"Your notifications: {fields.get('count', '0')}"
    # Unreachable: spec_for() has already rejected unknown categories.
    raise KeyError(event.category)


def render_body(event: NotificationEvent) -> str:
    fields = safe_payload(event)
    code = _code(fields)
    match event.category:
        case Category.NOTE_FINALIZED:
            return f"Note {code} has been moved to the finalized state."
        case Category.NOTE_AMENDED:
            version = fields.get("version", "")
            suffix = f" Version {version}." if version else ""
            return f"An amendment was added to note {code}.{suffix}"
        case Category.NOTE_CHAIN_FAILURE:
            check = fields.get("check_name", "integrity check")
            return (
                f"The automatic check «{check}» found a mismatch in the "
                "note version chain. Administrator action is required."
            )
        case Category.NOTE_SHARED_WITH_YOU:
            who = fields.get("shared_by_display", "A colleague")
            return f"{who} gave you access to note {code}."
        case Category.DICTATION_COMPLETED:
            return f"Your dictation session was processed. Segments: {fields.get('segments', '0')}."
        case Category.TRANSCRIPTION_COMPLETED:
            return (
                f"Your audio has been transcribed. Segments: {fields.get('segments', '0')}. "
                "You can now create a note from it."
            )
        case Category.TRANSCRIPTION_FAILED:
            kind = fields.get("error_kind", "unknown reason")
            return f"The transcription job did not complete: {kind}. Please try again."
        case Category.SECURITY_MFA_REMINDER:
            raw_role = fields.get("requested_by_role", "")
            who = _REMINDER_ROLE_LABELS.get(raw_role, "Your security team")
            try:
                again = int(fields.get("reminder_count", "1")) > 1
            except (TypeError, ValueError):
                again = False
            prefix = f"{who} asks again" if again else f"{who} asks"
            return (
                f"{prefix} that you enable two-factor authentication (TOTP) "
                "for your account. It takes about a minute."
            )
        case Category.SYSTEM_DIGEST:
            return f"Summary for the last {fields.get('period', 'day')}."
    raise KeyError(event.category)


def severity_for(event: NotificationEvent) -> str:
    return str(spec_for(event.category).severity)


def coalesced_title(category: Category, count: int) -> str:
    """Title for a storm-coalesced row (E1)."""
    match category:
        case Category.NOTE_FINALIZED:
            return f"Notes finalized: {count}"
        case Category.NOTE_AMENDED:
            return f"Notes amended: {count}"
        case Category.DICTATION_COMPLETED:
            return f"Dictation sessions completed: {count}"
        case Category.TRANSCRIPTION_COMPLETED:
            return f"Audio transcriptions completed: {count}"
        case _:
            return f"New notifications: {count}"


def coalesced_body(count: int) -> str:
    return (
        f"{count} similar notifications were grouped to keep your feed readable. "
        "Open the list to review each one."
    )


def notification_deep_link(resource_type: str, resource_id: UUID, *, base_url: str) -> str:
    base = base_url.rstrip("/")
    if resource_type == "note":
        return f"{base}/notes/{resource_id}"
    if resource_type == "dictation_session":
        return f"{base}/dictations/{resource_id}"
    if resource_type == "transcription_job":
        return f"{base}/asr/jobs/{resource_id}"
    # The MFA reminder's resource is the USER — and the only useful place to
    # send them is enrolment, not a profile page. `{sub}` is deliberately not
    # in the path: the SPA enrols whoever is signed in, and a link carrying
    # somebody's id would be a link that looks actionable by anyone.
    if resource_type == "user":
        return f"{base}/mfa"
    return base
