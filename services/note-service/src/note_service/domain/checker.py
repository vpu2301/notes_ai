"""The optional check call (Sprint P3, ``MDX_NOTE_CHECK``): one model call per window with
the note's cited lines and the window's transcript; the model names the lines it cannot
find support for and one reason each. A mark, never a deletion: no text changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final

import telemetry

from . import prompts, writer

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS: Final = 1_500
MAX_REASON: Final = 200

CHECK_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["unsupported"],
    "properties": {
        "unsupported": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["line", "reason"],
                "properties": {"line": {"type": "integer"}, "reason": {"type": "string"}},
            },
        }
    },
}


@dataclass(slots=True)
class Checked:
    """``unsupported``: position → the model's reason; counts of what was asked."""

    unsupported: dict[int, str] = field(default_factory=dict)
    items: int = 0
    calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "items": self.items,
            "unsupported": len(self.unsupported),
            "calls": self.calls,
            "failed_calls": self.failed_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


def build_prompt(lines: list[tuple[int, str]], turns: list[Any], language: str) -> tuple[str, str]:
    """``(system, user)``: the numbered lines and the window's transcript."""
    lang = prompts.language_of(language)
    listing = "\n".join(f"{n}. {text}" for n, text in lines)
    transcript = "\n".join(writer.render_turn(t) for t in turns)
    return prompts.CHECK[lang], prompts.CHECK_USER[lang].format(
        lines=listing, transcript=transcript
    )


def _first_turn(row: dict[str, Any]) -> int | None:
    for cite in row.get("cites") or []:
        if str(cite).startswith("turn:"):
            try:
                return int(str(cite)[5:])
            except ValueError:
                continue
    return None


async def check(
    rows: list[dict[str, Any]], turns: list[Any], *, provider: Any, language: str
) -> Checked:
    """Every row with a cite, checked in the window its first cite falls in. A failed
    call costs that window's verdicts, never the note."""
    out = Checked()
    by_turn: dict[int, int] = {}
    for w, window in enumerate(writer.windows(turns)):
        for t in window:
            by_turn[int(t.number)] = w
    grouped: dict[int, list[tuple[int, str]]] = {}
    for row in rows:
        turn = _first_turn(row)
        if turn is None or turn not in by_turn:
            continue
        grouped.setdefault(by_turn[turn], []).append((int(row["position"]), str(row["text"])))
    out.items = sum(len(v) for v in grouped.values())
    windows = writer.windows(turns)
    for w, lines in sorted(grouped.items()):
        numbered = [(i + 1, text) for i, (_pos, text) in enumerate(lines)]
        system, user = build_prompt(numbered, windows[w], language)
        out.calls += 1
        try:
            answer = await telemetry.llm.call(
                "note_check",
                provider,
                lambda user=user, system=system: provider.complete(
                    user, CHECK_SCHEMA, max_tokens=MAX_OUTPUT_TOKENS, temperature=0.0, system=system
                ),
            )
        except Exception:  # noqa: BLE001 — a mark we could not get, never a failed note
            logger.warning("note_check.call_failed", exc_info=True)
            out.failed_calls += 1
            continue
        out.input_tokens += int(getattr(answer, "input_tokens", 0) or 0)
        out.output_tokens += int(getattr(answer, "output_tokens", 0) or 0)
        verdict = answer.json if isinstance(getattr(answer, "json", None), dict) else {}
        for entry in verdict.get("unsupported") or []:
            if not isinstance(entry, dict):
                continue
            try:
                n = int(entry.get("line"))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= len(lines):
                position = lines[n - 1][0]
                reason = " ".join(str(entry.get("reason") or "").split())[:MAX_REASON]
                out.unsupported[position] = reason
    return out
