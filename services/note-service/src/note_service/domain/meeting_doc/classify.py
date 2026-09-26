"""What a recording is — decided before anything is extracted.

Summary Engine v2, Q3. The kinds a family offers the extractor are what
keeps a "Decisions" section off a news podcast: the model cannot answer
with a kind that is not in its enum. So the type has to be known BEFORE
extraction — which is why this is not the context pass (that runs after).

One small model call on the opening of the recording, then code rules
that override the model where the signal is unambiguous. The author's own
choice of meeting type is never second-guessed: the worker only calls
this for `auto`. A failed call is a meeting — the family every note had
before Q3.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from . import prompts
from .types import RECORDING_TYPES

logger = logging.getLogger(__name__)

# The opening of the recording the model sees: the first two windows,
# capped. The first minutes decide the type in practice.
MAX_HEAD_CHARS: Final = 8_000
CLASSIFY_MAX_TOKENS: Final = 50
VOICE_MEMO_MAX_MINUTES: Final = 5.0

SOURCE_USER: Final = "user"
SOURCE_CLASSIFIER: Final = "classifier"
SOURCE_RULE: Final = "rule"
SOURCE_TEMPLATE: Final = "template"

# The order the model sees the types in. Not the table's order: a small
# model picks the first option when unsure, and "meeting" first labelled
# the audit's news podcast a meeting (Q3 eval: 0/3 → 3/3 on m06 with this
# order). Meeting last, as in the context prompt since Q1.
OFFERED_ORDER: Final[tuple[str, ...]] = (
    "podcast_broadcast",
    "presentation_demo",
    "lecture_webinar",
    "interview",
    "voice_memo",
    "one_on_one",
    "sales_call",
    "client_call",
    "meeting",
)
assert set(OFFERED_ORDER) == set(RECORDING_TYPES)

CLASSIFY_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["recording_type"],
    "properties": {"recording_type": {"type": "string", "enum": list(OFFERED_ORDER)}},
}


async def classify(
    provider: Any,
    *,
    head: str,
    language: str,
    speakers: int,
    minutes: float,
    calendar_title: str | None,
    attendees: int,
) -> tuple[str, str]:
    """``(recording_type, source)`` for an `auto` note.

    ``head`` is the first windows' rendering; ``speakers``, ``minutes``,
    the calendar title and its attendee count are what code can check
    without a model."""
    said: str | None = None
    try:
        answer = await provider.complete(
            prompts.classify_prompt(head[:MAX_HEAD_CHARS]),
            CLASSIFY_SCHEMA,
            max_tokens=CLASSIFY_MAX_TOKENS,
            temperature=0.0,
            system=prompts.classify_system(language),
        )
        payload = answer.json if isinstance(getattr(answer, "json", None), dict) else None
        if payload is None:
            import json

            payload = json.loads(getattr(answer, "text", answer))
        value = payload.get("recording_type") if isinstance(payload, dict) else None
        said = value if value in RECORDING_TYPES else None
    except Exception:  # noqa: BLE001 — a type we cannot read is a meeting
        logger.warning("meeting_doc.classify_failed", exc_info=True)
        said = None

    # One voice, a few minutes, nothing in the calendar: somebody talking
    # to their phone, whatever the model heard.
    # F3: one voice demonstrating something to an audience is one voice
    # too — the model's presentation answer stands (a short walkthrough is
    # exactly this shape; Q3's podcast rule is unchanged).
    if (
        speakers <= 1
        and minutes < VOICE_MEMO_MAX_MINUTES
        and not calendar_title
        and said != "presentation_demo"
    ):
        return "voice_memo", SOURCE_RULE
    # One voice for longer is a talk — unless the model heard a broadcast.
    if (
        speakers <= 1
        and minutes >= VOICE_MEMO_MAX_MINUTES
        and said not in ("podcast_broadcast", "presentation_demo")
    ):
        return "lecture_webinar", SOURCE_RULE
    # A calendared call with people on it is not a broadcast.
    if calendar_title and attendees >= 2 and said in ("podcast_broadcast", "presentation_demo"):
        return "meeting", SOURCE_RULE
    if said is None:
        return "meeting", SOURCE_TEMPLATE
    return said, SOURCE_CLASSIFIER
