"""The note writer (Sprint P1): prompt + template + instruction text → model → Markdown.

One model call per window of the transcript (continuations carry the note so far) and
one merge call when there was more than one window. The Markdown comes back as the
model wrote it; the only line code ever adds is the merge-failed status line. Nothing
here touches the database: :func:`write` takes what the job loaded and returns the text
and the numbers about the run.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from typing import Any, Final, Literal

from models import ErrorKind, ProviderError

from . import prompts

logger = logging.getLogger(__name__)

WINDOW_MINUTES: Final = 25
WORDS_PER_MINUTE: Final = 30
WORDS_MIN: Final = 150
WORDS_MAX: Final = 1_500
# What a call may return when the workspace sets no cap (N0 `max_output_tokens`).
DEFAULT_MAX_OUTPUT_TOKENS: Final = 4_096
MERGE_RETRIES: Final = 1

TEMPLATES: Final[tuple[str, ...]] = (
    "meeting",
    "client_call",
    "interview",
    "broadcast",
    "public_meeting",
    "memo",
)
AUTO: Final = "auto"
NoteTemplate = Literal[
    "meeting", "client_call", "interview", "broadcast", "public_meeting", "memo", "auto"
]
# The author's meeting type → the template file; `auto` lets the model choose.
TEMPLATE_FOR_TYPE: Final[dict[str, str]] = {
    "team": "meeting",
    "client": "client_call",
    "sales": "client_call",
    "interview": "interview",
    "one_on_one": "meeting",
    "broadcast": "broadcast",
    "memo": "memo",
}
# A note's template code (the seed templates) → the template file, when the person chose it.
TEMPLATE_FOR_CODE: Final[dict[str, str]] = {
    "meeting_notes": "meeting",
    "project_update": "meeting",
    "one_on_one": "meeting",
    "client_call": "client_call",
    "sales_call": "client_call",
    "interview_debrief": "interview",
    "broadcast": "broadcast",
    "voice_memo": "memo",
}


DEFAULT_INSTRUCTIONS: Final = "instructions.default.md"


def template_name_for(
    meeting_type: str | None,
    template_code: str | None,
    chosen: bool,
    note_template: str | None = None,
) -> str:
    """The template the note names (P2) wins; then the author's meeting type; then a
    template the person chose at creation; else ``auto``."""
    if note_template and note_template != AUTO and note_template in TEMPLATES:
        return note_template
    if meeting_type and meeting_type != "auto" and meeting_type in TEMPLATE_FOR_TYPE:
        return TEMPLATE_FOR_TYPE[meeting_type]
    if chosen and template_code:
        code = template_code.casefold()
        for prefix, name in sorted(TEMPLATE_FOR_CODE.items(), key=lambda kv: -len(kv[0])):
            if code.startswith(prefix):
                return name
    return AUTO


def template_text(name: str, language: str, override: str | None = None) -> str:
    """The workspace's own text when it has one (P2), else the file that ships, read on
    every call (hot-reloadable); English when the language has no copy."""
    if override and override.strip():
        return override.strip()
    folder = resources.files(__package__).joinpath("writer_templates")
    for lang in (prompts.language_of(language), "en"):
        path = folder.joinpath(f"{name}.{lang}.md")
        if path.is_file():
            return path.read_text("utf-8").strip()
    raise FileNotFoundError(f"writer template {name!r}")


def target_words(speech_minutes: float) -> int:
    return int(min(WORDS_MAX, max(WORDS_MIN, round(WORDS_PER_MINUTE * speech_minutes))))


def mmss(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def render_turn(turn: Any) -> str:
    return f"[{mmss(turn.start_ms)}] {turn.display_name}: {turn.text}"


def windows(turns: list[Any], max_minutes: int = WINDOW_MINUTES) -> list[list[Any]]:
    """The turns cut into windows of at most ``max_minutes`` of recording, at turn
    boundaries; a single turn longer than the window is a window of its own."""
    out: list[list[Any]] = []
    current: list[Any] = []
    limit = max_minutes * 60_000
    for turn in turns:
        if current and int(turn.end_ms) - int(current[0].start_ms) > limit:
            out.append(current)
            current = []
        current.append(turn)
    if current:
        out.append(current)
    return out


def speech_minutes(turns: list[Any]) -> float:
    if not turns:
        return 0.0
    return max(0, int(turns[-1].end_ms) - int(turns[0].start_ms)) / 60_000


def _speakers(turns: list[Any]) -> int:
    return (
        len(
            {
                t.speaker_label or t.speaker_name
                for t in turns
                if (t.speaker_label or t.speaker_name)
            }
        )
        or 1
    )


def system_text(language: str) -> str:
    lang = prompts.language_of(language)
    return prompts.WRITER[lang].format(language=prompts.LANGUAGE_NAMES[lang])


def default_instructions() -> str:
    """The rules that ship (``writer_templates/instructions.default.md``), read on every
    call like the templates; a workspace's saved text replaces them whole."""
    folder = resources.files(__package__).joinpath("writer_templates")
    return folder.joinpath(DEFAULT_INSTRUCTIONS).read_text("utf-8").strip()


def instructions_text(
    saved: str | None, *, words: int, recording_date: date | None, language: str
) -> str:
    """The instructions the prompt carries: the workspace's text when it has one, else the
    default file, with ``{{words}}``, ``{{date}}`` and ``{{language}}`` filled in where the
    text uses them (a text without placeholders is sent as it is)."""
    lang = prompts.language_of(language)
    text = (saved or "").strip() or default_instructions()
    return (
        text.replace("{{words}}", str(words))
        .replace(
            "{{date}}", recording_date.isoformat() if recording_date else prompts.UNKNOWN_DATE[lang]
        )
        .replace("{{language}}", prompts.LANGUAGE_NAMES[lang])
    )


