#!/usr/bin/env python3
"""Gold format v2/v3 for the notes eval, and a validator that refuses a gold file
contradicting its own transcript.

    python scripts/eval/notes_gold.py tests/fixtures/eval/notes

Problems name the file and the entry index, never its text.
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
    "presentation_demo",
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


class GoldFigure(_Model):
    """F3 — a number a speaker attached to a named quantity."""

    name: str
    value: str
    unit: str = ""
    qualifier: str = ""


class GoldPresenter(_Model):
    name: str
    role: str = ""
    organisation: str = ""


class KeyFact(_Model):
    """Gold v3 (Sprint SQ1): a key fact with an id, the third of the
    recording it was said in (from the transcript's timestamps), its kind
    and — for an opinion — whose it is."""

    id: str = Field(pattern=r"^k\d{2,3}$")
    text: str
    third: Literal[1, 2, 3]
    kind: Literal["fact", "number", "date", "decision", "action", "opinion"] = "fact"
    holder: str | None = None


class Participant(_Model):
    """Gold v3: a voice and who it is. Every participant has a role."""

    label: str | None = None
    name: str | None = None
    role: Literal["narrator", "host", "expert", "guest", "interviewee", "participant"]
    speech_share: float = Field(ge=0.0, le=1.0)


class Opinion(_Model):
    fact: str  # a KeyFact id
    holder: str


class TopicSegment(_Model):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    label: str


class NonContent(_Model):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    kind: Literal["ad", "jingle", "trailer"]


def fact_text(fact: str | dict | KeyFact) -> str:
    """A key fact's text, whichever gold version wrote it."""
    if isinstance(fact, KeyFact):
        return fact.text
    if isinstance(fact, dict):
        return str(fact.get("text", ""))
    return fact


def fact_third(fact: str | dict | KeyFact) -> int | None:
    """The third a v3 fact names; None for a v1/v2 string (inferred then)."""
    if isinstance(fact, KeyFact):
        return fact.third
    if isinstance(fact, dict) and fact.get("third") in (1, 2, 3):
        return int(fact["third"])
    return None


class Gold(_Model):
    # v1/v2: strings; v3: KeyFact objects. One file uses one.
    key_facts: list[str | KeyFact] = Field(default_factory=list)
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
    # What a walkthrough's note must carry.
    figures: list[GoldFigure] = Field(default_factory=list)
    presenter: GoldPresenter | None = None
    contact: list[str] = Field(default_factory=list)
    # Who each voice is (label → narrator | host | guest | interviewee | participant | clip | advert).
    roles: dict[str, Literal[
        "narrator", "host", "guest", "interviewee", "participant", "clip", "advert"
    ]] = Field(default_factory=dict)  # fmt: skip
    # Gold v3.
    participants: list[Participant] = Field(default_factory=list)
    opinions: list[Opinion] = Field(default_factory=list)
    topic_segments: list[TopicSegment] = Field(default_factory=list)
    non_content: list[NonContent] = Field(default_factory=list)
    title_reference: str | None = None
    reviewers: int | None = Field(default=None, ge=1)


class Meeting(_Model):
    id: str
    language: Literal["en", "de", "uk"]
    meeting_type: str
    recorded_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    recording_type: RecordingType | None = None
    transcript: list[Turn]
    # Gold v3: the human-corrected transcript; faithfulness is scored against both.
    reference_transcript: list[Turn] | None = None
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
    facts = [_fold(fact_text(f)) for f in gold.key_facts]
    problems += _v3_problems(gold, name, labels)
    for i, forbidden in enumerate(gold.must_not_contain):
        if any(_fold(forbidden) in fact for fact in facts):
            problems.append(f"{name}: must_not_contain[{i}] occurs in a gold key fact")
    for i, turn in enumerate(meeting.transcript):
        if turn.t_end_ms < turn.t_start_ms:
            problems.append(f"{name}: transcript[{i}] ends before it starts")
    return problems


def _v3_problems(gold: Gold, name: str, labels: set[str]) -> list[str]:
    out: list[str] = []
    kinds = {type(f) for f in gold.key_facts}
    if len(kinds) > 1:
        out.append(f"{name}: key_facts mixes v2 strings and v3 objects")
    ids = [f.id for f in gold.key_facts if isinstance(f, KeyFact)]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        out.append(f"{name}: key_facts id {dup!r} is not unique")
    by_id = {f.id: f for f in gold.key_facts if isinstance(f, KeyFact)}
    for i, op in enumerate(gold.opinions):
        fact = by_id.get(op.fact)
        if fact is None:
            out.append(f"{name}: opinions[{i}].fact names no key fact")
        elif fact.kind != "opinion":
            out.append(f"{name}: opinions[{i}].fact is not an opinion")
    for i, f in enumerate(gold.key_facts):
        if isinstance(f, KeyFact) and f.kind == "opinion" and not f.holder:
            out.append(f"{name}: key_facts[{i}] is an opinion without a holder")
    for i, p in enumerate(gold.participants):
        if p.label is not None and p.label not in labels:
            out.append(f"{name}: participants[{i}].label is not a transcript speaker")
        if p.label is None and p.name is None:
            out.append(f"{name}: participants[{i}] has neither label nor name")
    previous = -1
    for i, seg in enumerate(gold.topic_segments):
        if seg.end_ms <= seg.start_ms:
            out.append(f"{name}: topic_segments[{i}] ends before it starts")
        if seg.start_ms < previous:
            out.append(f"{name}: topic_segments[{i}] is out of order")
        previous = seg.end_ms
    for i, region in enumerate(gold.non_content):
        if region.end_ms <= region.start_ms:
            out.append(f"{name}: non_content[{i}] ends before it starts")
    if ids and gold.reviewers is None:
        out.append(f"{name}: v3 key facts name no reviewers count")
    return out


def validate_corpus(path: Path) -> list[str]:
    """Every problem in every ``*.json`` meeting under ``path``.
    ``*.assertions.json`` files are regression checklists, not meetings."""
    problems: list[str] = []
    files = sorted(
        p
        for p in path.glob("*.json")
        if not p.name.endswith(".assertions.json") and p.name != "manifest.json"
    )
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
