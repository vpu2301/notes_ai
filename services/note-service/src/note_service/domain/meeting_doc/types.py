"""What each kind of meeting needs, as one declarative table: fact kinds and
their roles, judgement fields that may be suggested, whether a client version
exists. Pure data and functions; nothing imports the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# ── Section roles: re-exported from `roles.py`, never redefined ─────
from .roles import (  # noqa: F401  (re-exported for this module's readers)
    ACTION_ITEMS,
    AGENDA,
    ATTENDEES,
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

# ── Families ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Family:
    """One kind of meeting."""

    meeting_type: str
    """The `note_meetings.meeting_type` value that selects it."""
    template_prefix: str
    """Seed template code prefix; per-language copies share it."""
    extra_kinds: dict[str, Role] = field(default_factory=dict)
    """Fact kinds this family adds to the generic set, and where each
    lands. The extractor's enum for a call is the generic kinds plus
    these — a smaller choice set is easier for a small model."""
    judgement_fields: tuple[str, ...] = ()
    """Typed fields a generation may SUGGEST, with a quote, and never set."""
    internal_kinds: frozenset[str] = frozenset()
    """Kinds that never leave the workspace, whatever the note's sharing."""
    default_visibility: str = "workspace"
    """1:1s and interview debriefs are private by default: they are about
    a person, and a workspace-visible one is a disclosure nobody chose."""
    client_version: bool = True
    """Whether a client version and a follow-up draft may be built at all."""
    excluded_kinds: frozenset[str] = frozenset()
    """Generic kinds this family does NOT offer: the enum the model answers with omits them."""


# Kinds every family extracts, and where each lands.
GENERIC_KINDS: Final[dict[str, Role]] = {
    "decision": DECISIONS,
    "action": ACTION_ITEMS,
    "question": OPEN_QUESTIONS,
    "key_point": TOPICS,
    "user_point": USER_NOTES,
    "agenda_item": AGENDA,
    "completion": ACTION_ITEMS,
    "figure": SPECIFICATIONS,
}

# Internal in every family; a client version drops these.
ALWAYS_INTERNAL: Final[frozenset[str]] = frozenset({"user_point", "judgement"})

FAMILIES: Final[tuple[Family, ...]] = (
    Family(
        meeting_type="client",
        template_prefix="client_call",
        extra_kinds={
            "client_request": REQUESTS,
            # Grouped as "we do" / "they do" when rendered.
            "commitment_ours": ACTION_ITEMS,
            "commitment_theirs": ACTION_ITEMS,
            "risk": RISKS,
            "next_meeting": NEXT_MEETING,
        },
    ),
    Family(
        meeting_type="auto",
        template_prefix="meeting_notes",
        extra_kinds={"progress": CUSTOM, "risk": RISKS, "blocker": RISKS},
    ),
    Family(
        meeting_type="team",
        template_prefix="project_update",
        extra_kinds={
            "progress": CUSTOM,
            "risk": RISKS,
            "blocker": RISKS,
            "status_statement": SUMMARY,
        },
        judgement_fields=("overall_status", "target_date"),
    ),
    Family(
        meeting_type="sales",
        template_prefix="sales_call",
        extra_kinds={
            "need": CUSTOM,
            "objection": CUSTOM,
            "stakeholder": ATTENDEES,
            "budget_timeline": TOPICS,
            "competitor_mention": TOPICS,
        },
        judgement_fields=("deal_stage",),
        internal_kinds=frozenset({"objection", "competitor_mention", "budget_timeline"}),
    ),
    Family(
        meeting_type="one_on_one",
        template_prefix="one_on_one",
        extra_kinds={
            "win": CUSTOM,
            "challenge": CUSTOM,
            "feedback_given": CUSTOM,
            "feedback_received": CUSTOM,
            "growth_topic": CUSTOM,
        },
        internal_kinds=frozenset({"feedback_given", "feedback_received"}),
        default_visibility="private",
        client_version=False,
    ),
    Family(
        meeting_type="interview",
        template_prefix="interview_debrief",
        extra_kinds={"strength": CUSTOM, "concern": CUSTOM, "candidate_fact": ATTENDEES},
        judgement_fields=("recommendation",),
        internal_kinds=frozenset({"concern"}),
        default_visibility="private",
        client_version=False,
    ),
    # Recordings that are not meetings: no template of their own, only the kinds change.
    Family(
        meeting_type="broadcast",
        template_prefix="broadcast",
        extra_kinds={"introduction": ATTENDEES, "next_step": CONTACT},
        excluded_kinds=frozenset({"decision", "action", "agenda_item", "completion"}),
        client_version=False,
    ),
    Family(
        meeting_type="memo",
        template_prefix="voice_memo",
        excluded_kinds=frozenset({"agenda_item", "completion"}),
        default_visibility="private",
        client_version=False,
    ),
)

# Decided before extraction (author's choice or `classify`), mapped onto a family.
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


def fact_kinds(family: Family) -> dict[str, Role]:
    """Every kind this family's extractor may return, and its role:
    the generic kinds it does not exclude, plus its own."""
    generic = {k: r for k, r in GENERIC_KINDS.items() if k not in family.excluded_kinds}
    return {**generic, **family.extra_kinds}


def family_for_recording_type(recording_type: str | None) -> Family:
    """The family that extracts a recording of this type."""
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


def is_internal_kind(family: Family, kind: str) -> bool:
    """Whether a fact of this kind stays inside the workspace."""
    return kind in ALWAYS_INTERNAL or kind in family.internal_kinds


def supports_client_version(family: Family) -> bool:
    """A 1:1 and an interview debrief have no client version: nothing of them leaves the workspace."""
    return family.client_version
