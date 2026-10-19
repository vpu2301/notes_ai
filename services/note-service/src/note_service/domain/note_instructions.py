"""Note instructions (Sprint N1): the writing profile a workspace's plain-text instructions
compile to, and everything code says about it.

The profile is a closed set of dials (concept §2, §5): every field has a default equal to
today's behaviour, every bound is checked here, and an out-of-range value never reaches
the engine. What the admin is told was understood is rendered by code from the profile
(:func:`understood_lines`), never written by the model; what will not be applied is one
fixed sentence per reason (:data:`NOT_APPLIED_COPY`). The instruction text is content:
nothing here logs it.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import re
import unicodedata
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .meeting_doc import render, roles

MAX_CHARS: Final = 8000
MAX_PHRASE_CHARS: Final = 40
MAX_GUIDANCE_CHARS: Final = 120
MAX_EXAMPLE_CHARS: Final = 160
MAX_NOT_APPLIED_CHARS: Final = 200

Reason = Literal[
    "adds_content",
    "voice_locked",
    "language_locked",
    "verification_locked",
    "structure_locked",
    "sharing",
    "unclear",
]
SectionOff = Literal[
    "topics", "open_questions", "risks", "requests", "agenda", "next_meeting", "specifications"
]

# Concept §4: one sentence per reason; the clients never invent wording.
NOT_APPLIED_COPY: Final[dict[str, str]] = {
    "adds_content": "The notes contain only what was said in the recording.",
    "voice_locked": "Notes are written in the third person.",
    "language_locked": "Notes are written in the language spoken in the meeting.",
    "verification_locked": "Every line keeps its evidence; the writer cannot be asked to drop it.",
    "structure_locked": (
        "Attendees, the title and the section set come from the template and the recording."
    ),
    "sharing": "Sharing is set under Branding & sharing and the connectors.",
    "unclear": "Not understood — try rephrasing as one of the headings in the guide.",
}


class TermPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use: str = Field(min_length=1, max_length=MAX_PHRASE_CHARS)
    instead_of: str = Field(min_length=1, max_length=MAX_PHRASE_CHARS)


class NotApplied(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_NOT_APPLIED_CHARS)
    reason: Reason


class WritingProfile(BaseModel):
    """Schema v1 (concept §5). An empty profile is a no-op for the engine."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    length: Literal["short", "standard", "long"] = "standard"
    summary_sentences: int | None = Field(default=None, ge=1, le=6)
    bullets_per_section: tuple[int, int] | None = None
    sections_off: list[SectionOff] = Field(default_factory=list)
    figure_tables: bool = True
    quote_children: bool = True
    heading_style: Literal["descriptive", "short"] = "descriptive"
    """N0's writing style named by the text; None: the workspace's style picker applies."""
    style: Literal["business", "formal", "informal", "academic"] | None = None
    emphasis: list[str] = Field(default_factory=list, max_length=8)
    terminology: list[TermPair] = Field(default_factory=list, max_length=20)
    avoid: list[str] = Field(default_factory=list, max_length=10)
    guidance: list[str] = Field(default_factory=list, max_length=12)
    style_examples: list[str] = Field(default_factory=list, max_length=3)
    not_applied: list[NotApplied] = Field(default_factory=list, max_length=20)

    @field_validator("bullets_per_section")
    @classmethod
    def _bullets(cls, value: tuple[int, int] | None) -> tuple[int, int] | None:
        if value is not None and not 2 <= value[0] <= value[1] <= 6:
            raise ValueError("bullets_per_section must be [lo, hi] with 2 <= lo <= hi <= 6")
        return value

    @field_validator("emphasis", "avoid")
    @classmethod
    def _phrases(cls, value: list[str]) -> list[str]:
        for phrase in value:
            if not phrase.strip() or len(phrase) > MAX_PHRASE_CHARS:
                raise ValueError(f"each entry is 1 to {MAX_PHRASE_CHARS} characters")
        return value

    @field_validator("guidance")
    @classmethod
    def _guidance(cls, value: list[str]) -> list[str]:
        for line in value:
            if not line.strip() or len(line) > MAX_GUIDANCE_CHARS or _DELIMITERS.search(line):
                raise ValueError(f"each line is 1 to {MAX_GUIDANCE_CHARS} characters, no ⟦ ⟧")
        return value

    @field_validator("style_examples")
    @classmethod
    def _examples(cls, value: list[str]) -> list[str]:
        for line in value:
            if not line.strip() or len(line) > MAX_EXAMPLE_CHARS:
                raise ValueError(f"each sample is 1 to {MAX_EXAMPLE_CHARS} characters")
        return value


