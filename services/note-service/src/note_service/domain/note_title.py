"""A meeting note names itself: the ``note.generate`` job asks the model for a title.

Only a placeholder (``title_source = default``) is replaced, checked again under
the row lock so a concurrent rename wins; the write flips the source to ``ai``
so it happens once; too few real words keep the placeholder; every failure is
logged and swallowed, never at the note's expense.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from functools import cache
from importlib import resources
from typing import Any, Final
from uuid import UUID

from note_models import NoteStatus

from . import notes_repository as repo
from .meeting_doc import doclint, prompts, support, windows

logger = logging.getLogger(__name__)

DEFAULT: Final = "default"
AI: Final = "ai"
USER: Final = "user"

# Fewer real words than this and the placeholder stays.
MIN_MEANINGFUL_WORDS: Final = 12
# Sampled across the whole recording, not the first minutes.
SAMPLE_WORDS: Final = 1_200
_EXCERPTS: Final = 3

MAX_TITLE_WORDS: Final = 10
MAX_TITLE_CHARS: Final = doclint.TITLE_MAX_CHARS
MAX_TOKENS: Final = 60
TIMEOUT_SECONDS: Final = 45.0

_WORD = re.compile(r"\w+", re.UNICODE)
# Words that carry no topic; only decides "is there anything here".
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
    "sentence. The excerpts come from its beginning, middle and end; a second block, when "
    "there is one, lists themes and facts found across the whole recording.\n"
    "- Prefer specific nouns (products, projects, customers, subjects) over generic labels.\n"
    "- 30 to 80 characters, 3 to 10 words, sentence case. Name the subject and, when "
    "the conversation has one, the angle; at most one colon.\n"
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
    """The transcript, or when long three excerpts (opening, middle, end), so the
    title can name the whole recording."""
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
    if len(text) > MAX_TITLE_CHARS:
        # At a word, never mid-word.
        text = text[: MAX_TITLE_CHARS + 1].rsplit(" ", 1)[0].rstrip(" ,:;—-")
    return text.strip()


def _answer_text(answer: Any) -> str:
    text = getattr(answer, "text", answer)
    text = text if isinstance(text, str) else str(text)
    try:
        parsed = json.loads(text)
    except ValueError:
        # A backend that ignored the schema and answered in prose.
        return text
    return str(parsed.get("title") or "") if isinstance(parsed, dict) else ""


# Context for the title call: the note's themes and its most specific verified facts.
CONTEXT_FACTS: Final = 5


def context_block(themes: Sequence[str], facts: Sequence[str]) -> str:
    """The note's themes and top facts, as data — verified text only."""
    lines = []
    if themes:
        lines.append("Themes: " + "; ".join(t.strip() for t in themes if t.strip()))
    lines += [f"- {f.strip()}" for f in facts[:CONTEXT_FACTS] if f.strip()]
    return "\n".join(lines)


async def suggest(
    provider: Any,
    result: dict[str, Any],
    *,
    language: str,
    themes: Sequence[str] = (),
    facts: Sequence[str] = (),
) -> str | None:
    """A title for this transcript, or None (not enough said, no topic, model failed). Never raises."""
    if meaningful_word_count(result) < MIN_MEANINGFUL_WORDS:
        return None
    system = _SYSTEM.format(language=language_name(language), guard=prompts.guard(language))
    prompt = f"{prompts.DATA_OPEN}\n{sample(result)}\n{prompts.DATA_CLOSE}"
    found = context_block(themes, facts)
    if found:
        prompt += f"\n\n{prompts.DATA_OPEN}\n{found}\n{prompts.DATA_CLOSE}"
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
    reason = unsupported(title, result, language=language)
    if reason is not None:
        logger.info("note_title.skipped", extra={"reason": reason})
        return None
    return title


# A title word counts as said when a transcript word shares this many first letters.
_NAME_PREFIX: Final = 4
# Shortest part a German compound is split into ("Lehrer|mangel").
_COMPOUND_PART: Final = 3
# German joins compound parts with these ("Bildung|s|notstand").
_LINKS: Final = ("s", "es", "n", "en", "e")


@cache
def _lexicon(name: str) -> frozenset[str]:
    """A Tatoeba frequency list from ``asr_models/resources`` (CC-BY 2.0 FR); empty when absent."""
    try:
        text = resources.files("asr_models").joinpath("resources", name).read_text("utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        return frozenset()
    return frozenset(line.strip() for line in text.splitlines() if line.strip())


def _common(word: str, language: str, heads: set[str], depth: int = 0) -> bool:
    """A common word of the language (or, in German, a compound of common and said
    words): a topic, not a new name."""
    lang = (language or "").split("-")[0].lower()
    if word in _lexicon("names.txt"):
        return False
    if word in _lexicon(f"freq_{lang}.txt"):
        return True
    if lang != "de" or depth > 2:
        return False
    for i in range(_COMPOUND_PART, len(word) - _COMPOUND_PART + 1):
        head, rest = word[:i], word[i:]
        stems = [head] + [head[: -len(s)] for s in _LINKS if head.endswith(s)]
        if not any(
            len(s) >= _COMPOUND_PART
            and s not in _lexicon("names.txt")
            and (s in _lexicon("freq_de.txt") or s[:_NAME_PREFIX] in heads)
            for s in stems
        ):
            continue
        if rest[:_NAME_PREFIX] in heads and len(rest) >= _NAME_PREFIX:
            return True
        if _common(rest, lang, heads, depth + 1):
            return True
    return False


def unsupported(title: str, result: dict[str, Any], *, language: str = "") -> str | None:
    """Why this title may not be written, or None: ``example`` (a copied prompt
    example), ``unsupported`` (a name the transcript never says), or a lint fault."""
    if prompts.echoes_example(title):
        return "example"
    said = " ".join(_spoken(result))
    heads = {w[:_NAME_PREFIX] for w in _WORD.findall(said.casefold()) if len(w) >= _NAME_PREFIX}
    language = language or str(result.get("language") or "")
    # `new_names` skips a sentence's first word, so the title is read as a clause.
    for name in support.new_names(f"re {title}", said):
        words = [w for w in _WORD.findall(name.casefold()) if len(w) >= _NAME_PREFIX]
        if any(w[:_NAME_PREFIX] not in heads and not _common(w, language, heads) for w in words):
            logger.info("note_title.new_name", extra={"word": name})
            return "unsupported"
    # The title form rules; a failing suggestion is not applied (``title_skipped: lint``).
    ctx = doclint.LintContext(language="en", speech_ms=0)
    if [f for f in doclint.title_faults(title, ctx) if f != "name"]:
        return "lint"
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
    """Put ``title`` on the note if it still has its placeholder, under the note's
    row lock from check to write. Returns whether anything was written."""
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
