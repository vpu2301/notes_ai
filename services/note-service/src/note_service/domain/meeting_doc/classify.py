"""What a recording is, decided BEFORE extraction (the kind enum keeps a
"Decisions" section off a podcast): one model call on the opening, then code
rules where the signal is unambiguous. Only for `auto`; a failed call is a meeting.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any, Final

from . import prompts
from .types import RECORDING_TYPES

logger = logging.getLogger(__name__)

# The opening the model sees: the first two windows, capped.
MAX_HEAD_CHARS: Final = 8_000
CLASSIFY_MAX_TOKENS: Final = 50
VOICE_MEMO_MAX_MINUTES: Final = 5.0

SOURCE_USER: Final = "user"
SOURCE_CLASSIFIER: Final = "classifier"
SOURCE_RULE: Final = "rule"
SOURCE_TEMPLATE: Final = "template"
# Code cues settled a close call.
SOURCE_CUES: Final = "cues"

# Meeting last: a small model picks the first option when unsure.
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

    # One voice, a few minutes, no calendar: a voice memo, unless the model heard a demo.
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


# ── Lecture or podcast, settled by cues ─────────────────────────────

PODCAST: Final = "podcast_broadcast"
LECTURE: Final = "lecture_webinar"
CUE_PAIR: Final = frozenset({PODCAST, LECTURE})
_SHOW_WORDS: Final = re.compile(
    r"\b(?:podcast|folge|episode|епізод|подкаст|випуск)\b", re.IGNORECASE
)
_SLIDE_WORDS: Final = re.compile(
    r"\b(?:folie|folien|slide|slides|nächstes kapitel|next slide|слайд\w*)\b", re.IGNORECASE
)


# A speaker saying the recording moves to its next part; the match is a time, never stored as text.
STRUCTURE_CUES: Final[dict[str, re.Pattern[str]]] = {
    "de": re.compile(
        r"\b(?:kapitel\s+(?:\d+|eins|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)"
        r"|(?:nächste[rnms]?|zweite[rnms]?|dritte[rnms]?|letzte[rnms]?)\s+(?:punkt|kapitel|thema|teil)"
        r"|tagesordnungspunkt|kommen wir (?:jetzt |nun )?zu(?:m|r)?\b|weiter geht'?s mit)",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"\b(?:chapter\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"|let'?s move on|moving on to|(?:next|second|third|last)\s+(?:item|topic|point|chapter|part)"
        r"|agenda item|that brings us to)",
        re.IGNORECASE,
    ),
    "uk": re.compile(
        r"(?:перейдемо до|переходимо до|наступн(?:е|ий|а)\s+(?:питання|пункт|тема|розділ|частина)"
        r"|розділ\s+(?:\d+|перший|другий|третій)|пункт порядку денного)",
        re.IGNORECASE,
    ),
}


def structure_cues(turns: Sequence[Any], language: str) -> list[int]:
    """Start times (ms) of the turns where a speaker announces the next part."""
    pattern = STRUCTURE_CUES.get(language)
    if pattern is None:
        return []
    return [int(t.start_ms) for t in turns if pattern.search(t.text)]


def type_cues(
    turns: Sequence[Any], table: Any, adverts: Sequence[tuple[int, int]] = ()
) -> tuple[str | None, dict[str, Any]]:
    """``(podcast_broadcast | lecture_webinar | None, the cues)``.

    Podcast: a show word or jingle, a guest interview, sound-bite clips, an
    advert break. Lecture: one voice with no guest and no clips, slide
    vocabulary. More cues win; a tie is None — the classifier stands."""
    from .roles_table import ADVERT, CLIP, EXPERT, GUEST, INTERVIEWEE

    text = " ".join(t.text for t in turns)
    roles = [s.role for s in table.speakers.values()]
    podcast = {
        "show": bool(_SHOW_WORDS.search(text)),
        "guest": any(r in (GUEST, INTERVIEWEE, EXPERT) for r in roles),
        "clips": CLIP in roles,
        "advert": bool(adverts),
    }
    voices = [r for r in roles if r not in (CLIP, ADVERT)]
    lecture = {
        "single_voice": len(voices) == 1 and not podcast["guest"] and not podcast["clips"],
        "slides": bool(_SLIDE_WORDS.search(text)),
    }
    p_score, l_score = sum(podcast.values()), sum(lecture.values())
    verdict = PODCAST if p_score > l_score else LECTURE if l_score > p_score else None
    cues = {
        "podcast": sorted(k for k, v in podcast.items() if v),
        "lecture": sorted(k for k, v in lecture.items() if v),
        "verdict": verdict or "tie",
    }
    return verdict, cues
