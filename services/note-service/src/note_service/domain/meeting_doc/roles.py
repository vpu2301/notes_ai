"""What a section is FOR (its role), as opposed to what this template calls it.
The engine, the shared page, the action-item projection and the PDF all call
:func:`role_of`. Templates without a declared role fall back to an id map.
"""

from __future__ import annotations

import re
from typing import Final

# ── The vocabulary ──────────────────────────────────────────────────

Role = str

SUMMARY: Final[Role] = "summary"
ATTENDEES: Final[Role] = "attendees"
AGENDA: Final[Role] = "agenda"
TOPICS: Final[Role] = "topics"
DECISIONS: Final[Role] = "decisions"
ACTION_ITEMS: Final[Role] = "action_items"
OPEN_QUESTIONS: Final[Role] = "open_questions"
RISKS: Final[Role] = "risks"
NEXT_MEETING: Final[Role] = "next_meeting"
REQUESTS: Final[Role] = "requests"
USER_NOTES: Final[Role] = "user_notes"
TRANSCRIPT: Final[Role] = "transcript"
JUDGEMENT: Final[Role] = "judgement"
CUSTOM: Final[Role] = "custom"
# The dates and deadlines a recording named.
KEY_DATES: Final[Role] = "key_dates"
# The figures a recording gave, and what it asks its audience to do.
SPECIFICATIONS: Final[Role] = "specifications"
CONTACT: Final[Role] = "contact"

ROLES: Final[tuple[Role, ...]] = (
    SUMMARY,
    ATTENDEES,
    AGENDA,
    TOPICS,
    DECISIONS,
    ACTION_ITEMS,
    OPEN_QUESTIONS,
    RISKS,
    NEXT_MEETING,
    REQUESTS,
    USER_NOTES,
    TRANSCRIPT,
    JUDGEMENT,
    CUSTOM,
    KEY_DATES,
    SPECIFICATIONS,
    CONTACT,
)

# Section ids of templates written before roles existed; anything else is `custom`.
_BY_ID: Final[dict[str, Role]] = {
    "summary": SUMMARY,
    "status_summary": SUMMARY,
    "attendees": ATTENDEES,
    "contact": ATTENDEES,
    "candidate": ATTENDEES,
    "agenda": AGENDA,
    "discussion": TOPICS,
    "topics": TOPICS,
    "context": TOPICS,
    "decisions": DECISIONS,
    "action_items": ACTION_ITEMS,
    "next_steps": ACTION_ITEMS,
    "open_questions": OPEN_QUESTIONS,
    "risks": RISKS,
    "next_meeting": NEXT_MEETING,
    "requests": REQUESTS,
    "user_notes": USER_NOTES,
    "transcript": TRANSCRIPT,
    # Typed fields a person sets; the engine may SUGGEST a value, never write one.
    "deal_stage": JUDGEMENT,
    "recommendation": JUDGEMENT,
    "overall_status": JUDGEMENT,
    "target_date": JUDGEMENT,
    # Not "contact": templates already use that id for the attendee block.
    "specifications": SPECIFICATIONS,
    "call_to_action": CONTACT,
}


# Engine-made sections: "gen:overview" and one "gen:<slug>" per topic.
GENERATED_PREFIX: Final = "gen:"
OVERVIEW_KEY: Final = "gen:overview"


def is_generated(section_key: str) -> bool:
    return section_key.startswith(GENERATED_PREFIX)


def generated_key(title: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """A stable, readable key for a topic section: ``gen:transfer-strategy``.
    Unique within ``taken`` by a numeric suffix."""
    slug = re.sub(r"[^\w]+", "-", title.casefold(), flags=re.UNICODE).strip("-")[:40].strip("-")
    slug = slug or "topic"
    key = f"{GENERATED_PREFIX}{slug}"
    n = 2
    while key in taken or key == OVERVIEW_KEY:
        key = f"{GENERATED_PREFIX}{slug}-{n}"
        n += 1
    return key


def role_of(section: object) -> Role:
    """The role of a template section or bare key: the declared `role`, else the id
    map; a generated section's role is in its key."""
    if isinstance(section, str):
        if section == OVERVIEW_KEY:
            return SUMMARY
        if is_generated(section):
            return TOPICS
        return _BY_ID.get(section, CUSTOM)
    declared = getattr(section, "role", None)
    if isinstance(declared, str) and declared in ROLES:
        return declared
    key = getattr(section, "id", None) or getattr(section, "section_key", None)
    return _BY_ID.get(str(key), CUSTOM) if key else CUSTOM


def role_map(definition: object) -> dict[str, Role]:
    """``{section_key: role}`` for a whole template definition."""
    sections = getattr(definition, "sections", None) or []
    out: dict[str, Role] = {}
    for section in sections:
        key = getattr(section, "id", None) or getattr(section, "section_key", None)
        if key:
            out[str(key)] = role_of(section)
    return out


def keys_with_role(definition: object, role: Role) -> list[str]:
    """Every section of this template with the given role, in template order."""
    return [key for key, value in role_map(definition).items() if value == role]


def first_key_with_role(definition: object, role: Role) -> str | None:
    keys = keys_with_role(definition, role)
    return keys[0] if keys else None
