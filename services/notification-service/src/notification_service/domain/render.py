"""Renders a fact into the content-free text a user sees.

Content boundary (pointers only, ADR-0031) is enforced by ALLOW-LISTING payload keys
per category, never by scrubbing; every field is also length-clamped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final
from uuid import UUID

from notification_events import Category, NotificationEvent

from .catalog import spec_for

# The ONLY payload keys rendering may read, per category.
ALLOWED_PAYLOAD_KEYS: Final[dict[Category, frozenset[str]]] = {
    Category.NOTE_FINALIZED: frozenset({"note_code"}),
    Category.NOTE_AMENDED: frozenset({"note_code", "version"}),
    Category.NOTE_CHAIN_FAILURE: frozenset({"note_code", "detected_at", "check_name"}),
    Category.NOTE_SHARED_WITH_YOU: frozenset({"note_code", "shared_by_display"}),
    # `link_label` is sender-typed, never recipient input; `kind` is a closed vocabulary.
    Category.NOTE_RECIPIENT_RESPONDED: frozenset({"note_code", "link_label", "kind"}),
    Category.NOTE_LINK_STATUS_CHANGED: frozenset({"note_code", "link_label", "delivery_status"}),
    Category.SHARE_REPORTED: frozenset({"note_code", "reason"}),
    # Counts and durations only; no transcript fragment, ever.
    Category.DICTATION_COMPLETED: frozenset({"duration_ms", "segments"}),
    # Counts only; NOT the audio filename (may carry a surname and a date).
    Category.TRANSCRIPTION_COMPLETED: frozenset({"duration_ms", "segments", "language", "model"}),
    # `error_kind` is a closed vocabulary; `error_detail` is free text that may quote the transcript.
    Category.TRANSCRIPTION_FAILED: frozenset({"error_kind"}),
    # `requested_by_role` is a closed vocabulary, never the reviewer's name.
    Category.SECURITY_MFA_REMINDER: frozenset({"requested_by_role", "reminder_count"}),
    Category.SYSTEM_DIGEST: frozenset({"count", "period"}),
}

# Labels for the reminder's requester vocabulary.
_REMINDER_ROLE_LABELS: Final[dict[str, str]] = {
    "tenant_admin": "Your workspace administrator",
    "auditor": "An auditor",
}

# Field clamp: enough for a note code, too short for a narrative.
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
    """The note's code; never the user-authored title (content boundary)."""
    return fields.get("note_code", "—")


def deep_link(event: NotificationEvent, *, base_url: str) -> str:
    """A path into the SPA. Carries ids, never content."""
    return notification_deep_link(event.resource_type, event.resource_id, base_url=base_url)


def _money(cents: object) -> str:
    """Cents as USD."""
    try:
        return f"${int(str(cents)) / 100:.2f}"
    except (TypeError, ValueError):
        return "the budget"


_RESPONSE_VERBS: Final[dict[str, str]] = {
    "confirm": "confirmed an item on",
    "done": "marked an item done on",
    "dispute": "disputed an item on",
    "flag": "flagged a section on",
}


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
        case Category.NOTE_RECIPIENT_RESPONDED:
            who = fields.get("link_label") or "A recipient"
            return f"{who} responded on note {code}"
        case Category.NOTE_LINK_STATUS_CHANGED:
            who = fields.get("link_label") or "A recipient"
            return f"{who} opened note {code}"
        case Category.SHARE_REPORTED:
            return f"A shared page of note {code} was reported"
        case Category.DICTATION_COMPLETED:
            return "Dictation completed"
        case Category.TRANSCRIPTION_COMPLETED:
            return "Audio transcription completed"
        case Category.TRANSCRIPTION_FAILED:
            return "Audio transcription failed"
        case Category.SECURITY_MFA_REMINDER:
            return "Enable two-factor authentication"
        case Category.AI_BUDGET_REACHED:
            return "Automatic note writing has paused"
        case Category.SYSTEM_DIGEST:
            return f"Your notifications: {fields.get('count', '0')}"
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
        case Category.NOTE_RECIPIENT_RESPONDED:
            who = fields.get("link_label") or "A recipient"
            verb = _RESPONSE_VERBS.get(fields.get("kind", ""), "responded to")
            return f"{who} {verb} note {code}. Open the note to see the responses."
        case Category.NOTE_LINK_STATUS_CHANGED:
            who = fields.get("link_label") or "A recipient"
            return f"{who} opened the link to note {code}."
        case Category.SHARE_REPORTED:
            reason = fields.get("reason", "other")
            return (
                f"A recipient reported the shared page of note {code} ({reason}). "
                "Review the note's links."
            )
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
        case Category.AI_BUDGET_REACHED:
            spent = _money(fields.get("spent_cents"))
            budget = _money(fields.get("budget_cents"))
            return (
                f"This workspace has used {spent} of its {budget} monthly AI budget, "
                "so new recordings are transcribed but not written up. "
                "An admin can raise the budget in Settings › Data."
            )
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
    # MFA reminder: link to enrolment; `{sub}` deliberately not in the path.
    if resource_type == "user":
        return f"{base}/mfa"
    return base
