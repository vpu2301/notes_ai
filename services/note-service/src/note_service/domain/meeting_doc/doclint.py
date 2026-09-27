"""D1 — the document lint: a note against the document standard
(docs/eval/document-standard.md; codes from docs/eval/error-taxonomy.md).

Runs before a document is written (``pipeline.run``). Two things happen:

* :func:`repair` makes the changes the standard states as mechanical — a
  line without a source is not written (§7), a heading loses trailing
  punctuation (§4). Nothing else is rewritten: code never rewords a
  model's line or a person's words.
* :func:`lint` reports every other departure as a finding: a taxonomy
  code, a rule, a section key and a line number — never a line's text —
  so findings can be stored in stats, counted in metrics and printed in
  CI. A finding does not block the note; the nightly gates and the blind
  rubric (§8) judge the numbers.

``D`` is the duration of transcribed speech in minutes (§ preamble).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Final

from . import roles, support
from .verify import _has_date_word, date_mentions, is_copied

# ── the standard's numbers ─────────────────────────────────────────
# §1 title
TITLE_MIN_CHARS: Final = 30
TITLE_MAX_CHARS: Final = 80
TITLE_MAX_COLONS: Final = 1
# §2 orientation
PARA1_WORDS: Final = (25, 60)
PARA2_WORDS: Final = (60, 140)
PARA2_SENTENCES: Final = (3, 6)
# §3 sections: max(3, min(8, round(D / 4))); judged from this many minutes
SECTIONS_MIN: Final = 3
SECTIONS_MAX: Final = 8
MINUTES_PER_SECTION: Final = 4
SECTIONS_FROM_MINUTES: Final = 5.0  # below: too little to head (Q3), not in the standard
SECTIONS_TOLERANCE: Final = 2  # "a 30-minute podcast has 6–8 sections"
POINTS_PER_SECTION: Final = (2, 6)
# §4 headings
HEADING_WORDS: Final = (3, 8)
HEADING_MAX_CHARS: Final = 60
HEADING_MAX_SHARED: Final = 0.6
# §5 bullets
BULLET_WORDS: Final = (8, 25)
# §6 sub-bullets
MAX_CHILDREN: Final = 3
QUOTE_CHILD_MAX_WORDS: Final = 20
CHILD_RESTATES: Final = 0.6
# §7 volume and redundancy
WORDS_PER_MINUTE: Final = (8, 18)
VOLUME_FROM_MINUTES: Final = 1.0
MAX_REDUNDANCY: Final = 0.05
REDUNDANT_JACCARD: Final = 0.6
TABLE_TYPES: Final = frozenset({"presentation_demo", "lecture_webinar"})
MIN_TABLE_ROWS: Final = 3

GENERIC_HEADINGS: Final[frozenset[str]] = frozenset(
    {
        "discussion", "general", "general discussion", "introduction", "intro", "other",
        "others", "other points", "further points", "misc", "miscellaneous", "topics", "notes",
        "summary", "overview", "various", "updates", "wrap-up", "conclusion", "next steps",
        "diskussion", "allgemeines", "allgemein", "einleitung", "einführung", "sonstiges",
        "weitere punkte", "weiteres", "themen", "notizen", "zusammenfassung", "überblick",
        "verschiedenes", "besprechung", "fazit", "abschluss",
        "обговорення", "загальне", "вступ", "інше", "інші питання", "теми", "нотатки",
        "підсумок", "підсумки", "огляд", "різне",
    }
)  # fmt: skip
GENERIC_TITLE: Final = re.compile(
    r"^(?:meeting|notes?|meeting notes|call|recording|besprechung|notizen|aufnahme|"
    r"gespräch|зустріч|нотатки|запис)\b[\s\-—:,]*(?:\d|$)",
    re.IGNORECASE,
)

_DEFAULT_LABEL: Final = re.compile(
    r"\bSPEAKER_\d+\b|\b(?:[Ss]peaker|[Ss]precher(?:in)?|[Сс]пікер)\s\d+\b"
    r"|\b[Uu]nknown speaker\b|\bUNKNOWN\b"
)
_NARRATOR_LABEL: Final = re.compile(
    r"Erzähler(?:/in)?|\bthe narrator\b|\bоповідач\b", re.IGNORECASE
)
_MARKS: Final = re.compile(r"❝|\[↗\]|\b[0-9a-f]{16}\b|\bfact[_ ]?ids?\b", re.IGNORECASE)
_MARKDOWN_RESIDUE: Final = re.compile(r"\*\*|^\s*#{1,6}\s|^\s*[-*]\s*$")
_TABLE_ROW: Final = re.compile(r"^\s*\|.*\|\s*$")
_BULLET: Final = re.compile(r"^(?P<indent>\s*)-\s")
_WORD: Final = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE_END: Final = re.compile(r"[.!?…](?:\s|$)")
_QUOTED: Final = re.compile(r"[\"“„«‚'].{3,}?[\"”“»‘']")
_LEAD: Final = re.compile(r"^[^—]{1,20}—\s+")
_FIRST_PERSON: Final[dict[str, re.Pattern[str]]] = {
    "en": re.compile(r"\bI\b|\bI['’](?:m|ll|ve|d)\b|\b(?:[Ww]e|[Mm]y|[Oo]ur|us|me)\b"),
    "de": re.compile(r"\b(?:ich|wir|mein\w*|unser\w*|uns|mir|mich)\b", re.IGNORECASE),
    "uk": re.compile(
        r"(?<![\w'’ʼ])(?:я|ми|мій|моя|моє|мої|наш\w*|нас|нам|мене|мені)(?![\w'’ʼ])",
        re.IGNORECASE,
    ),
}
_PRONOUNS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({"he", "she", "they", "him", "her", "his", "their", "them", "it"}),
    "de": frozenset({"er", "sie", "ihm", "ihn", "ihr", "sein", "seine", "ihre"}),
    "uk": frozenset({"він", "вона", "вони", "його", "її", "їх", "йому", "їй"}),
}
_ITEM_ROLES: Final = frozenset({roles.DECISIONS, roles.ACTION_ITEMS, roles.OPEN_QUESTIONS})
_PROSE: Final = frozenset({"framing", "summary", "bullet", "key_point"})
_NO_SOURCE_NEEDED: Final = frozenset({"heading", "note"})

# rule → taxonomy code: the closed vocabulary of findings.
RULES: Final[dict[str, str]] = {
    # §1 title
    "title_length": "D-HEAD",
    "title_generic": "D-HEAD",
    "title_colons": "D-HEAD",
    "title_repeats": "D-HEAD",
    "title_unsupported_name": "F-INV",
    # §2 orientation
    "no_overview": "D-ORIENT",
    "overview_no_framing": "D-ORIENT",
    "overview_list": "D-ORIENT",
    "paragraph1_length": "D-ORIENT",
    "paragraph2_missing": "D-ORIENT",
    "paragraph2_length": "D-ORIENT",
    "paragraph2_sentences": "D-ORIENT",
    # §3 sections
    "too_few_sections": "D-STRUCT",
    "too_many_sections": "D-STRUCT",
    "thin_section": "D-STRUCT",
    "long_section": "D-STRUCT",
    "out_of_order": "D-STRUCT",
    "interleaved": "D-STRUCT",
    "topic_repeats_item": "D-RED",
    # §4 headings
    "heading_generic": "D-HEAD",
    "heading_question": "D-HEAD",
    "heading_all_caps": "D-HEAD",
    "heading_length": "D-HEAD",
    "heading_punctuation": "D-HEAD",
    "heading_duplicate": "D-HEAD",
    "heading_overlap": "D-HEAD",
    "heading_restates_title": "D-HEAD",
    "heading_unsupported_name": "F-INV",
    # §5 bullets
    "bullet_length": "D-FORM",
    "bullet_unspecific": "D-SPEC",
    "bullet_pronoun_subject": "F-SUBJ",
    "bullet_copy": "F-COPY",
    "bullet_descriptive": "F-DESC",
    "label_in_prose": "D-LABEL",
    "first_person": "D-LANG",
    # §6 sub-bullets
    "too_many_children": "D-NEST",
    "nested_too_deep": "D-NEST",
    "child_restates_parent": "D-NEST",
    "quote_child_long": "D-FORM",
    # §7 volume and referencing
    "volume_low": "D-VOL",
    "volume_high": "D-VOL",
    "redundancy": "D-RED",
    "uncited_line": "D-REF",
    "table_misplaced": "D-FORM",
    "table_in_overview": "D-FORM",
    "marks": "D-FORM",
    "markdown_residue": "D-FORM",
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
class LintFact:
    start_ms: int = 0
    text: str = ""
    quote: str = ""


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


def target_sections(minutes: float) -> int:
    """§3: ``max(3, min(8, round(D / 4)))``."""
    return max(SECTIONS_MIN, min(SECTIONS_MAX, round(minutes / MINUTES_PER_SECTION)))


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


# ── repair: the mechanical part of the standard ─────────────────────


def repair(sections: Sequence[object]) -> tuple[list[object], dict[str, int]]:
    """Before the write (§4, §7): a content line citing nothing is not
    written; a heading loses trailing ":" "." "!". Works on
    ``render.RenderedSection`` (frozen dataclasses) and returns new ones
    with ``text`` rebuilt from the kept lines. Counts what it did."""
    counts = {"uncited_dropped": 0, "heading_punctuation_stripped": 0}
    out: list[object] = []
    for s in sections:
        lines = tuple(getattr(s, "lines", ()))
        kept = tuple(ln for ln in lines if ln.fact_ids or ln.kind in _NO_SOURCE_NEEDED)
        changes: dict[str, object] = {}
        if lines and len(kept) != len(lines):
            counts["uncited_dropped"] += len(lines) - len(kept)
            changes["lines"] = kept
            changes["text"] = _rebuild_text(getattr(s, "text", ""), lines, kept)
        title = getattr(s, "title", None)
        if title and title.rstrip() != title.rstrip().rstrip(":.!"):
            counts["heading_punctuation_stripped"] += 1
            changes["title"] = title.rstrip().rstrip(":.!").rstrip()
        if not changes:
            out.append(s)
            continue
        fixed = replace(s, **changes)  # type: ignore[type-var]
        if getattr(fixed, "lines", ()) or not lines:
            out.append(fixed)
        # A section every line of which cited nothing is not written.
    return out, counts


def _rebuild_text(text: str, before: Sequence[object], kept: Sequence[object]) -> str:
    """The section's text without the dropped lines, paragraph breaks kept."""
    dropped = [ln.text for ln in before if ln not in kept]  # type: ignore[attr-defined]
    out = []
    for raw in text.split("\n"):
        if raw.strip() and raw in dropped:
            dropped.remove(raw)
            continue
        out.append(raw)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ── lint ────────────────────────────────────────────────────────────


