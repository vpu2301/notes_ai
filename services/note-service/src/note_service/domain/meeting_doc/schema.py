"""What the model is allowed to say back.

Two schemas, one per model step. Both are narrow on purpose: a
schema-constrained response is the first line of defence against a
transcript that contains "ignore previous instructions", and a small
enum is easier for a small model than an open field.

Nothing here decides whether a fact is TRUE — :mod:`verify` does that,
in code, against the transcript. These types only describe the shape the
model must answer in.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

# ── Fact kinds ──────────────────────────────────────────────────────

DECISION: Final = "decision"
ACTION: Final = "action"
OPEN_QUESTION: Final = "open_question"
KEY_POINT: Final = "key_point"
AGENDA_ITEM: Final = "agenda_item"
RISK: Final = "risk"
NEXT_MEETING: Final = "next_meeting"

# Sprint 36 adds `completion` to the generic set: the engine has to be
# able to say "that task from last week is done", with the words.
COMPLETION: Final = "completion"
JUDGEMENT: Final = "judgement"

FACT_KINDS: Final[tuple[str, ...]] = (
    DECISION,
    ACTION,
    OPEN_QUESTION,
    KEY_POINT,
    AGENDA_ITEM,
    RISK,
    NEXT_MEETING,
    COMPLETION,
)

MAX_FACTS_PER_WINDOW: Final = 12
MAX_FACT_CHARS: Final = 240
MAX_TOPIC_TITLE_CHARS: Final = 80
MAX_SUMMARY_SENTENCES: Final = 5
MIN_TOPICS: Final = 2
# Fewer verified facts than this and the conversation is one list.
MIN_FACTS_FOR_TOPICS: Final = 5
MAX_TOPICS: Final = 8
MAX_BULLETS_PER_TOPIC: Final = 5
# Short enough to be a quote, long enough to be findable.
MIN_QUOTE_WORDS: Final = 3
MAX_THEMES: Final = 7
MAX_KEY_POINTS: Final = 6
MAX_NOISE_PER_WINDOW: Final = 8
# A flagged turn above this share of the window's words is the recording, not noise.
MAX_NOISE_SHARE: Final = 0.5

# How sure the speaker was. The text has to carry it ("was estimated at",
# "was described as"); the field makes the model decide it explicitly,
# which is what keeps an estimate from becoming a fact in the notes.
CERTAINTIES: Final[tuple[str, ...]] = (
    "fact",
    "estimate",
    "prediction",
    "opinion",
    "proposal",
    "allegation",
)
# Why a turn is not part of the conversation. A closed vocabulary: the
# transcript note is rendered from it in code, never from model prose.
NOISE_REASONS: Final[tuple[str, ...]] = (
    "background",
    "other_language",
    "artifact",
    "duplicate",
    "unrelated",
)
MAX_QUOTE_WORDS: Final = 30


class Fact(BaseModel):
    """One thing the model claims was said."""

    model_config = ConfigDict(extra="ignore")

    kind: str
    text: str = Field(max_length=MAX_FACT_CHARS)
    owner: str | None = None
    due_text: str | None = None
    """True when someone actually took this on, as opposed to the room
    agreeing that somebody ought to."""
    explicit: bool = False
    """Verbatim words from the transcript. The whole design rests on
    this: a fact whose quote cannot be found is dropped, not shown."""
    quote: str = ""
    """Which numbered turn the quote came from."""
    turn: int = -1
    """Sprint 36 — for `completion`: WHICH carried item this finishes, as
    its number in the list the prompt was given. Never a free-text
    reference: the engine may only point at an item we already had."""
    refers_to: int | None = None
    """For `judgement`: which typed field this is a suggestion for. The
    value goes in `text`. Never written to the field — only offered."""
    field: str | None = None
    """How sure the speaker was; see ``CERTAINTIES``."""
    certainty: str | None = None


class NoiseTurn(BaseModel):
    """A turn that is not part of the conversation, and why."""

    model_config = ConfigDict(extra="ignore")

    turn: int
    reason: str = "unrelated"


class ExtractOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic_title: str = Field(default="", max_length=MAX_TOPIC_TITLE_CHARS)
    facts: list[Fact] = Field(default_factory=list)
    noise: list[NoiseTurn] = Field(default_factory=list)


class ContextOut(BaseModel):
    """The conversation as a whole, read off its verified facts."""

    model_config = ConfigDict(extra="ignore")

    conversation_type: str = Field(default="", max_length=60)
    subject: str = Field(default="", max_length=160)
    themes: list[str] = Field(default_factory=list)
    """One sentence for the top of the notes: what kind of conversation,
    about what, covering which themes."""
    framing: str = Field(default="", max_length=400)
    """The facts a reader must know first."""
    key_fact_ids: list[str] = Field(default_factory=list)


class SummarySentence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentence: str = Field(max_length=400)
    fact_ids: list[str] = Field(default_factory=list)


class TopicBullet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(max_length=MAX_FACT_CHARS)
    fact_ids: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(max_length=MAX_TOPIC_TITLE_CHARS)
    fact_ids: list[str] = Field(default_factory=list)
    bullets: list[TopicBullet] = Field(default_factory=list)


class ReduceOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: list[SummarySentence] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)


# ── JSON schemas handed to the provider ─────────────────────────────
#
# Written out rather than generated from the models: the provider sends
# these to a constrained-decoding backend, and a hand-written schema is
# what we can keep small and explicit. The Pydantic models above parse
# whatever comes back, so a backend that ignores the schema still cannot
# produce a shape the pipeline chokes on.


def extract_schema(
    kinds: tuple[str, ...] = FACT_KINDS,
    *,
    judgement_fields: tuple[str, ...] = (),
    carried_items: int = 0,
) -> dict[str, Any]:
    """The extraction schema for ONE family.

    Built per call rather than fixed, because the enum is the main lever
    on a small model's accuracy: a sales call chooses between ten kinds
    it might actually see, not the union of every kind in the product.
    Turning a kind off for a family whose precision is poor is deleting
    an entry in `types.py` — configuration, not code.
    """
    properties: dict[str, Any] = {
        "kind": {"type": "string", "enum": list(kinds)},
        "text": {"type": "string", "maxLength": MAX_FACT_CHARS},
        "owner": {"type": ["string", "null"], "maxLength": 60},
        "due_text": {"type": ["string", "null"], "maxLength": 120},
        "explicit": {"type": "boolean"},
        "quote": {"type": "string", "maxLength": 400},
        "turn": {"type": "integer"},
        "certainty": {"type": ["string", "null"], "enum": [*CERTAINTIES, None]},
    }
    if carried_items:
        # A completion may only point at an item we already had, by its
        # number in the list the prompt was given — never by free text.
        properties["refers_to"] = {
            "type": ["integer", "null"],
            "minimum": 1,
            "maximum": carried_items,
        }
    if judgement_fields:
        properties["field"] = {
            "type": ["string", "null"],
            "enum": [*judgement_fields, None],
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["topic_title", "facts", "noise"],
        "properties": {
            "topic_title": {"type": "string", "maxLength": MAX_TOPIC_TITLE_CHARS},
            "facts": {
                "type": "array",
                "maxItems": MAX_FACTS_PER_WINDOW,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "text", "quote", "turn", "explicit"],
                    "properties": properties,
                },
            },
            "noise": {
                "type": "array",
                "maxItems": MAX_NOISE_PER_WINDOW,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["turn", "reason"],
                    "properties": {
                        "turn": {"type": "integer"},
                        "reason": {"type": "string", "enum": list(NOISE_REASONS)},
                    },
                },
            },
        },
    }


EXTRACT_SCHEMA: Final[dict[str, Any]] = extract_schema()

REDUCE_TOPICS_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topics"],
    "properties": {
        "topics": {
            "type": "array",
            "maxItems": MAX_TOPICS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "bullets"],
                "properties": {
                    "title": {"type": "string", "maxLength": MAX_TOPIC_TITLE_CHARS},
                    "fact_ids": {"type": "array", "items": {"type": "string"}},
                    "bullets": {
                        "type": "array",
                        "maxItems": MAX_BULLETS_PER_TOPIC,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["text", "fact_ids"],
                            "properties": {
                                "text": {"type": "string", "maxLength": MAX_FACT_CHARS},
                                "fact_ids": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}

REDUCE_SUMMARY_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {
        "summary": {
            "type": "array",
            "maxItems": MAX_SUMMARY_SENTENCES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sentence", "fact_ids"],
                "properties": {
                    "sentence": {"type": "string", "maxLength": 400},
                    "fact_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                },
            },
        }
    },
}

REDUCE_CONTEXT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["conversation_type", "subject", "themes", "framing", "key_fact_ids"],
    "properties": {
        "conversation_type": {"type": "string", "maxLength": 60},
        "subject": {"type": "string", "maxLength": 160},
        "themes": {
            "type": "array",
            "maxItems": MAX_THEMES,
            "items": {"type": "string", "maxLength": MAX_TOPIC_TITLE_CHARS},
        },
        "framing": {"type": "string", "maxLength": 400},
        "key_fact_ids": {
            "type": "array",
            "maxItems": MAX_KEY_POINTS,
            "items": {"type": "string"},
        },
    },
}
