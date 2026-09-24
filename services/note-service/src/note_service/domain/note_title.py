"""A meeting note names itself (0057).

A recording opens its note with a placeholder title — the template name
and the date — because at that moment nothing has been heard. Once the
transcript is in, the ``note.generate`` job asks the model for a short
title in the language that was spoken, and puts it on the note.

Four rules, and each is enforced here rather than hoped for:

* **Only a placeholder is replaced.** ``notes.title_source`` must still be
  ``default`` — checked before the model is asked (a cheap skip) and again
  under the note's row lock just before the write, so a rename that
  landed while the model was thinking wins. A person's title, and a title
  this job already wrote, are never touched.
* **Once.** The write flips the source to ``ai``; a second run of the same
  job, a regenerate, or a crash-and-retry finds nothing to do.
* **Not from nothing.** A recording with too few real words keeps its
  placeholder, and the model may answer "no topic" — a made-up subject
  on a microphone test is worse than a date.
* **Never at the note's expense.** Every failure here is logged and
  swallowed: the note, the transcript and the rest of the generation go
  on exactly as if this module did not exist.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Final
from uuid import UUID

from note_models import NoteStatus

from . import notes_repository as repo
from .meeting_doc import prompts, support, windows

logger = logging.getLogger(__name__)

DEFAULT: Final = "default"
AI: Final = "ai"
USER: Final = "user"

# Fewer real words than this and there is no topic to name: a greeting,
# "can you hear me", a silent take. The placeholder stays.
MIN_MEANINGFUL_WORDS: Final = 12
# How much of the meeting the model reads. Taken from across the whole
# recording, not the first minutes, so the title is the meeting's main
# subject rather than whatever was said while people were joining.
SAMPLE_WORDS: Final = 1_200
_EXCERPTS: Final = 3

MAX_TITLE_WORDS: Final = 10
MAX_TITLE_CHARS: Final = 120
MAX_TOKENS: Final = 60
TIMEOUT_SECONDS: Final = 45.0

_WORD = re.compile(r"\w+", re.UNICODE)
# Words that carry no topic in any language we transcribe. Deliberately
# short: this only decides "is there anything here", the model decides
# what it is.
_FILLER: Final = frozenset(
    [
        "hi",
        "hello",
        "hey",
        "um",
        "uh",
        "uhm",
        "hmm",
        "mm",
        "ok",
        "okay",
        "yeah",
        "yes",
        "no",
        "so",
        "well",
        "right",
        "can",
        "you",
        "hear",
        "me",
        "testing",
        "test",
        "one",
        "two",
        "three",
        "is",
        "this",
        "on",
        "the",
        "a",
        "and",
        "hallo",
        "ja",
        "nein",
        "also",
        "äh",
        "ähm",
        "gut",
        "hören",
        "sie",
        "mich",
        "привіт",
        "так",
        "ні",
        "ну",
        "добре",
        "чуєте",
        "мене",
        "алло",
    ]
)

_LANGUAGE_NAMES: Final[dict[str, str]] = {
    "en": "English",
    "de": "German",
    "uk": "Ukrainian",
    "ru": "Russian",
    "pl": "Polish",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
}

SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title"],
    "properties": {"title": {"type": "string", "maxLength": MAX_TITLE_CHARS}},
}

_SYSTEM: Final = (
    "You name notes. Read a meeting transcript and write a concise title for the note.\n"
    "- Name the primary topic or purpose of the conversation as a whole, not its first "
    "sentence.\n"
    "- Prefer specific nouns (products, projects, customers, subjects) over generic labels.\n"
    "- 3 to 8 words.\n"
    "- No quotation marks, no date or time, no trailing punctuation.\n"
    '- Do not start with "Meeting about", "Discussion about", "Note about" or the like '
    "unless it genuinely makes the title clearer.\n"
    "- Write the title in {language}, the language the people speak.\n"
    "- If the transcript has no real topic (greetings, a microphone test, silence), "
    "answer with an empty title.\n"
    'Answer only with JSON: {{"title": "..."}}\n\n'
    "{guard}"
)

# What a model sometimes wraps a title in, however it is asked.
_PREFIX = re.compile(r"^\s*(title|titel|назва)\s*[:：-]\s*", re.IGNORECASE)
_QUOTES = "\"'“”„«»‘’`"
_NO_TOPIC = frozenset({"none", "null", "n/a", "untitled", "no topic"})


def language_name(code: str) -> str:
    code = (code or "").split("-")[0].lower()
    return _LANGUAGE_NAMES.get(code, code or "the language of the transcript")


def _spoken(result: dict[str, Any]) -> list[str]:
    """Every word said, in order, without speaker names or timings."""
    words: list[str] = []
    for turn in windows.turns_from_result(result):
        words.extend(turn.text.split())
    if not words and result.get("text"):
        words = str(result["text"]).split()
    return words


def meaningful_word_count(result: dict[str, Any]) -> int:
    count = 0
    for word in _spoken(result):
        for token in _WORD.findall(word.casefold()):
            if len(token) > 1 and not token.isdigit() and token not in _FILLER:
                count += 1
    return count


def sample(result: dict[str, Any], *, budget: int = SAMPLE_WORDS) -> str:
    """The transcript, or evenly spread excerpts of it when it is long."""
    words = _spoken(result)
    if len(words) <= budget:
        return " ".join(words)
    size = budget // _EXCERPTS
    step = (len(words) - size) / (_EXCERPTS - 1)
    parts = [" ".join(words[round(i * step) : round(i * step) + size]) for i in range(_EXCERPTS)]
    return " … ".join(parts)


def clean(raw: str) -> str:
    """The model's answer as a title, or "" when it is not one."""
    text = " ".join((raw or "").split())
    text = _PREFIX.sub("", text).strip().strip(_QUOTES).strip()
    text = text.rstrip(".!?;:,…").strip().strip(_QUOTES).strip()
    if not text or text.casefold() in _NO_TOPIC or not _WORD.search(text):
        return ""
    words = text.split()
    if len(words) > MAX_TITLE_WORDS:
        text = " ".join(words[:MAX_TITLE_WORDS])
    return text[:MAX_TITLE_CHARS].strip()


