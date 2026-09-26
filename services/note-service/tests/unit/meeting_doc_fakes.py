"""A scripted model for whole-pipeline tests (Summary Engine v2, Q1).

``ScriptedProvider`` answers each model step from what it was actually
given — facts quoted from the window it was shown, summaries and topics
citing the fact ids it was shown — and records every prompt and system
string, so a test can assert what the engine sent as well as what it
wrote. Which step is being asked is read off the schema, the same way a
constrained-decoding backend would see it.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]
EVAL_FIXTURES = REPO / "tests" / "fixtures" / "eval" / "notes"

_TURN_LINE = re.compile(r"^\[(?P<turn>\d+)\] [^()\n]*\(\d{2}:\d{2}\): (?P<text>.*)$")
_FACT_LINE = re.compile(r"^(?P<id>[0-9a-f]{16}) \((?P<kind>[a-z_]+), \d{2}:\d{2}\): (?P<text>.*)$")
DATA_BLOCK = re.compile(r"⟦\n(?P<body>.*?)\n⟧", re.DOTALL)


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((EVAL_FIXTURES / f"{name}.json").read_text("utf-8"))


def as_result(meeting: dict[str, Any]) -> dict[str, Any]:
    """A gold file in the result-view shape the worker snapshots."""
    return {
        "language": meeting.get("language", "en"),
        "result_rev": 1,
        "turns": [
            {
                "speaker": t["speaker"],
                "name": None,
                "start_ms": t["t_start_ms"],
                "end_ms": t["t_end_ms"],
                "paragraphs": [t["text"]],
            }
            for t in meeting["transcript"]
        ],
    }


def step_of(schema: dict[str, Any] | None) -> str:
    props = (schema or {}).get("properties", {})
    for key in (
        "facts",
        "conversation_type",
        "topics",
        "summary",
        "corrections",
        "recording_type",
        "figures",
        "people",
        "steps",
    ):
        if key in props:
            return {
                "facts": "extract",
                "conversation_type": "context",
                "corrections": "entities",
                "recording_type": "classify",
            }.get(key, key)
    return "unknown"


def data_blocks(text: str) -> list[str]:
    return [m.group("body") for m in DATA_BLOCK.finditer(text)]


def facts_in(prompt: str) -> list[tuple[str, str, str]]:
    """``[(id, kind, text)]`` from a reduce prompt's facts block."""
    out: list[tuple[str, str, str]] = []
    for body in data_blocks(prompt):
        for line in body.splitlines():
            match = _FACT_LINE.match(line)
            if match:
                out.append((match["id"], match["kind"], match["text"]))
    return out


@dataclass
class _Answer:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def json(self) -> Any:
        return json.loads(self.text)


@dataclass
class ScriptedProvider:
    backend: str = "scripted"
    model_id: str = "scripted"
    """Replace a step's answer: ``{"summary": callable(facts[, system]) -> dict}``.
    ``noise`` adds ``[{turn, reason}]`` to every extract answer."""
    overrides: dict[str, Any] = field(default_factory=dict)
    noise: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, str, str]] = field(default_factory=list)
    schemas: list[dict[str, Any] | None] = field(default_factory=list)

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        *,
        max_tokens: int = 0,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> _Answer:
        step = step_of(schema)
        self.calls.append((step, prompt, system or ""))
        self.schemas.append(schema)
        facts = facts_in(prompt)
        if step in self.overrides:
            override = self.overrides[step]
            # An override may take (facts) or (facts, system) — the latter
            # to answer a strict retry differently from the first call.
            takes_system = len(inspect.signature(override).parameters) > 1
            payload = override(facts, system or "") if takes_system else override(facts)
            return _Answer(json.dumps(payload))
        return _Answer(json.dumps(getattr(self, f"_{step}")(prompt, facts)))

    # ── default answers: grounded in what the step was shown ─────────

    def _extract(self, prompt: str, _facts: list[Any]) -> dict[str, Any]:
        out = []
        for body in data_blocks(prompt):
            for line in body.splitlines():
                match = _TURN_LINE.match(line)
                if not match:
                    continue
                words = match["text"].split()
                if len(words) < 6:
                    continue
                out.append(
                    {
                        "kind": "key_point",
                        "text": " ".join(words[:12]),
                        "quote": " ".join(words[:6]),
                        "turn": int(match["turn"]),
                        "explicit": False,
                        "certainty": "fact",
                    }
                )
        return {"topic_title": "", "facts": out[:24], "noise": list(self.noise)}

    def _context(self, _prompt: str, facts: list[tuple[str, str, str]]) -> dict[str, Any]:
        return {
            "conversation_type": "meeting",
            "subject": "",
            "themes": [],
            "framing": "",
            "key_fact_ids": [fid for fid, _k, _t in facts[:2]],
        }

    def _topics(self, _prompt: str, facts: list[tuple[str, str, str]]) -> dict[str, Any]:
        half = max(1, len(facts) // 2)
        groups = [facts[:half], facts[half:]]
        return {
            "topics": [
                {
                    "title": f"Part {n}",
                    "fact_ids": [fid for fid, _k, _t in group],
                    "bullets": [{"text": text, "fact_ids": [fid]} for fid, _k, text in group[:3]],
                }
                for n, group in enumerate(groups, 1)
                if group
            ]
        }

    def _figures(self, _prompt: str, _facts: list[Any]) -> dict[str, Any]:
        return {"figures": []}

    def _people(self, _prompt: str, _facts: list[Any]) -> dict[str, Any]:
        return {"people": []}

    def _steps(self, _prompt: str, _facts: list[Any]) -> dict[str, Any]:
        return {"steps": []}

    def _entities(self, _prompt: str, _facts: list[Any]) -> dict[str, Any]:
        return {"corrections": []}

    def _classify(self, _prompt: str, _facts: list[Any]) -> dict[str, Any]:
        return {"recording_type": "meeting"}

    def _summary(self, _prompt: str, facts: list[tuple[str, str, str]]) -> dict[str, Any]:
        return {"summary": [{"sentence": text, "fact_ids": [fid]} for fid, _k, text in facts[:2]]}


def spoken(text: str) -> str:
    """A quote a fact's text is drawn from without being a copy of it (F2:
    a text that IS its quote is evidence only, never a line). Fixtures that
    once used ``quote=text`` as shorthand use this instead."""
    quote = f"so {text}"
    while len(text) >= 0.8 * len(quote):
        quote = f"{quote} and that was the point"
    return quote
