"""``Ask this note`` — one question, answered by the chat provider over the
note's current content and, when the note came from a recording, its
transcript.

The provider comes from ``libs/models`` (ADR-0046): ``config/models.yaml``
decides which backend answers in this environment; nothing here names a
vendor. The registry is loaded on first use so a dev Mac without a model
server still serves every other note operation, and the provider is kept
per backend name (its HTTP client, semaphore and structured-output probe
are meant to be long-lived).

Text handling: the note's title and sections first, then the transcript,
clipped to ``max_chars`` (the transcript loses its tail, with a marker),
then the conversation so far, then the question. The answer is plain text
in the language of the question.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from models import ChatProvider, Registry, build_chat_provider

logger = logging.getLogger(__name__)

Role = Literal["user", "assistant"]

SYSTEM_PROMPT = (
    "You are the assistant inside a meeting-notes app. The user is looking at one "
    "note, reproduced below together with the transcript it was made from (when there "
    "is one). Answer the user's question from that material only. Quote or paraphrase "
    "what was said; do not invent facts, names or numbers that are not there. If the "
    "material does not contain the answer, say so in one sentence. Reply in the "
    "language the question is written in. Be concise: plain text, short paragraphs or a "
    "short list, no headings."
)

TRUNCATED_MARK = "\n[… transcript shortened …]"


@dataclass(frozen=True, slots=True)
class Turn:
    role: Role
    text: str


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    backend: str
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def build_prompt(
    *,
    title: str,
    code: str,
    sections: list[tuple[str, str]],
    transcript: str,
    history: list[Turn],
    question: str,
    max_chars: int,
) -> str:
    """The user message: note, transcript, conversation so far, question.

    ``sections`` are ``(label, text)`` pairs; empty sections are skipped.
    The note always survives whole (it is the thing being asked about);
    the transcript is what gets clipped when the budget runs out.
    """
    lines: list[str] = [f"# Note: {title.strip() or 'Untitled note'} ({code})"]
    for label, text in sections:
        body = text.strip()
        if body:
            lines.append(f"\n## {label}\n{body}")
    note_block = "\n".join(lines)

    transcript = transcript.strip()
    if transcript:
        room = max_chars - len(note_block) - len(TRUNCATED_MARK) - 64
        if room <= 0:
            transcript = ""
        elif len(transcript) > room:
            transcript = transcript[:room].rstrip() + TRUNCATED_MARK
    transcript_block = f"\n\n# Transcript\n{transcript}" if transcript else ""

    history_block = ""
    if history:
        turns = "\n".join(
            f"{'User' if t.role == 'user' else 'Assistant'}: {t.text.strip()}"
            for t in history
            if t.text.strip()
        )
        if turns:
            history_block = f"\n\n# Conversation so far\n{turns}"

    return f"{note_block}{transcript_block}{history_block}\n\n# Question\n{question.strip()}"


class NoteAsker:
    """Lazily-built registry + one provider per backend name."""

    def __init__(
        self,
        *,
        config_path: str | Path,
        env: str,
        environ: Mapping[str, str],
        max_tokens: int,
        max_chars: int,
    ) -> None:
        self._config_path = config_path
        self._env = env
        self._environ = environ
        self._max_tokens = max_tokens
        self._max_chars = max_chars
        self._registry: Registry | None = None
        self._providers: dict[str, ChatProvider] = {}

    def _provider(self, workspace_id: str) -> ChatProvider:
        if self._registry is None:
            # Only the chat route matters here — validate=False keeps an
            # unrelated (e.g. ASR) misconfiguration from blocking answers.
            self._registry = Registry.load(
                self._config_path, env=self._env, environ=self._environ, validate=False
            )
        resolved = self._registry.resolve(workspace_id, "understand")
        provider = self._providers.get(resolved.name)
        if provider is None:
            provider = build_chat_provider(resolved)
            self._providers[resolved.name] = provider
            logger.info("ask.provider_ready", extra=resolved.log_fields())
        return provider

    async def answer(
        self,
        *,
        workspace_id: str,
        title: str,
        code: str,
        sections: list[tuple[str, str]],
        transcript: str,
        history: list[Turn],
        question: str,
    ) -> Answer:
        """Raises ``models.ConfigError`` / ``models.ProviderError``."""
        provider = self._provider(workspace_id)
        prompt = build_prompt(
            title=title,
            code=code,
            sections=sections,
            transcript=transcript,
            history=history,
            question=question,
            max_chars=self._max_chars,
        )
        result = await provider.complete(
            prompt, None, max_tokens=self._max_tokens, temperature=0.2, system=SYSTEM_PROMPT
        )
        return Answer(
            text=result.text.strip(),
            backend=result.backend,
            model_id=result.model_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
        )

    async def aclose(self) -> None:
        for provider in self._providers.values():
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                logger.debug("ask.provider_close_failed", exc_info=True)
        self._providers.clear()


def section_label(section_key: str, names: Mapping[str, str] | None = None) -> str:
    """The template's section name when known, else the key made readable."""
    if names and section_key in names:
        return names[section_key]
    return section_key.replace("_", " ").strip().capitalize() or section_key


def sections_for_prompt(
    content: Any, names: Mapping[str, str] | None = None
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for section in getattr(content, "sections", None) or []:
        out.append((section_label(section.section_key, names), section.text or ""))
    return out