def build_prompt(
    turns: list[Any],
    *,
    instruction_text: str | None,
    template: str,
    template_name: str,
    language: str,
    recording_date: date | None,
    words: int | None = None,
) -> tuple[str, str]:
    """``(system, user)`` for the first (or only) window of a recording."""
    lang = prompts.language_of(language)
    minutes = speech_minutes(turns)
    system = system_text(lang)
    user = prompts.USER[lang].format(
        instructions=instructions_text(
            instruction_text,
            words=words or target_words(minutes),
            recording_date=recording_date,
            language=lang,
        ),
        template_name=template_name,
        template=template,
        minutes=max(1, round(minutes)),
        speakers=_speakers(turns),
        transcript="\n".join(render_turn(t) for t in turns),
    )
    return system, user


def continuation_prompt(turns: list[Any], *, note_so_far: str, language: str) -> str:
    lang = prompts.language_of(language)
    return prompts.CONTINUATION[lang].format(
        note=note_so_far,
        minutes=max(1, round(speech_minutes(turns))),
        transcript="\n".join(render_turn(t) for t in turns),
    )


def merge_prompt(parts: list[str], *, template: str, template_name: str, language: str) -> str:
    lang = prompts.language_of(language)
    rendered = "\n\n".join(
        f"{prompts.PART_HEADER[lang].format(n=n, total=len(parts))}\n{part}"
        for n, part in enumerate(parts, 1)
    )
    return prompts.MERGE[lang].format(
        template_name=template_name, template=template, parts=rendered
    )


def merge_failed_text(parts: list[str], language: str) -> str:
    """The only text code adds to a note: a status line, then the parts in order."""
    lang = prompts.language_of(language)
    return "\n\n".join([prompts.MERGE_FAILED[lang], *parts])


@dataclass(slots=True)
class Written:
    text: str
    parts: list[str]
    backend: str | None = None
    model_id: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)


async def write(
    turns: list[Any],
    *,
    provider: Any,
    language: str,
    recording_date: date | None,
    instruction_text: str | None,
    template_name: str,
    template_override: str | None = None,
    temperature: float = 0.0,
    max_output_tokens: int | None = None,
    done_parts: list[str] | None = None,
    on_part: Callable[[list[str]], Any] | None = None,
) -> Written:
    """The note for ``turns``: one call per window, continuations carrying the note so
    far, one merge call when there was more than one window. ``done_parts`` are window
    outputs a crashed earlier attempt already got (cached by the job); ``on_part`` is
    called with every part finished so far, so the job can cache them.

    A ``ProviderError`` after the provider's own backoff propagates: the job runner
    retries the job, and after its attempts the generation fails."""
    lang = prompts.language_of(language)
    template = template_text(template_name, lang, template_override)
    total_minutes = speech_minutes(turns)
    words = target_words(total_minutes)
    max_tokens = int(max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS)
    chunks = windows(turns)
    parts: list[str] = list(done_parts or [])[: len(chunks)]
    system = system_text(lang)
    calls = tokens_in = tokens_out = 0
    latency_ms = 0
    backend = model_id = None
    started = time.monotonic()

    async def call(user: str) -> str:
        nonlocal calls, tokens_in, tokens_out, latency_ms, backend, model_id
        result = await provider.complete(
            user, None, max_tokens=max_tokens, temperature=temperature, system=system
        )
        calls += 1
        tokens_in += int(result.input_tokens or 0)
        tokens_out += int(result.output_tokens or 0)
        latency_ms += int(result.latency_ms or 0)
        backend = getattr(result, "backend", None) or backend
        model_id = getattr(result, "model_id", None) or model_id
        return str(result.text or "")

    for index in range(len(parts), len(chunks)):
        chunk = chunks[index]
        if index == 0:
            _, user = build_prompt(
                chunk,
                instruction_text=instruction_text,
                template=template,
                template_name=template_name,
                language=lang,
                recording_date=recording_date,
                words=words,
            )
        else:
            user = continuation_prompt(chunk, note_so_far=parts[-1], language=lang)
        parts.append(await call(user))
        if on_part is not None:
            await on_part(list(parts))

    merge_failed = False
    if len(parts) == 1:
        text = parts[0]
    else:
        user = merge_prompt(parts, template=template, template_name=template_name, language=lang)
        text = ""
        for attempt in range(MERGE_RETRIES + 1):
            try:
                text = await call(user)
                break
            except ProviderError as exc:
                if attempt >= MERGE_RETRIES or exc.kind is ErrorKind.AUTH:
                    merge_failed = True
                    logger.warning("writer.merge_failed", extra={"kind": str(exc.kind)})
        if merge_failed:
            text = merge_failed_text(parts, lang)

    return Written(
        text=text,
        parts=parts,
        backend=backend,
        model_id=model_id,
        stats={
            "model": model_id,
            "backend": backend,
            "windows": len(chunks),
            "calls": calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "wall_ms": int((time.monotonic() - started) * 1000),
            "words": len(text.split()),
            "target_words": words,
            "speech_minutes": round(total_minutes, 1),
            "template": template_name,
            "template_source": "workspace" if template_override else "builtin",
            "prompt_version": prompts.PROMPT_VERSION,
            "prompt_fingerprint": prompts.fingerprint(),
            "merge_failed": merge_failed,
        },
    )
