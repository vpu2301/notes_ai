"""P1-04 — the critical cases a profile version must pass before it is activated: the
conditional $5,000 payment (condition and recipient kept), polarity inversions (worse,
fewer, not approved, opposes keep their direction) and participants (an event or a
chamber is nobody, a quoted clip is no guest, the introduced guest is kept).

Synthetic transcripts that ship with the service (``acceptance_cases/``), run as an
experiment like any other (same snapshot, same pipeline, nothing written), checked by
code against the produced note. A result counts only for the code it ran on
(:func:`suite_version`): a change to the bundled instructions, the algorithm, the prompt
schemas or the final check asks for the suite again, whatever the workspace text.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Final

from . import prompt_profiles as profiles
from .meeting_doc import final_check, prompts

SUITE: Final = "critical"


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    sentinel: str
    result: dict[str, Any]
    assertions: dict[str, Any]
    meeting_type: str = "auto"
    output_language: str = "auto"


@cache
def cases() -> tuple[Case, ...]:
    folder = resources.files(__package__).joinpath("acceptance_cases")
    out = []
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".json"):
            continue
        data = json.loads(entry.read_text("utf-8"))
        out.append(
            Case(
                id=data["id"],
                sentinel=data.get("sentinel", ""),
                result=data["result"],
                assertions=data.get("assertions") or {},
                meeting_type=data.get("meeting_type") or "auto",
                output_language=data.get("output_language") or "auto",
            )
        )
    return tuple(out)


def case(case_id: str) -> Case | None:
    return next((c for c in cases() if c.id == case_id), None)


def suite_version() -> str:
    """What a passing result is valid for: the cases, the prompt version and schemas, the
    algorithm and the final check. Any of them changing asks for the suite again."""
    blob = json.dumps(
        {
            "cases": [[c.id, c.result, c.assertions] for c in cases()],
            "prompt_version": prompts.PROMPT_VERSION,
            "schema": profiles.schema_version(),
            "algorithm": profiles.ALGORITHM_VERSION,
            "final_check": final_check.VERSION,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _has(text: str, needle: str) -> bool:
    return _fold(needle) in _fold(text)


def check(assertions: dict[str, Any], artifact: dict[str, Any]) -> list[str]:
    """The names of the failed checks (empty: passed), on the produced note's lines —
    the same semantics as ``scripts/eval/notes_assert.py`` for these check kinds."""
    lines = [
        ln
        for section in artifact.get("sections") or []
        for ln in section.get("lines") or []
        if str(ln.get("text") or "").strip()
    ]
    everything = "\n".join(str(ln["text"]) for ln in lines)
    framing = " ".join(
        str(ln["text"]) for ln in lines if ln.get("kind") in ("framing", "presenter")
    )
    failed: list[str] = []
    for i, group in enumerate(assertions.get("must_contain_any") or []):
        if not any(_has(everything, alt) for alt in group):
            failed.append(f"must_contain_any[{i}]")
    for i, forbidden in enumerate(assertions.get("must_not_contain") or []):
        if _has(everything, forbidden):
            failed.append(f"must_not_contain[{i}]")
    for i, groups in enumerate(assertions.get("same_line") or []):
        if not any(
            all(any(_has(str(ln["text"]), m) for m in group) for group in groups) for ln in lines
        ):
            failed.append(f"same_line[{i}]")
    for i, forbidden in enumerate(assertions.get("framing_must_not_contain") or []):
        if _has(framing, forbidden):
            failed.append(f"framing_must_not_contain[{i}]")
    for i, group in enumerate(assertions.get("framing_must_contain_any") or []):
        if not any(_has(framing, alt) for alt in group):
            failed.append(f"framing_must_contain_any[{i}]")
    return failed