def _answer_text(answer: Any) -> str:
    text = getattr(answer, "text", answer)
    text = text if isinstance(text, str) else str(text)
    try:
        parsed = json.loads(text)
    except ValueError:
        # A backend that ignored the schema and answered in prose.
        return text
    return str(parsed.get("title") or "") if isinstance(parsed, dict) else ""


async def suggest(provider: Any, result: dict[str, Any], *, language: str) -> str | None:
    """A title for this transcript, or None: not enough said, no topic,
    or the model failed. Never raises."""
    if meaningful_word_count(result) < MIN_MEANINGFUL_WORDS:
        return None
    system = _SYSTEM.format(language=language_name(language), guard=prompts.guard(language))
    prompt = f"{prompts.DATA_OPEN}\n{sample(result)}\n{prompts.DATA_CLOSE}"
    try:
        answer = await asyncio.wait_for(
            provider.complete(
                prompt, SCHEMA, max_tokens=MAX_TOKENS, temperature=0.0, system=system
            ),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 — a title is never worth a failed note
        logger.warning("note_title.model_failed", exc_info=True)
        return None
    title = clean(_answer_text(answer))
    if not title:
        return None
    reason = unsupported(title, result)
    if reason is not None:
        logger.info("note_title.skipped", extra={"reason": reason})
        return None
    return title


# A title word counts as said when a transcript word shares this many
# first letters with it: English titles are title-cased, so "Planning"
# over a transcript that says "plan" is a topic word, not a new name.
_NAME_PREFIX: Final = 4


def unsupported(title: str, result: dict[str, Any]) -> str | None:
    """Why this title may not be written, or None (Summary Engine v2, Q6).

    ``example`` — it repeats a prompt example: the model copied its
    instructions. ``unsupported`` — it names someone or something the
    transcript never says. Same rules as the document's lines."""
    if prompts.echoes_example(title):
        return "example"
    said = " ".join(_spoken(result))
    heads = {w[:_NAME_PREFIX] for w in _WORD.findall(said.casefold()) if len(w) >= _NAME_PREFIX}
    # `new_names` never counts a sentence's first word; a title's first
    # word is often the name, so the title is read as a clause.
    for name in support.new_names(f"re {title}", said):
        words = [w for w in _WORD.findall(name.casefold()) if len(w) >= _NAME_PREFIX]
        if any(w[:_NAME_PREFIX] not in heads for w in words):
            return "unsupported"
    return None


async def source_of(conn: Any, *, note_id: UUID) -> str | None:
    value = await conn.fetchval("SELECT title_source FROM notes WHERE id = $1", note_id)
    return str(value) if value is not None else None


async def apply(
    conn: Any,
    *,
    note_id: UUID,
    title: str,
    requested_by: UUID,
    generation_id: UUID,
) -> bool:
    """Put ``title`` on the note if it still has its placeholder.

    Holds the note's row lock — the same one every autosave takes — from
    the check to the write, so a rename cannot slip in between. Returns
    whether anything was written.
    """
    note = await repo.lock_note_for_update(conn, note_id=note_id)
    if note is None or note.status != NoteStatus.DRAFT:
        return False
    if await source_of(conn, note_id=note_id) != DEFAULT:
        return False
    version = await repo.fetch_version(conn, version_id=note.current_version_id)
    if version is None or version.content.title == title:
        return False
    await repo.append_version(
        conn,
        note_id=note_id,
        expected_version=note.current_version_number,
        new_content=version.content.model_copy(update={"title": title}),
        created_by=requested_by,
        diff_jsonb={"source": "generation"},
        extra_metadata={
            "source": "generation",
            "generation_id": str(generation_id),
            "step": "title",
        },
        title_source=AI,
    )
    return True


__all__ = [
    "AI",
    "DEFAULT",
    "MIN_MEANINGFUL_WORDS",
    "USER",
    "apply",
    "clean",
    "meaningful_word_count",
    "sample",
    "source_of",
    "suggest",
]