def _words(text: str) -> int:
    return len(_WORD.findall(text))


def _tokens(text: str) -> frozenset[str]:
    return support.merge_tokens(text)


def _said_a_date(text: str, language: str) -> bool:
    if _has_date_word(text):
        return True
    return bool(date_mentions(text, meeting_date=date(2026, 1, 5), language=language))


def _headed(section: LintSection) -> bool:
    return section.role == roles.TOPICS and bool((section.title or "").strip())


def _body(text: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s+|#{1,6}\s+)", "", text)


_CAPITAL_RUN: Final = re.compile(
    r"(?<![\w-])[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+(?:\s+[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+)+"
)
_ACRONYM: Final = re.compile(r"\b[A-ZÄÖÜА-ЯІЇЄҐ]{2,6}\b")


def _names(text: str, language: str, known: frozenset[str]) -> list[str]:
    """Names in a title or heading: two or more capitalised words in a row
    ("Elon Musk"), an acronym, or a name the recording knows. A single
    capitalised word says nothing in German, where every noun has one."""
    out = [m.group(0) for m in _CAPITAL_RUN.finditer(text)]
    out += _ACRONYM.findall(text)
    out += support.entities_in(text, language, known)
    return list(dict.fromkeys(out))


def _supported_name(name: str, evidence: str) -> bool:
    said = evidence.casefold()
    return all(w.casefold()[:5] in said for w in _WORD.findall(name) if len(w) > 1)


def lint(
    sections: Sequence[LintSection],
    *,
    language: str,
    speech_ms: int,
    recording_type: str | None = None,
    facts: dict[str, LintFact] | None = None,
    known: frozenset[str] = frozenset(),
    title: str | None = None,
) -> LintResult:
    """Every finding for one rendered note."""
    result = LintResult()
    facts = facts or {}
    minutes = speech_ms / 60_000
    content = [s for s in sections if s.lines or s.text.strip()]
    all_evidence = " ".join(f"{f.text} {f.quote}" for f in facts.values())

    if title is not None:
        _lint_title(result, title, language, known, all_evidence)
    if not content:
        return result
    _lint_orientation(result, sections)
    headed = [s for s in sections if _headed(s)]
    _lint_sections(result, sections, headed, minutes, facts)
    _lint_headings(result, headed, language, known, facts, title)
    _lint_lines(result, sections, language, known, facts, recording_type)
    _lint_volume(result, sections, minutes)
    return result


def _lint_title(
    result: LintResult, title: str, language: str, known: frozenset[str], evidence: str
) -> None:
    text = title.strip()
    if not TITLE_MIN_CHARS <= len(text) <= TITLE_MAX_CHARS:
        result.add("title_length")
    if GENERIC_TITLE.match(text):
        result.add("title_generic")
    if text.count(":") > TITLE_MAX_COLONS:
        result.add("title_colons")
    words = [w.casefold() for w in _WORD.findall(text) if len(w) > 3]
    if len(words) != len(set(words)):
        result.add("title_repeats")
    if evidence and any(not _supported_name(n, evidence) for n in _names(text, language, known)):
        result.add("title_unsupported_name")


def _lint_orientation(result: LintResult, sections: Sequence[LintSection]) -> None:
    top = next((s for s in sections if s.section_key == roles.OVERVIEW_KEY), None)
    if top is None:
        result.add("no_overview")
        return
    if not any(ln.kind == "framing" for ln in top.lines):
        result.add("overview_no_framing", top.section_key)
    for n, ln in enumerate(top.lines):
        if _TABLE_ROW.match(ln.text):
            result.add("table_in_overview", top.section_key, n)
        elif _BULLET.match(ln.text):
            result.add("overview_list", top.section_key, n)
    paragraphs = [p for p in top.text.split("\n\n") if p.strip()]
    if paragraphs and any(ln.kind == "framing" for ln in top.lines):
        low, high = PARA1_WORDS
        if not low <= _words(paragraphs[0]) <= high:
            result.add("paragraph1_length", top.section_key)
        if len(paragraphs) < 2:
            result.add("paragraph2_missing", top.section_key)
            return
        second = paragraphs[1]
        low, high = PARA2_WORDS
        if not low <= _words(second) <= high:
            result.add("paragraph2_length", top.section_key)
        # One summary line is one sentence (render writes them so); "11."
        # would end a sentence for a full-stop count.
        summary_lines = [ln for ln in top.lines if ln.kind == "summary" and ln.text in second]
        sentences = len(summary_lines) or len(_SENTENCE_END.findall(second)) or 1
        low, high = PARA2_SENTENCES
        if not low <= sentences <= high:
            result.add("paragraph2_sentences", top.section_key)


def _lint_sections(
    result: LintResult,
    sections: Sequence[LintSection],
    headed: list[LintSection],
    minutes: float,
    facts: dict[str, LintFact],
) -> None:
    if minutes >= SECTIONS_FROM_MINUTES:
        target = target_sections(minutes)
        if len(headed) < max(SECTIONS_MIN, target - SECTIONS_TOLERANCE):
            result.add("too_few_sections")
        elif len(headed) > SECTIONS_MAX:
            result.add("too_many_sections")
    low, high = POINTS_PER_SECTION
    for s in headed:
        points = sum(
            1 for ln in s.lines if ln.kind in ("bullet", "key_point", "figure") and not ln.child
        )
        if points < low:
            result.add("thin_section", s.section_key)
        elif points > high:
            result.add("long_section", s.section_key)
    spans: list[tuple[str, int, int]] = []
    for s in headed:
        times = [facts[i].start_ms for ln in s.lines for i in ln.fact_ids if i in facts]
        if times:
            spans.append((s.section_key, min(times), max(times)))
    for (_a, first_a, last_a), (key_b, first_b, _last_b) in zip(spans, spans[1:], strict=False):
        if first_b < first_a:
            result.add("out_of_order", key_b)
        elif first_b < last_a:
            result.add("interleaved", key_b)
    items = {i for s in sections if s.role in _ITEM_ROLES for ln in s.lines for i in ln.fact_ids}
    for s in headed:
        for n, ln in enumerate(s.lines):
            if ln.fact_ids and set(ln.fact_ids) <= items:
                result.add("topic_repeats_item", s.section_key, n)


def _lint_headings(
    result: LintResult,
    headed: list[LintSection],
    language: str,
    known: frozenset[str],
    facts: dict[str, LintFact],
    title: str | None,
) -> None:
    seen: list[tuple[str, frozenset[str]]] = []
    title_tokens = _tokens(title or "")
    for s in headed:
        heading = (s.title or "").strip()
        folded = heading.casefold()
        tokens = _tokens(heading)
        if folded.rstrip(":.!?") in GENERIC_HEADINGS:
            result.add("heading_generic", s.section_key)
        if heading.endswith("?"):
            result.add("heading_question", s.section_key)
        letters = [c for c in heading if c.isalpha()]
        if len(letters) >= 4 and all(c.isupper() for c in letters) and len(heading.split()) > 1:
            result.add("heading_all_caps", s.section_key)
        low, high = HEADING_WORDS
        # A chapter heading ("07:40 — Alex Karp") counts its words, not its time.
        words = _words(re.sub(r"^\d{1,2}:\d{2}\s*—\s*", "", heading))
        chapter = re.match(r"^\d{1,2}:\d{2}\b", heading)
        if (not low <= words <= high or len(heading) > HEADING_MAX_CHARS) and not chapter:
            result.add("heading_length", s.section_key)
        if heading.endswith((":", ".", "!")):
            result.add("heading_punctuation", s.section_key)
        for other, other_tokens in seen:
            if folded == other:
                result.add("heading_duplicate", s.section_key)
                break
            smaller = min(len(tokens), len(other_tokens))
            if smaller and len(tokens & other_tokens) / smaller > HEADING_MAX_SHARED:
                result.add("heading_overlap", s.section_key)
                break
        # Restating the title: every word of the heading is in it.
        if len(tokens) >= 2 and tokens <= title_tokens:
            result.add("heading_restates_title", s.section_key)
        evidence = " ".join(
            f"{facts[i].text} {facts[i].quote}" for ln in s.lines for i in ln.fact_ids if i in facts
        )
        if evidence and any(
            not _supported_name(n, evidence) for n in _names(heading, language, known)
        ):
            result.add("heading_unsupported_name", s.section_key)
        seen.append((folded, tokens))


def _lint_lines(
    result: LintResult,
    sections: Sequence[LintSection],
    language: str,
    known: frozenset[str],
    facts: dict[str, LintFact],
    recording_type: str | None,
) -> None:
    voice = _FIRST_PERSON.get(language, _FIRST_PERSON["en"])
    pronouns = _PRONOUNS.get(language, _PRONOUNS["en"])
    for s in sections:
        topic = _headed(s) or (s.role == roles.TOPICS)
        children = 0
        parent_tokens: frozenset[str] = frozenset()
        table_rows = 0
        for n, ln in enumerate(s.lines):
            text = ln.text
            if not text.strip():
                continue
            if _TABLE_ROW.match(text) and ln.kind != "heading":
                table_rows += 1
            if ln.kind not in _NO_SOURCE_NEEDED and not ln.fact_ids:
                result.add("uncited_line", s.section_key, n)
            if _DEFAULT_LABEL.search(text) or (
                ln.kind != "framing" and _NARRATOR_LABEL.search(text)
            ):
                result.add("label_in_prose", s.section_key, n)
            if _MARKS.search(text):
                result.add("marks", s.section_key, n)
            elif ln.kind != "heading" and _MARKDOWN_RESIDUE.search(text):
                result.add("markdown_residue", s.section_key, n)
            if ln.kind in _PROSE and voice.search(_DEFAULT_LABEL.sub("", text)):
                result.add("first_person", s.section_key, n)
            bullet = _BULLET.match(text)
            if not (bullet and ln.kind in ("bullet", "key_point")):
                continue
            body = _body(text).strip()
            indent = len(bullet["indent"])
            if indent >= 4:
                result.add("nested_too_deep", s.section_key, n)
            if ln.child or indent >= 2:
                children += 1
                if children == MAX_CHILDREN + 1:
                    result.add("too_many_children", s.section_key, n)
                child_tokens = _tokens(body)
                if parent_tokens and child_tokens:
                    shared = len(child_tokens & parent_tokens) / len(child_tokens | parent_tokens)
                    if shared >= CHILD_RESTATES:
                        result.add("child_restates_parent", s.section_key, n)
                if _QUOTED.search(body) and _words(body) > QUOTE_CHILD_MAX_WORDS:
                    result.add("quote_child_long", s.section_key, n)
                continue
            children = 0
            parent_tokens = _tokens(body)
            clean = _DEFAULT_LABEL.sub("", body)
            if topic:
                low, high = BULLET_WORDS
                if not low <= _words(body) <= high:
                    result.add("bullet_length", s.section_key, n)
            if (
                support.specificity(
                    clean,
                    language,
                    known=known,
                    has_date=ln.has_date or _said_a_date(clean, language),
                )
                == 0
            ):
                result.add("bullet_unspecific", s.section_key, n)
            first = _LEAD.sub("", clean).split()
            if first and first[0].strip(",.;:").casefold() in pronouns:
                result.add("bullet_pronoun_subject", s.section_key, n)
            if any(is_copied(body, facts[i].quote) for i in ln.fact_ids if i in facts):
                result.add("bullet_copy", s.section_key, n)
            if support.descriptive(clean, language, known=known, has_date=ln.has_date):
                result.add("bullet_descriptive", s.section_key, n)
        if table_rows and (recording_type not in TABLE_TYPES and table_rows < MIN_TABLE_ROWS):
            result.add("table_misplaced", s.section_key)


def _lint_volume(result: LintResult, sections: Sequence[LintSection], minutes: float) -> None:
    lines = [
        ln
        for s in sections
        for ln in s.lines
        if ln.text.strip() and ln.kind not in _NO_SOURCE_NEEDED and not _TABLE_ROW.match(ln.text)
    ]
    if minutes >= VOLUME_FROM_MINUTES:
        words = sum(_words(_body(ln.text)) for ln in lines)
        low, high = WORDS_PER_MINUTE
        if words < low * minutes:
            result.add("volume_low")
        elif words > high * minutes:
            result.add("volume_high")
    tokens = [_tokens(_body(ln.text)) for ln in lines]
    repeated: set[int] = set()
    for i in range(len(tokens)):
        for j in range(i + 1, len(tokens)):
            a, b = tokens[i], tokens[j]
            if a and b and len(a & b) / len(a | b) >= REDUNDANT_JACCARD:
                repeated.update((i, j))
    if lines and len(repeated) / len(lines) >= MAX_REDUNDANCY:
        result.add("redundancy")


# ── §8: the two rubric questions code can answer ────────────────────


def rubric_auto(
    sections: Sequence[LintSection],
    *,
    language: str,
    speech_ms: int,
    known: frozenset[str] = frozenset(),
) -> dict[str, int | float | None]:
    """Q3 (share of bullets with a name, number, date or term: ≥ 90 % → 2,
    60–89 % → 1, else 0) and Q7 (body words within 8·D–18·D → 2, within
    25 % of the band → 1, else 0). None when there is nothing to judge."""
    bullets = [
        ln
        for s in sections
        for ln in s.lines
        if ln.kind in ("bullet", "key_point") and _BULLET.match(ln.text) and not ln.child
    ]
    specific = sum(
        1
        for ln in bullets
        if support.specificity(
            _DEFAULT_LABEL.sub("", _body(ln.text)),
            language,
            known=known,
            has_date=ln.has_date or _said_a_date(_body(ln.text), language),
        )
        > 0
    )
    share = (specific / len(bullets)) if bullets else None
    q3 = None if share is None else 2 if share >= 0.9 else 1 if share >= 0.6 else 0
    minutes = speech_ms / 60_000
    words = sum(
        _words(_body(ln.text))
        for s in sections
        for ln in s.lines
        if ln.text.strip() and ln.kind not in _NO_SOURCE_NEEDED and not _TABLE_ROW.match(ln.text)
    )
    q7: int | None = None
    if minutes >= VOLUME_FROM_MINUTES:
        low, high = WORDS_PER_MINUTE[0] * minutes, WORDS_PER_MINUTE[1] * minutes
        q7 = 2 if low <= words <= high else 1 if 0.75 * low <= words <= 1.25 * high else 0
    return {"Q3": q3, "Q7": q7, "specific_share": share, "words": words}
