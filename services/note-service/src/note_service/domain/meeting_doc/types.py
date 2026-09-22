"""What each kind of meeting needs, as one declarative table.

A sales discovery call, a 1:1 and a client status call are not the same
document. The engine could grow a branch per type; instead every
difference between them lives here, as data:

* which **fact kinds** the extractor may return for that family, and which
  template section each kind lands in;
* which **judgement fields** may be *suggested* (never set) for it;
* whether a note of that type may leave the workspace at all.

Adding a type is a row here plus a template seed. Turning a kind off
because it is not precise enough is deleting one entry — configuration,
not code (Sprint 36's kind kill-switch).

Everything here is pure data and pure functions; nothing imports the
engine, so the clients and the routes can read the same table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# ── Section roles ───────────────────────────────────────────────────
#
# The vocabulary lives in `roles.py` (Sprint 33), which is also what the
# engine, the shared page, the action-item projection and the PDF decide
# by. Re-exported here — NOT redefined — so a family table and a renderer
# can never disagree about what "topics" means.
from .roles import (  # noqa: F401  (re-exported for this module's readers)
    ACTION_ITEMS,
    AGENDA,
    ATTENDEES,
    CUSTOM,
    DECISIONS,
    JUDGEMENT,
    NEXT_MEETING,
    OPEN_QUESTIONS,
    REQUESTS,
    RISKS,
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


# Kinds every family extracts. The engine (Sprint 33) owns their meaning;
# the roles they land in are here so one table answers "where does this go".
GENERIC_KINDS: Final[dict[str, Role]] = {
    "decision": DECISIONS,
    "action": ACTION_ITEMS,
    "question": OPEN_QUESTIONS,
    "key_point": TOPICS,
    "user_point": USER_NOTES,
    "agenda_item": AGENDA,
    "completion": ACTION_ITEMS,
}

# Internal by nature, in every family: what the author thinks about the
# other side, what the model is unsure of, and anything the author typed
# for themselves. A client version drops these before anyone asks.
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
        # What the buyer objected to, and what we know about their budget
        # and their other vendors, is ours — not theirs.
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
)

_BY_TYPE: Final[dict[str, Family]] = {f.meeting_type: f for f in FAMILIES}
FALLBACK: Final[Family] = _BY_TYPE["auto"]


def family_for_type(meeting_type: str | None) -> Family:
    return _BY_TYPE.get(meeting_type or "", FALLBACK)


def family_for_template(template_code: str | None) -> Family:
    """The family a template belongs to, by code prefix.

    Longest prefix first, so `client_call_uk` does not match a shorter
    family that happens to be a prefix of it.
    """
    code = (template_code or "").lower()
    for fam in sorted(FAMILIES, key=lambda f: -len(f.template_prefix)):
        if code.startswith(fam.template_prefix):
            return fam
    return FALLBACK


def fact_kinds(family: Family) -> dict[str, Role]:
    """Every kind this family's extractor may return, and its role."""
    return {**GENERIC_KINDS, **family.extra_kinds}


def is_internal_kind(family: Family, kind: str) -> bool:
    """Whether a fact of this kind stays inside the workspace."""
    return kind in ALWAYS_INTERNAL or kind in family.internal_kinds


def supports_client_version(family: Family) -> bool:
    """A 1:1 and an interview debrief have no client. Building one would
    be building a way to send a colleague's performance conversation, or a
    candidate's assessment, outside the workspace."""
    return family.client_version
