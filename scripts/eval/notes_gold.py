#!/usr/bin/env python3
"""Gold format v2 for the notes eval, and a validator (Summary Engine v2, Q1 T2).

    python scripts/eval/notes_gold.py tests/fixtures/eval/notes     # prints problems, exit 1 if any
    make eval-notes-validate CORPUS=eval/notes/v2

Every v2 field is optional, so a v1 file is a valid v2 file. What the
validator refuses is a gold file that contradicts itself or its own
transcript: an ASR spelling that the ASR never produced, a date phrase
nobody said, a speaker label nobody spoke under, a forbidden string that
the gold facts themselves contain. A metric computed from such a file
would measure the annotator, not the engine.

Problems name the file and the index of the offending entry — never its
text, so the output is safe to paste into a ticket about a real corpus.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

RecordingType = Literal[
    "meeting",
    "client_call",
    "sales_call",
    "interview",
    "one_on_one",
    "podcast_broadcast",
    "lecture_webinar",
    "voice_memo",
]


class _Model(BaseModel):
    # Unknown keys are refused: a typo in a gold key silently skips a metric.
    model_config = ConfigDict(extra="forbid")


class Turn(_Model):
    speaker: str
    t_start_ms: int = Field(ge=0)
    t_end_ms: int = Field(ge=0)
    text: str


class Action(_Model):
    text: str
    owner: str | None = None
    due: str | None = None


class Entity(_Model):
    canonical: str
    surface_forms: list[str] = Field(default_factory=list)
    kind: Literal["person", "org", "place", "product"] = "person"


class Hedged(_Model):
    fact: str
    modality: Literal["forecast", "estimate", "plan", "unconfirmed", "opinion"]


class DateRef(_Model):
    text: str
    resolved: str
    tense: Literal["past", "future", "none"] = "none"


class TopicRef(_Model):
    title: str
    t_start_ms: int = Field(ge=0)


class GlossaryTerm(_Model):
    term: str
    kind: Literal["person", "company", "product", "term"] = "person"
    heard_as: list[str] = Field(default_factory=list)


class Gold(_Model):
    key_facts: list[str] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    hedged: list[Hedged] = Field(default_factory=list)
    dates: list[DateRef] = Field(default_factory=list)
    speakers: dict[str, str] = Field(default_factory=dict)
    name_candidates: list[str] = Field(default_factory=list)
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    topics: list[TopicRef] = Field(default_factory=list)
    must_contain: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)


class Meeting(_Model):
    id: str
    language: Literal["en", "de", "uk"]
    meeting_type: str
    recorded_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    recording_type: RecordingType | None = None
    transcript: list[Turn]
    gold: Gold


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def validate_meeting(data: dict, name: str) -> list[str]:
    try:
        meeting = Meeting.model_validate(data)
    except ValidationError as exc:
        return [
            f"{name}: schema: {'.'.join(str(p) for p in err['loc'])}: {err['type']}"
            for err in exc.errors()
        ]
    problems: list[str] = []
    said = _fold(" ".join(t.text for t in meeting.transcript))
    labels = {t.speaker for t in meeting.transcript}
    gold = meeting.gold

    for i, entity in enumerate(gold.entities):
        for j, form in enumerate(entity.surface_forms):
            if _fold(form) not in said:
                problems.append(f"{name}: entities[{i}].surface_forms[{j}] not in the transcript")
    for i, ref in enumerate(gold.dates):
        if _fold(ref.text) not in said:
            problems.append(f"{name}: dates[{i}].text not in the transcript")
    for label in gold.speakers:
        if label not in labels:
            problems.append(f"{name}: speakers key {label!r} is not a transcript speaker")
    facts = [_fold(f) for f in gold.key_facts]
    for i, forbidden in enumerate(gold.must_not_contain):
        if any(_fold(forbidden) in fact for fact in facts):
            problems.append(f"{name}: must_not_contain[{i}] occurs in a gold key fact")
    for i, turn in enumerate(meeting.transcript):
        if turn.t_end_ms < turn.t_start_ms:
            problems.append(f"{name}: transcript[{i}] ends before it starts")
    return problems


def validate_corpus(path: Path) -> list[str]:
    """Every problem in every ``*.json`` meeting under ``path``.
    ``*.assertions.json`` files are regression checklists, not meetings."""
    problems: list[str] = []
    files = sorted(p for p in path.glob("*.json") if not p.name.endswith(".assertions.json"))
    if not files:
        return [f"{path}: no meetings"]
    for file in files:
        try:
            data = json.loads(file.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{file.name}: not JSON (line {exc.lineno})")
            continue
        problems.extend(validate_meeting(data, file.name))
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: notes_gold.py <corpus dir>", file=sys.stderr)
        return 2
    corpus = Path(argv[0])
    if not corpus.is_dir():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return 3
    problems = validate_corpus(corpus)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