EMPTY: Final = WritingProfile()


def is_empty(profile: WritingProfile) -> bool:
    """Every dial at its default and nothing passed to the writer (``not_applied`` aside)."""
    return profile.model_copy(update={"not_applied": []}) == EMPTY


def canonical_hash(profile: WritingProfile) -> str:
    """sha256 of the canonical JSON: what a generation records to name the profile it used."""
    blob = json.dumps(profile.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def non_default_dials(profile: WritingProfile) -> int:
    """How many dials differ from today's behaviour (``not_applied`` is no dial)."""
    defaults = EMPTY.model_dump()
    current = profile.model_dump()
    return sum(1 for k, v in current.items() if k != "not_applied" and v != defaults[k])


# ── Sanitising ──────────────────────────────────────────────────────

_DELIMITERS: Final = re.compile("[⟦⟧]")
# C0 and C1 controls except \t and \n.
_CONTROLS: Final = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BLANK_LINES: Final = re.compile(r"\n{3,}")


def sanitize_text(text: str, *, max_chars: int = MAX_CHARS) -> str:
    """NFC, no ⟦ ⟧, no control characters (tabs and newlines kept), at most one blank line
    in a row, trimmed. Longer than ``max_chars`` is the caller's 413, never a silent cut;
    this only caps what it is handed when the caller chose to."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROLS.sub("", _DELIMITERS.sub("", text))
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return text[:max_chars] if len(text) > max_chars else text


def sanitize_line(text: str, *, max_chars: int) -> str:
    """One line for a list field: sanitised, whitespace collapsed, capped."""
    return " ".join(sanitize_text(text, max_chars=10 * max_chars).split())[:max_chars].strip()


# ── What was understood (rendered by code) ─────────────────────────

_SECTION_LABELS: Final[dict[str, str]] = {
    **render.ROLE_LABELS["en"],
    roles.TOPICS: "topic sections",
    roles.REQUESTS: "Requests",
    roles.AGENDA: "Agenda",
}


def understood_lines(profile: WritingProfile) -> list[str]:
    """One fixed English sentence per non-default dial, in the concept's order. Guidance
    lines are shown separately, verbatim; they are not "understood" by code."""
    out: list[str] = []
    if profile.length == "short":
        out.append("Shorter than standard — about 60 % of the usual length.")
    elif profile.length == "long":
        out.append("Longer than standard — about 140 % of the usual length.")
    if profile.summary_sentences is not None:
        n = profile.summary_sentences
        out.append(f"The summary has at most {n} sentence{'' if n == 1 else 's'}.")
    if profile.bullets_per_section is not None:
        lo, hi = profile.bullets_per_section
        out.append(f"Each section has {lo} to {hi} bullets.")
    if profile.sections_off:
        # Mid-sentence: the note's headings ("Open questions") in lower case.
        labels = ", ".join(_SECTION_LABELS.get(s, s).lower() for s in profile.sections_off)
        out.append(f"Left out: {labels}.")
    if not profile.figure_tables:
        out.append("No figure tables.")
    if not profile.quote_children:
        out.append("No quoted sub-points.")
    if profile.heading_style == "short":
        out.append("Short headings (3 to 5 words).")
    if profile.style is not None:
        out.append(
            f"Style: {profile.style.capitalize()} — from your instructions (the picker is overridden)."
        )
    if profile.emphasis:
        out.append(f"Put first and never leave out: {', '.join(profile.emphasis)}.")
    out.extend(f"Use '{t.use}' instead of '{t.instead_of}'." for t in profile.terminology)
    if profile.avoid:
        out.append(f"Avoid the words: {', '.join(profile.avoid)}.")
    if profile.style_examples:
        out.append(
            "A sample of the wanted style is passed to the writer (form only; never copied)."
        )
    return out


def not_applied_view(profile: WritingProfile) -> list[dict[str, str]]:
    """``[{text, reason, message}]``: each refused request with its fixed sentence."""
    return [
        {"text": item.text, "reason": item.reason, "message": NOT_APPLIED_COPY[item.reason]}
        for item in profile.not_applied
    ]


# ── Terminology (N2): after the gate and the linter, on composed lines only ──

TERM_REPLACED: Final = "term_replaced"
_UNTOUCHED_ROLES: Final = frozenset({roles.TRANSCRIPT, roles.USER_NOTES})
_WORD: Final = re.compile(r"\w+")


def _term_patterns(
    profile: WritingProfile, known: frozenset[str]
) -> tuple[list[tuple[re.Pattern[str], str]], int]:
    """One word-bounded, case-insensitive pattern per pair, and the number skipped: a pair
    sharing a word with a known name is never applied (it must not respell a person)."""
    names = {w.casefold() for n in known for w in _WORD.findall(n)}
    patterns: list[tuple[re.Pattern[str], str]] = []
    skipped = 0
    for pair in profile.terminology:
        words = {w.casefold() for w in _WORD.findall(f"{pair.use} {pair.instead_of}")}
        if words & names:
            skipped += 1
            continue
        try:
            pattern = re.compile(rf"(?<!\w){re.escape(pair.instead_of)}(?!\w)", re.IGNORECASE)
        except re.error:
            skipped += 1
            continue
        patterns.append((pattern, pair.use))
    return patterns, skipped


def _cased(found: str, use: str) -> str:
    """``use`` as written, capitalised when it is lower case and the match was not."""
    if use != use.lower() or not found[:1].isupper():
        return use
    return use[:1].upper() + use[1:]


def _replace(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> str:
    for pattern, use in patterns:
        text = pattern.sub(functools.partial(_cased_match, use=use), text)
    return text


def _cased_match(match: re.Match[str], *, use: str) -> str:
    return _cased(match.group(0), use)


def apply_terminology(document: object, profile: WritingProfile, *, known: frozenset[str]) -> int:
    """Rewrite ``instead_of`` as ``use`` in every composed line (never a quote, a line that
    names a known person, a transcript or the author's own notes); a changed line carries ``term_replaced``. Returns the number
    of lines changed; with no pairs the document is not touched."""
    if not profile.terminology:
        return 0
    patterns, skipped = _term_patterns(profile, known)
    named = (
        re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(k) for k in sorted(known) if k.strip()) + r")(?!\w)",
            re.IGNORECASE,
        )
        if any(k.strip() for k in known)
        else None
    )
    stats = getattr(document, "stats", None)
    changed = 0
    sections = list(getattr(document, "sections", []))
    for n, section in enumerate(sections):
        if section.role in _UNTOUCHED_ROLES:
            continue
        text_lines = section.text.split("\n")
        used: set[int] = set()
        lines = []
        touched = False
        for line in section.lines:
            # A quote is the speaker's words; a line naming a person is left whole.
            keep = line.kind == "quote" or (named is not None and named.search(line.text))
            new = line.text if keep else _replace(line.text, patterns)
            if new == line.text:
                lines.append(line)
                continue
            changed += 1
            touched = True
            lines.append(dataclasses.replace(line, text=new, flags=(*line.flags, TERM_REPLACED)))
            at = next(
                (i for i, t in enumerate(text_lines) if t == line.text and i not in used), None
            )
            if at is not None:
                text_lines[at] = new
                used.add(at)
        if touched:
            sections[n] = dataclasses.replace(
                section,
                text="\n".join(text_lines),
                lines=tuple(lines),
                title=_replace(section.title, patterns)
                if section.title and not (named is not None and named.search(section.title))
                else section.title,
            )
    if changed:
        document.sections = sections  # type: ignore[attr-defined]
    if isinstance(stats, dict) and isinstance(stats.get("instructions_applied"), dict):
        stats["instructions_applied"]["terms_replaced"] = changed
        stats["instructions_applied"]["terms_skipped"] = skipped
    return changed
