"""D1 — the document lint (docs/eval/error-taxonomy.md, layer C).

Reads a rendered note and names what is wrong with its form, by taxonomy
code and rule: no orientation (D-ORIENT), no or wrong structure
(D-STRUCT), bad headings (D-HEAD), unspecific bullets (D-SPEC), wrong
volume (D-VOL), a line without a source (D-REF), labels in prose
(D-LABEL), first person (D-LANG), rendering residue (D-FORM).

It detects; it does not rewrite. A finding carries a code, a rule, a
section key and a line number — never a line's text — so findings can be
stored in stats, counted in metrics and printed in CI.

Thresholds are ADR-0065's. The ones the taxonomy leaves open (volume,
headings per minute, heading length) are PROVISIONAL until measured on
eval/notes/v2.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from . import roles, support
from .verify import _has_date_word, date_mentions

# ── thresholds (ADR-0065) ───────────────────────────────────────────
LONG_RECORDING_MS: Final = 10 * 60_000  # needs headings (amendment §2.6)
MINUTES_PER_HEADING: Final = 15  # at least one heading per 15 minutes
MIN_POINTS_PER_SECTION: Final = 2  # Q3: a topic is two points or more
HEADING_MAX_WORDS: Final = 8
HEADING_MAX_CHARS: Final = 60
VOLUME_MIN_WPM: Final = 8.0  # words of note per minute of audio, below: too little
VOLUME_MAX_WPM: Final = 50.0  # above: the note is becoming the transcript
VOLUME_MIN_MS: Final = 5 * 60_000  # "too little" is judged from five minutes on
VOLUME_MAX_MIN_MS: Final = 2 * 60_000

# Headings that name no phase and no subject.
GENERIC_HEADINGS: Final[frozenset[str]] = frozenset(
    {
        "discussion", "general", "general discussion", "other", "others", "misc",
        "miscellaneous", "topics", "notes", "summary", "overview", "various", "updates",
        "diskussion", "allgemeines", "allgemein", "sonstiges", "themen", "notizen",
        "zusammenfassung", "überblick", "verschiedenes", "besprechung",
        "обговорення", "загальне", "інше", "теми", "нотатки", "підсумок", "огляд", "різне",
    }
)  # fmt: skip

_DEFAULT_LABEL: Final = re.compile(
    r"\bSPEAKER_\d+\b|\b(?:[Ss]peaker|[Ss]precher(?:in)?|[Сс]пікер)\s\d+\b"
    r"|\b[Uu]nknown speaker\b|\bUNKNOWN\b"
)
_NARRATOR_LABEL: Final = re.compile(r"Erzähler/in|\bthe narrator\b|\bоповідач\b", re.IGNORECASE)
_MARKS: Final = re.compile(r"❝|\[↗\]|\b[0-9a-f]{16}\b|\bfact[_ ]?ids?\b", re.IGNORECASE)
_MARKDOWN_RESIDUE: Final = re.compile(r"\*\*|^\s*#{1,6}\s|^\s*[-*]\s*$")
_TABLE_ROW: Final = re.compile(r"^\s*\|.*\|\s*$")
_BULLET: Final = re.compile(r"^\s*-\s")
_WORD: Final = re.compile(r"[^\W_]+", re.UNICODE)
# D-LANG — the transcript's voice. Broader than support.first_person (which
# decides what F2 drops): the lint only reports, and "we" in a record is
# already the wrong register.
_FIRST_PERSON: Final[dict[str, re.Pattern[str]]] = {
    "en": re.compile(r"\bI\b|\bI['’](?:m|ll|ve|d)\b|\b(?:[Ww]e|[Mm]y|[Oo]ur|us|me)\b"),
    "de": re.compile(r"\b(?:ich|wir|mein\w*|unser\w*|uns|mir|mich)\b", re.IGNORECASE),
    "uk": re.compile(
        r"(?<![\w'’ʼ])(?:я|ми|мій|моя|моє|мої|наш\w*|нас|нам|мене|мені)(?![\w'’ʼ])", re.IGNORECASE
    ),
}

# Line kinds that are prose a model or the code composed.
_PROSE: Final = frozenset({"framing", "summary", "bullet", "key_point"})
# Line kinds that carry no claim of their own.
_NO_SOURCE_NEEDED: Final = frozenset({"heading", "note"})

# rule → code: the closed vocabulary of findings.
RULES: Final[dict[str, str]] = {
    "no_overview": "D-ORIENT",
    "overview_no_framing": "D-ORIENT",
    "overview_list": "D-ORIENT",
    "no_headings_long": "D-STRUCT",
    "too_few_headings": "D-STRUCT",
    "thin_section": "D-STRUCT",
    "out_of_order": "D-STRUCT",
    "heading_generic": "D-HEAD",
    "heading_all_caps": "D-HEAD",
    "heading_long": "D-HEAD",
    "heading_punctuation": "D-HEAD",
    "heading_duplicate": "D-HEAD",
    "bullet_unspecific": "D-SPEC",
    "volume_low": "D-VOL",
    "volume_high": "D-VOL",
    "uncited_line": "D-REF",
    "label_in_prose": "D-LABEL",
    "first_person": "D-LANG",
    "marks": "D-FORM",
    "markdown_residue": "D-FORM",
    "table_in_overview": "D-FORM",
}


@dataclass(frozen=True, slots=True)
class LintLine:
    text: str
    kind: str
    fact_ids: tuple[str, ...] = ()
    child: bool = False
    has_date: bool = False  # render resolved a date said in it (Q3)


@dataclass(frozen=True, slots=True)
class LintSection:
    section_key: str
    role: str
    title: str | None
    text: str
    lines: tuple[LintLine, ...] = ()


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    rule: str
    section_key: str | None = None
    line: int | None = None  # index into the section's lines


@dataclass
class LintResult:
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, section_key: str | None = None, line: int | None = None) -> None:
        self.findings.append(Finding(RULES[rule], rule, section_key, line))

    def by_code(self) -> dict[str, int]:
        return dict(sorted(Counter(f.code for f in self.findings).items()))

    def by_rule(self) -> dict[str, int]:
        return dict(sorted(Counter(f.rule for f in self.findings).items()))


def from_rendered(sections: Iterable[object]) -> list[LintSection]:
    """``render.RenderedSection`` → lint input."""
    out: list[LintSection] = []
    for s in sections:
        lines = tuple(
            LintLine(
                text=ln.text,
                kind=ln.kind,
                fact_ids=tuple(ln.fact_ids),
                child=bool(getattr(ln, "parent", None)),
                has_date=bool(getattr(ln, "dates", ())),
            )
            for ln in getattr(s, "lines", ())
        )
        out.append(
            LintSection(
                section_key=s.section_key,  # type: ignore[attr-defined]
                role=s.role,  # type: ignore[attr-defined]
                title=s.title,  # type: ignore[attr-defined]
                text=s.text,  # type: ignore[attr-defined]
                lines=lines,
            )
        )
    return out


def _said_a_date(text: str, language: str) -> bool:
    """A date word, or anything the Q3 resolver reads as a date ("до
    п'ятниці", "by Friday"). Which day it resolves to does not matter here."""
    if _has_date_word(text):
        return True
    return bool(date_mentions(text, meeting_date=date(2026, 1, 5), language=language))


def _headed(section: LintSection) -> bool:
    return section.role == roles.TOPICS and bool((section.title or "").strip())


def _words(text: str) -> int:
    return len(_WORD.findall(text))


def lint(
    sections: Sequence[LintSection],
    *,
    language: str,
    duration_ms: int,
    fact_start_ms: dict[str, int] | None = None,
    known: frozenset[str] = frozenset(),
) -> LintResult:
    """Every finding for one rendered note."""
    result = LintResult()
    starts = fact_start_ms or {}
    content = [s for s in sections if s.lines or s.text.strip()]
    if not content:
        return result

    # ── D-ORIENT ─────────────────────────────────────────────────────
    top = next((s for s in sections if s.section_key == roles.OVERVIEW_KEY), None)
    if top is None:
        result.add("no_overview")
    else:
        if not any(ln.kind == "framing" for ln in top.lines):
            result.add("overview_no_framing", top.section_key)
        for n, ln in enumerate(top.lines):
            if _TABLE_ROW.match(ln.text):
                result.add("table_in_overview", top.section_key, n)
            elif _BULLET.match(ln.text):
                result.add("overview_list", top.section_key, n)

    # ── D-STRUCT ─────────────────────────────────────────────────────
    headed = [s for s in sections if _headed(s)]
    if duration_ms > LONG_RECORDING_MS:
        if not headed:
            result.add("no_headings_long")
        elif len(headed) < (duration_ms / 60_000) / MINUTES_PER_HEADING:
            result.add("too_few_headings")
    for s in headed:
        points = sum(
            1 for ln in s.lines if ln.kind in ("bullet", "key_point", "figure") and not ln.child
        )
        if points < MIN_POINTS_PER_SECTION:
            result.add("thin_section", s.section_key)
    firsts = []
    for s in headed:
        times = [starts[i] for ln in s.lines for i in ln.fact_ids if i in starts]
        if times:
            firsts.append((s.section_key, min(times)))
    for (_a, t_a), (key_b, t_b) in zip(firsts, firsts[1:], strict=False):
        if t_b < t_a:
            result.add("out_of_order", key_b)

    # ── D-HEAD ───────────────────────────────────────────────────────
    seen: set[str] = set()
    for s in headed:
        title = (s.title or "").strip()
        folded = title.casefold()
        if folded.rstrip(":.") in GENERIC_HEADINGS:
            result.add("heading_generic", s.section_key)
        letters = [c for c in title if c.isalpha()]
        if len(letters) >= 4 and all(c.isupper() for c in letters) and len(title.split()) > 1:
            result.add("heading_all_caps", s.section_key)
        if _words(title) > HEADING_MAX_WORDS or len(title) > HEADING_MAX_CHARS:
            result.add("heading_long", s.section_key)
        if title.endswith((":", ".")):
            result.add("heading_punctuation", s.section_key)
        if folded in seen:
            result.add("heading_duplicate", s.section_key)
        seen.add(folded)

    # ── line rules ───────────────────────────────────────────────────
    words = 0
    for s in sections:
        for n, ln in enumerate(s.lines):
            text = ln.text
            if not text.strip():
                continue
            if ln.kind not in _NO_SOURCE_NEEDED:
                words += _words(text)
            # D-REF
            if ln.kind not in _NO_SOURCE_NEEDED and not ln.fact_ids:
                result.add("uncited_line", s.section_key, n)
            # D-LABEL — the framing may list the narrator among the speakers.
            if _DEFAULT_LABEL.search(text) or (
                ln.kind != "framing" and _NARRATOR_LABEL.search(text)
            ):
                result.add("label_in_prose", s.section_key, n)
            # D-FORM
            if _MARKS.search(text):
                result.add("marks", s.section_key, n)
            elif ln.kind != "heading" and _MARKDOWN_RESIDUE.search(text):
                result.add("markdown_residue", s.section_key, n)
            # D-LANG
            voice = _FIRST_PERSON.get(language, _FIRST_PERSON["en"])
            if ln.kind in _PROSE and voice.search(_DEFAULT_LABEL.sub("", text)):
                result.add("first_person", s.section_key, n)
            # D-SPEC — a bullet names, counts or dates something.
            if ln.kind in ("bullet", "key_point") and _BULLET.match(text):
                body = _DEFAULT_LABEL.sub("", text)
                if (
                    support.specificity(
                        body,
                        language,
                        known=known,
                        has_date=ln.has_date or _said_a_date(body, language),
                    )
                    == 0
                ):
                    result.add("bullet_unspecific", s.section_key, n)

    # ── D-VOL ────────────────────────────────────────────────────────
    minutes = duration_ms / 60_000
    if minutes > 0:
        wpm = words / minutes
        if duration_ms >= VOLUME_MIN_MS and wpm < VOLUME_MIN_WPM:
            result.add("volume_low")
        elif duration_ms >= VOLUME_MAX_MIN_MS and wpm > VOLUME_MAX_WPM:
            result.add("volume_high")
    return result
