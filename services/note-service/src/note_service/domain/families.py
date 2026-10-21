"""What each kind of meeting is, as one declarative table: its seed template, its
default visibility, whether a client version exists. Pure data and functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ── Section roles: re-exported from `roles.py`, never redefined ─────
from .roles import (  # noqa: F401  (re-exported for this module's readers)
    ACTION_ITEMS,
    AGENDA,
    ATTENDEES,
    CLAIMS,
    CONTACT,
    CUSTOM,
    DECISIONS,
    JUDGEMENT,
    NEXT_MEETING,
    OPEN_QUESTIONS,
    REQUESTS,
    RISKS,
    SPECIFICATIONS,
    SUMMARY,
    TOPICS,
    TRANSCRIPT,
    USER_NOTES,
    Role,
    role_of,
)


@dataclass(frozen=True, slots=True)
class Family:
    """One kind of meeting."""

    meeting_type: str
    """The `note_meetings.meeting_type` value that selects it."""
    template_prefix: str
    """Seed template code prefix; per-language copies share it."""
    default_visibility: str = "workspace"
    """1:1s and interview debriefs are private by default: they are about
    a person, and a workspace-visible one is a disclosure nobody chose."""
    client_version: bool = True
    """Whether a client version and a follow-up draft may be built at all."""


FAMILIES: Final[tuple[Family, ...]] = (
    Family(meeting_type="client", template_prefix="client_call"),
    Family(meeting_type="auto", template_prefix="meeting_notes"),
    Family(meeting_type="team", template_prefix="project_update"),
    Family(meeting_type="sales", template_prefix="sales_call"),
    Family(
        meeting_type="one_on_one",
        template_prefix="one_on_one",
        default_visibility="private",
        client_version=False,
    ),
    Family(
        meeting_type="interview",
        template_prefix="interview_debrief",
        default_visibility="private",
        client_version=False,
    ),
    # Recordings that are not meetings: no template of their own.
    Family(meeting_type="broadcast", template_prefix="broadcast", client_version=False),
    Family(
        meeting_type="memo",
        template_prefix="voice_memo",
        default_visibility="private",
        client_version=False,
    ),
)

# The author's choice or the writer's reading of a recording, mapped onto a family.
RECORDING_TYPES: Final[tuple[str, ...]] = (
    "meeting",
    "client_call",
    "sales_call",
    "interview",
    "one_on_one",
    "podcast_broadcast",
    "lecture_webinar",
    "voice_memo",
    "presentation_demo",
)
_FAMILY_OF_RECORDING: Final[dict[str, str]] = {
    "meeting": "auto",
    "client_call": "client",
    "sales_call": "sales",
    "interview": "interview",
    "one_on_one": "one_on_one",
    "podcast_broadcast": "broadcast",
    "lecture_webinar": "broadcast",
    "voice_memo": "memo",
    "presentation_demo": "broadcast",
}
_RECORDING_OF_MEETING: Final[dict[str, str]] = {
    "auto": "meeting",
    "team": "meeting",
    "client": "client_call",
    "sales": "sales_call",
    "one_on_one": "one_on_one",
    "interview": "interview",
}

_BY_TYPE: Final[dict[str, Family]] = {f.meeting_type: f for f in FAMILIES}
FALLBACK: Final[Family] = _BY_TYPE["auto"]


def family_for_type(meeting_type: str | None) -> Family:
    return _BY_TYPE.get(meeting_type or "", FALLBACK)


def family_for_template(template_code: str | None) -> Family:
    """The family a template belongs to, by code prefix (longest first)."""
    code = (template_code or "").lower()
    for fam in sorted(FAMILIES, key=lambda f: -len(f.template_prefix)):
        if code.startswith(fam.template_prefix):
            return fam
    return FALLBACK


def family_for_recording_type(recording_type: str | None) -> Family:
    """The family of a recording of this type."""
    return _BY_TYPE.get(_FAMILY_OF_RECORDING.get(recording_type or "", "auto"), FALLBACK)


def recording_type_for_meeting_type(meeting_type: str | None) -> str:
    """The author's meeting type as a recording type (`team` is a meeting)."""
    return _RECORDING_OF_MEETING.get(meeting_type or "auto", "meeting")


def detected_value(recording_type: str) -> str:
    """What `note_meetings.meeting_type_detected` stores: the meeting-type word for
    meeting kinds, the recording type itself otherwise."""
    family = _FAMILY_OF_RECORDING.get(recording_type, "auto")
    if family in ("broadcast", "memo"):
        return recording_type
    return family


def supports_client_version(family: Family) -> bool:
    """A 1:1 and an interview debrief have no client version: nothing of them leaves the workspace."""
    return family.client_version
