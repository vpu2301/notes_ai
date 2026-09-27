"""Sprint D1 — the document linter: no note below the standard is written
(docs/eval/document-standard.md; codes from docs/eval/error-taxonomy.md;
ADR-0065).

One linter, two callers. :func:`enforce` runs in the worker between
``pipeline.run`` and ``writer.apply``, and in the eval harness on every
output, so production and eval agree on what meets the standard.

* :func:`check` is pure: the rendered sections in, findings out —
  ``(rule, code, severity, section key, line index, detail)``, never a
  line's text.
* :func:`repair` makes the deterministic repairs the work order names:
  merge, split, reorder, drop, trim, widen, recase, map. A line code cannot
  make meet the standard is not rendered (its fact stays evidence); a part
  that cannot be repaired is written in its fallback form (chapters,
  code-composed orientation, an entity-and-time heading).
* Hard findings (S1/S2) whose rule a D2 regeneration can fix are sent to
  the ``regenerate`` hook once, before the fallbacks. D2 is not merged: the
  worker passes no hook and ``regenerated`` is 0.
* Whatever is still found after that is ``unresolved`` in the stats.

Rules are data (:data:`RULES`): adding one is a row, a check and a test.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Final

from . import overview, roles, support
from .render import Line, RenderedSection, patch_claim
from .verify import VerifiedFact, _has_date_word, date_mentions, is_copied

logger = logging.getLogger(__name__)

# ── the standard's numbers ─────────────────────────────────────────
TITLE_CHARS: Final = (30, 80)
TITLE_MAX_CHARS: Final = TITLE_CHARS[1]  # note_title's cut
TITLE_MAX_COLONS: Final = 1
PARA1_WORDS: Final = (25, 60)
PARA2_WORDS: Final = (60, 140)
PARA2_SENTENCES: Final = (3, 6)
THEMES: Final = (3, 5)
SECTIONS_MIN: Final = 3
SECTIONS_MAX: Final = 8
MINUTES_PER_SECTION: Final = 4
SECTIONS_TOLERANCE: Final = 2
SECTIONS_FROM_MINUTES: Final = 5.0  # below: Q3's "too little to head"
POINTS_PER_SECTION: Final = (2, 6)
MERGE_HEADING_SHARE: Final = 0.4
MERGE_SPAN_MS: Final = 90_000
HEADING_WORDS: Final = (3, 8)
HEADING_MAX_CHARS: Final = 60
HEADING_MAX_SHARED: Final = 0.6
BULLET_WORDS: Final = (8, 25)
SENTENCE_MAX_WORDS: Final = 35
MAX_CHILDREN: Final = 3
CHILD_RESTATES: Final = 0.6
WORDS_PER_MINUTE: Final = (8, 18)
VOLUME_FROM_MINUTES: Final = 1.0
REDUNDANT_JACCARD: Final = 0.6
LANGUAGE_MIN_WORDS: Final = 6

# Severity of each taxonomy code (docs/eval/error-taxonomy.md): S1 misleads,
# S2 unusable, S3 worse than it should be. S1/S2 are hard.
SEVERITY: Final[dict[str, str]] = {
    "F-INV": "S1", "F-DIST": "S1", "F-SUBJ": "S1",
    "D-ORIENT": "S2", "D-STRUCT": "S2", "D-SPEC": "S2", "D-VOL": "S2", "D-REF": "S2",
    "D-LABEL": "S2", "F-COPY": "S2", "F-DESC": "S2",
    "D-HEAD": "S3", "D-RED": "S3", "D-NEST": "S3", "D-LANG": "S3", "D-FORM": "S3",
}  # fmt: skip
HARD: Final = frozenset({"S1", "S2"})


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    hook: bool = False  # a D2 regeneration can fix it


RULES: Final[dict[str, Rule]] = {
    # T1 structure and volume
    "sections.count": Rule("D-STRUCT", hook=True),
    "sections.size": Rule("D-STRUCT"),
    "sections.order": Rule("D-STRUCT"),
    "volume.words": Rule("D-VOL"),
    "redundancy": Rule("D-RED"),
    # T2 headings and title
    "heading.form": Rule("D-HEAD", hook=True),
    "heading.generic": Rule("D-HEAD", hook=True),
    "heading.nouns": Rule("D-HEAD", hook=True),
    "heading.distinct": Rule("D-HEAD", hook=True),
    "title.form": Rule("D-HEAD"),
    # T3 lines (line.subject is F-SUBJ for a pronoun, D-LABEL for a label)
    "line.specific": Rule("D-SPEC"),
    "line.length": Rule("D-FORM", hook=True),
    "line.copy": Rule("F-COPY"),
    "line.descriptive": Rule("F-DESC"),
    "line.subject": Rule("F-SUBJ", hook=True),
    "line.person": Rule("D-LANG"),
    "line.certainty": Rule("F-DIST"),
    "line.glyph": Rule("D-FORM"),
    "line.language": Rule("D-LANG"),
    "line.cited": Rule("D-REF"),
    "line.child": Rule("D-NEST"),
    # T4 orientation
    "orient.present": Rule("D-ORIENT", hook=True),
    "orient.p1": Rule("D-ORIENT", hook=True),
    "orient.p2": Rule("D-ORIENT", hook=True),
    "orient.type_words": Rule("D-ORIENT"),
}

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
# A speaker label as a subject or actor. "Labels are never repaired by
# substitution — that is how 'Speaker 1 ist genervt' happened."
_LABEL: Final = re.compile(
    r"\bSPEAKER_\d+\b|\b(?:[Ss]peaker|[Ss]precher(?:in)?|[Сс]пікер)(?:\s\d+)?\b"
    r"|\b[Uu]nknown speaker\b|\bUNKNOWN\b|Erzähler(?:/in)?|\bthe narrator\b|\bоповідач\b"
)
_GLYPHS: Final = re.compile(
    r"\s*(?:❝|\[↗\]|⟦[^⟧]*⟧|⟦|⟧|\b[0-9a-f]{16}\b|\(?\bfact[_ ]?ids?\b\s*[:=]?\)?)"
)
_MARKDOWN: Final = re.compile(r"\*\*")
_TABLE_ROW: Final = re.compile(r"^\s*\|.*\|\s*$")
_BULLET: Final = re.compile(r"^(?P<indent>\s*)-\s")
_WORD: Final = re.compile(r"[^\W_]+", re.UNICODE)
_LEAD: Final = re.compile(r"^[^—]{1,20}—\s+")
_QUOTE_MARKS: Final = re.compile(r"[\"“„«»”]")
_MACHINE_LABEL: Final = re.compile(r"\b[a-z]+_[a-z_]+\b")
_CAPITAL_RUN: Final = re.compile(
    r"(?<![\w-])[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+(?:\s+[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+)+"
)
_ACRONYM: Final = re.compile(r"\b[A-ZÄÖÜА-ЯІЇЄҐ]{2,6}\b")
_FIRST_PERSON: Final[dict[str, re.Pattern[str]]] = {
    "en": re.compile(r"\bI\b|\bI['’](?:m|ll|ve|d)\b|\b(?:[Ww]e|[Mm]y|[Oo]ur|us|me)\b"),
    "de": re.compile(r"\b(?:ich|wir|mein\w*|unser\w*|uns|mir|mich)\b", re.IGNORECASE),
    "uk": re.compile(
        r"(?<![\w'’ʼ])(?:я|ми|мій|моя|моє|мої|наш\w*|нас|нам|мене|мені)(?![\w'’ʼ])",
        re.IGNORECASE,
    ),
}
_PRONOUNS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({"he", "she", "it", "they", "him", "her", "his", "their", "them"}),
    "de": frozenset({"er", "sie", "es", "ihm", "ihn", "ihr", "sein", "seine", "ihre"}),
    "uk": frozenset({"він", "вона", "воно", "вони", "його", "її", "їх", "йому", "їй"}),
}
# "Es gibt …", "It is …": an expletive, not a subject.
_EXPLETIVE_NEXT: Final = frozenset(
    {"gibt", "ist", "war", "sind", "waren", "geht", "wird", "is", "was", "has", "seems"}
)
_PROSE: Final = frozenset({"summary", "bullet", "framing"})
_NO_SOURCE_NEEDED: Final = frozenset({"heading", "note"})
_FUNCTION_WORDS: Final = frozenset(
    {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "und", "oder",
        "von", "vom", "im", "in", "mit", "für", "auf", "zu", "zum", "zur", "über", "nach",
        "bei", "aus", "als", "am", "an", "the", "a", "and", "or", "of", "on",
        "for", "to", "with", "by", "at", "from", "і", "та", "в", "у", "на", "з", "до", "про",
    }
)  # fmt: skip


# ── findings ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    code: str
    severity: str
    section_key: str | None = None
    line_index: int | None = None
    detail: str = ""  # a closed word ("too_few", "caps") — never content

    @property
    def hard(self) -> bool:
        return self.severity in HARD


@dataclass(frozen=True, slots=True)
class RegenRequest:
    """What D2 is asked to write again: a rule, a place, the facts."""

    rule: str
    section_key: str | None
    line_index: int | None
    fact_ids: tuple[str, ...]


Regenerate = Callable[
    [list[RegenRequest], list[RenderedSection]], Awaitable[list[RenderedSection] | None]
]


@dataclass
class LintContext:
    language: str
    speech_ms: int
    recording_type: str | None = None
    facts: dict[str, VerifiedFact] = field(default_factory=dict)
    known: frozenset[str] = frozenset()
    brief: dict[str, Any] = field(default_factory=dict)
    title: str | None = None

    @property
    def minutes(self) -> float:
        return self.speech_ms / 60_000


@dataclass
class LintReport:
    findings: list[Finding]
    repaired: list[RenderedSection]
    repaired_by_code: Counter[str]
    unresolved: list[Finding]
    regenerated: int = 0

    def stats(self) -> dict[str, Any]:
        return {
            "findings_by_code": _count(f.code for f in self.findings),
            "findings_by_rule": _count(f.rule for f in self.findings),
            "repaired_by_code": dict(sorted(self.repaired_by_code.items())),
            "regenerated": self.regenerated,
            "unresolved": _count(f.code for f in self.unresolved),
            "unresolved_rules": _count(f.rule for f in self.unresolved),
            "unresolved_hard": _count(f.code for f in self.unresolved if f.hard),
        }


def _count(items: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(items).items()))


def _finding(
    rule: str,
    section_key: str | None = None,
    line_index: int | None = None,
    detail: str = "",
    code: str | None = None,
) -> Finding:
    code = code or RULES[rule].code
    return Finding(rule, code, SEVERITY[code], section_key, line_index, detail)


def target_sections(minutes: float) -> int:
    """§3: ``max(3, min(8, round(D / 4)))``."""
    return max(SECTIONS_MIN, min(SECTIONS_MAX, round(minutes / MINUTES_PER_SECTION)))


# ── small readers ───────────────────────────────────────────────────


def _words(text: str) -> int:
    return len(_WORD.findall(text))


def _body(text: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s+|#{1,6}\s+)", "", text).strip()


def _tokens(text: str) -> frozenset[str]:
    return support.merge_tokens(text)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _headed(s: RenderedSection) -> bool:
    return s.role == roles.TOPICS and bool((s.title or "").strip())


def _is_bullet(line: Line) -> bool:
    return line.kind in ("bullet", "key_point") and bool(_BULLET.match(line.text))


def _is_child(line: Line) -> bool:
    match = _BULLET.match(line.text)
    return bool(line.parent) or (match is not None and len(match["indent"]) >= 2)


def _said_a_date(text: str, language: str) -> bool:
    if _has_date_word(text):
        return True
    return bool(date_mentions(text, meeting_date=date(2026, 1, 5), language=language))


def specificity(line: Line, ctx: LintContext) -> int:
    clean = _LABEL.sub("", _body(line.text))
    return support.specificity(
        clean,
        ctx.language,
        known=ctx.known,
        has_date=bool(line.dates) or _said_a_date(clean, ctx.language),
    )


def _start(line: Line, ctx: LintContext) -> int | None:
    times = [ctx.facts[i].start_ms for i in line.fact_ids if i in ctx.facts]
    return min(times) if times else None


def _span(s: RenderedSection, ctx: LintContext) -> tuple[int, int] | None:
    times = [ctx.facts[i].start_ms for ln in s.lines for i in ln.fact_ids if i in ctx.facts]
    return (min(times), max(times)) if times else None


def _names(text: str, ctx: LintContext) -> list[str]:
    """Names in a title or heading. In German every noun is capitalised, so
    a name is two or more capitalised words in a row, an acronym, or a name
    the recording knows; elsewhere any capitalised non-initial word."""
    if ctx.language == "de":
        out = [m.group(0) for m in _CAPITAL_RUN.finditer(text)]
        out += _ACRONYM.findall(text)
        out += support.entities_in(text, ctx.language, ctx.known)
    else:
        out = support.names_in(text)
    return list(dict.fromkeys(out))


def _supported(name: str, evidence: str) -> bool:
    said = evidence.casefold()
    words = [w for w in _WORD.findall(name) if len(w) > 1]
    if all(w.casefold()[:5] in said for w in words):
        return True
    # A capitalised noun before a name in German ("Gast Felix Holtermann",
    # "Chef Alex Karp") is part of the run, not of the name.
    return len(words) >= 3 and all(w.casefold()[:5] in said for w in words[1:])


def _evidence(line_ids: Iterable[str], ctx: LintContext) -> str:
    return " ".join(f"{ctx.facts[i].text} {ctx.facts[i].quote}" for i in line_ids if i in ctx.facts)


# ── the line rules (T3) — one line, the reason it fails, or None ────


def line_fault(line: Line, ctx: LintContext) -> tuple[str, str, str | None] | None:
    """``(rule, detail, code override)`` for the first rule a prose line
    breaks, in the order the repairs need; None when it meets them."""
    if line.kind not in _PROSE or not line.text.strip() or _TABLE_ROW.match(line.text):
        return None
    body = _body(line.text)
    if not line.fact_ids:
        return ("line.cited", "no_row", None)
    if line.kind == "framing":
        return None
    if _LABEL.search(body):
        return ("line.subject", "label", "D-LABEL")
    words = _LEAD.sub("", body).split()
    if words:
        first = words[0].strip(",.;:").casefold()
        following = words[1].casefold() if len(words) > 1 else ""
        pronouns = _PRONOUNS.get(ctx.language, _PRONOUNS["en"])
        if first in pronouns and not (first in ("es", "it") and following in _EXPLETIVE_NEXT):
            return ("line.subject", "pronoun", None)
    if _FIRST_PERSON.get(ctx.language, _FIRST_PERSON["en"]).search(body):
        return ("line.person", "first_person", None)
    if _other_language(body, ctx.language):
        return ("line.language", "language", None)
    cited = [ctx.facts[i] for i in line.fact_ids if i in ctx.facts]
    if any(is_copied(body, f.quote) for f in cited):
        return ("line.copy", "copy", None)
    if support.descriptive(body, ctx.language, known=ctx.known, has_date=bool(line.dates)):
        return ("line.descriptive", "descriptive", None)
    if specificity(line, ctx) == 0:
        return ("line.specific", "zero", None)
    return None


def _other_language(text: str, language: str) -> bool:
    if _words(text) < LANGUAGE_MIN_WORDS:
        return False
    cyrillic = support.cyrillic_share(text)
    if language in support.CYRILLIC_LANGUAGES:
        return cyrillic < 0.3
    if cyrillic > 0.5:
        return True
    own = support.stop_word_share(text, language)
    others = [support.stop_word_share(text, other) for other in ("en", "de") if other != language]
    # Languages share a few short words ("in"): another language is one
    # whose stop words are at least twice as present as the note's.
    return bool(others) and max(others) >= 0.2 and own * 2 <= max(others)


# ── check: every finding for one rendered document ──────────────────


def check(sections: Sequence[RenderedSection], ctx: LintContext) -> list[Finding]:
    out: list[Finding] = []
    if ctx.title is not None:
        out += [_finding("title.form", detail=d) for d in title_faults(ctx.title, ctx)]
    content = [s for s in sections if s.lines or s.text.strip()]
    if not content:
        return out
    out += _check_orientation(sections, ctx)
    headed = [s for s in sections if _headed(s)]
    out += _check_sections(headed, ctx)
    out += _check_headings(headed, ctx)
    out += _check_lines(sections, ctx)
    out += _check_volume(sections, ctx)
    return out


def title_faults(title: str, ctx: LintContext) -> list[str]:
    """§1 — ``length``, ``colons``, ``repeat``, ``generic``, ``name``."""
    text = title.strip()
    faults = []
    low, high = TITLE_CHARS
    if not low <= len(text) <= high:
        faults.append("length")
    if text.count(":") > TITLE_MAX_COLONS:
        faults.append("colons")
    words = [w.casefold() for w in _WORD.findall(text)]
    pairs = [tuple(words[i : i + 2]) for i in range(len(words) - 1)]
    if len(pairs) != len(set(pairs)):
        faults.append("repeat")
    if GENERIC_TITLE.match(text):
        faults.append("generic")
    evidence = " ".join(f"{f.text} {f.quote}" for f in ctx.facts.values())
    if evidence and any(not _supported(n, evidence) for n in _names(text, ctx)):
        faults.append("name")
    return faults


def _paragraphs(top: RenderedSection) -> tuple[list[Line], list[Line]]:
    first = [ln for ln in top.lines if ln.kind in ("framing", "presenter")]
    second = [ln for ln in top.lines if ln.kind == "summary"]
    return first, second


def _check_orientation(sections: Sequence[RenderedSection], ctx: LintContext) -> list[Finding]:
    out: list[Finding] = []
    top = next((s for s in sections if s.section_key == roles.OVERVIEW_KEY), None)
    if top is None:
        return [_finding("orient.present", detail="missing")]
    key = top.section_key
    first, second = _paragraphs(top)
    if any(_BULLET.match(ln.text) or _TABLE_ROW.match(ln.text) for ln in top.lines):
        out.append(_finding("orient.present", key, detail="bullets"))
    if not first or not second:
        out.append(_finding("orient.present", key, detail="paragraphs"))
    if first:
        out += [_finding("orient.p1", key, detail=d) for d in p1_faults(first, ctx)]
        if type_word_fault(first[0].text, ctx):
            out.append(_finding("orient.type_words", key, detail="mapping"))
    if second:
        text = " ".join(ln.text for ln in second)
        low, high = PARA2_WORDS
        if not low <= _words(text) <= high:
            out.append(_finding("orient.p2", key, detail="length"))
        low, high = PARA2_SENTENCES
        if not low <= len(second) <= high:
            out.append(_finding("orient.p2", key, detail="sentences"))
        for ln in second:
            if _QUOTE_MARKS.search(ln.text):
                out.append(_finding("orient.p2", key, top.lines.index(ln), detail="quote"))
    return out


def _roles(ctx: LintContext) -> tuple[list[str], list[str]]:
    orientation = ctx.brief.get("orientation") or {}
    return list(orientation.get("speakers") or []), list(orientation.get("guests") or [])


def p1_faults(first: Sequence[Line], ctx: LintContext) -> list[str]:
    """§2 paragraph 1 — ``length``, ``type``, ``speakers``, ``themes``,
    ``label`` (a narrator with no role entry), ``guest`` (a guest nobody
    verified), ``name``."""
    text = " ".join(ln.text for ln in first)
    folded = text.casefold()
    faults = []
    low, high = PARA1_WORDS
    if not low <= _words(text) <= high:
        faults.append("length")
    labels = overview.TYPE_LABELS.get(ctx.language, overview.TYPE_LABELS["en"])
    if not any(label.casefold() in folded for label in labels.values()) and not _model_framed(ctx):
        faults.append("type")
    speakers, guests = _roles(ctx)
    lead = overview._SPEAKERS.get(ctx.language, overview._SPEAKERS["en"]).split("{")[0].strip()
    if lead.casefold() not in folded and not any(ln.kind == "presenter" for ln in first):
        faults.append("speakers")
    themes_lead = overview._THEMES.get(ctx.language, overview._THEMES["en"]).split("{")[0].strip()
    if themes_lead.casefold() in folded:
        # To the end of the paragraph: "11. September" is not a sentence end.
        listed = text[folded.index(themes_lead.casefold()) + len(themes_lead) :]
        listed = listed.split("\n")[0].strip().rstrip(".")
        n = len([t for t in re.split(r",|\s(?:und|and|і)\s", listed) if t.strip()])
        if not THEMES[0] <= n <= THEMES[1]:
            faults.append("themes")
    else:
        faults.append("themes")
    narrator = overview.NARRATOR.get(ctx.language, overview.NARRATOR["en"])
    if _LABEL.search(text) and narrator not in speakers:
        faults.append("label")
    guest_word = overview._GUEST.get(ctx.language, overview._GUEST["en"])
    for match in re.finditer(re.escape(guest_word) + r":?\s+(?P<who>[^,.(]+)", text):
        who = match["who"].strip()
        if not any(g.split(" (")[0].strip() in who or who in g for g in guests):
            faults.append("guest")
            break
    evidence = " ".join(f"{f.text} {f.quote}" for f in ctx.facts.values())
    evidence += " " + " ".join([*speakers, *guests])
    if any(not _supported(n, evidence) for n in _names(text, ctx) if not _LABEL.search(n)):
        faults.append("name")
    return faults


def _model_framed(ctx: LintContext) -> bool:
    return bool((ctx.brief.get("orientation") or {}).get("framing"))


def type_word_fault(text: str, ctx: LintContext) -> bool:
    """The type word is the reader's word for the classified type: never a
    machine label, never another type's word."""
    if _MACHINE_LABEL.search(text):
        return True
    if not ctx.recording_type:
        return False
    labels = overview.TYPE_LABELS.get(ctx.language, overview.TYPE_LABELS["en"])
    want = labels.get(ctx.recording_type)
    if not want or text.startswith(want):
        return False
    return any(text.startswith(label) for key, label in labels.items() if label != want)


def _check_sections(headed: list[RenderedSection], ctx: LintContext) -> list[Finding]:
    out: list[Finding] = []
    if ctx.minutes >= SECTIONS_FROM_MINUTES:
        target = target_sections(ctx.minutes)
        if len(headed) < max(SECTIONS_MIN, target - SECTIONS_TOLERANCE):
            out.append(_finding("sections.count", detail="too_few"))
        elif len(headed) > min(SECTIONS_MAX, target + SECTIONS_TOLERANCE):
            out.append(_finding("sections.count", detail="too_many"))
    low, high = POINTS_PER_SECTION
    for s in headed:
        points = _points(s)
        if points < low:
            out.append(_finding("sections.size", s.section_key, detail="one"))
        elif points > high:
            out.append(_finding("sections.size", s.section_key, detail="many"))
    spans = [(s.section_key, sp) for s in headed if (sp := _span(s, ctx))]
    for (_a, (first_a, last_a)), (key_b, (first_b, _l)) in zip(spans, spans[1:], strict=False):
        if first_b < first_a:
            out.append(_finding("sections.order", key_b, detail="order"))
        elif first_b < last_a:
            out.append(_finding("sections.order", key_b, detail="interleaved"))
    return out


def _points(s: RenderedSection) -> int:
    return sum(
        1
        for ln in s.lines
        if (ln.kind in ("bullet", "key_point") and not _is_child(ln)) or ln.kind == "figure"
    )


def heading_faults(title: str) -> list[str]:
    heading = title.strip()
    faults = []
    chapter = re.match(r"^\d{1,2}:\d{2}\b", heading)
    words = _words(re.sub(r"^\d{1,2}:\d{2}\s*—\s*", "", heading))
    low, high = HEADING_WORDS
    if not chapter and not low <= words <= high:
        faults.append("words")
    if len(heading) > HEADING_MAX_CHARS:
        faults.append("chars")
    letters = [c for c in heading if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters) and len(heading.split()) > 1:
        faults.append("caps")
    if heading.endswith((":", ".", "!", ";")):
        faults.append("punctuation")
    if heading.endswith("?"):
        faults.append("question")
    return faults


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _check_headings(headed: list[RenderedSection], ctx: LintContext) -> list[Finding]:
    out: list[Finding] = []
    title_tokens = _tokens(ctx.title or "")
    seen: list[frozenset[str]] = []
    for s in headed:
        heading = (s.title or "").strip()
        key = s.section_key
        faults = heading_faults(heading)
        out += [_finding("heading.form", key, detail=d) for d in faults]
        if heading.casefold().rstrip(":.!?") in GENERIC_HEADINGS:
            out.append(_finding("heading.generic", key, detail="generic"))
        evidence = _evidence((i for ln in s.lines for i in ln.fact_ids), ctx)
        # Names are read in the heading as it will be written.
        named = _recase(heading, ctx.language, evidence) if "caps" in faults else heading
        if evidence and any(not _supported(n, evidence) for n in _names(named, ctx)):
            out.append(_finding("heading.nouns", key, detail="name"))
        tokens = _tokens(heading)
        if any(_overlap(tokens, other) > HEADING_MAX_SHARED for other in seen):
            out.append(_finding("heading.distinct", key, detail="overlap"))
        elif len(tokens) >= 2 and tokens <= title_tokens:
            out.append(_finding("heading.distinct", key, detail="title"))
        seen.append(tokens)
    return out


def _check_lines(sections: Sequence[RenderedSection], ctx: LintContext) -> list[Finding]:
    out: list[Finding] = []
    for s in sections:
        children = 0
        parent_tokens: frozenset[str] = frozenset()
        for n, ln in enumerate(s.lines):
            if not ln.text.strip():
                continue
            if ln.kind not in _NO_SOURCE_NEEDED and not ln.fact_ids and ln.kind not in _PROSE:
                out.append(_finding("line.cited", s.section_key, n, "no_row"))
            if _GLYPHS.search(ln.text) or _MARKDOWN.search(ln.text):
                out.append(_finding("line.glyph", s.section_key, n, "glyph"))
            fault = line_fault(ln, ctx)
            if fault:
                rule, detail, code = fault
                out.append(_finding(rule, s.section_key, n, detail, code))
            if ln.kind in _PROSE and _certainty_missing(ln, ctx):
                out.append(_finding("line.certainty", s.section_key, n, "marker"))
            if ln.kind == "summary" and _words(ln.text) > SENTENCE_MAX_WORDS:
                out.append(_finding("line.length", s.section_key, n, "sentence"))
            if not _is_bullet(ln):
                continue
            body = _body(ln.text)
            if _is_child(ln):
                children += 1
                if children > MAX_CHILDREN:
                    out.append(_finding("line.child", s.section_key, n, "too_many"))
                if parent_tokens and _jaccard(_tokens(body), parent_tokens) >= CHILD_RESTATES:
                    out.append(_finding("line.child", s.section_key, n, "restates"))
                continue
            children = 0
            parent_tokens = _tokens(body)
            if _headed(s):
                low, high = BULLET_WORDS
                if not low <= _words(body) <= high:
                    out.append(_finding("line.length", s.section_key, n, "bullet"))
    return out


def _certainty_missing(line: Line, ctx: LintContext) -> bool:
    unsure = [
        ctx.facts[i]
        for i in line.fact_ids
        if i in ctx.facts and ctx.facts[i].certainty in support.UNSURE_CERTAINTIES
    ]
    if not unsure:
        return False
    core = _body(line.text)
    return patch_claim(core, unsure, ctx.language) != core


def _body_lines(sections: Sequence[RenderedSection]) -> list[Line]:
    return [
        ln
        for s in sections
        for ln in s.lines
        if ln.text.strip() and ln.kind not in _NO_SOURCE_NEEDED and not _TABLE_ROW.match(ln.text)
    ]


def body_words(sections: Sequence[RenderedSection]) -> int:
    return sum(_words(_body(ln.text)) for ln in _body_lines(sections))


def volume_band(minutes: float) -> tuple[float, float]:
    return WORDS_PER_MINUTE[0] * minutes, WORDS_PER_MINUTE[1] * minutes


def _check_volume(sections: Sequence[RenderedSection], ctx: LintContext) -> list[Finding]:
    out: list[Finding] = []
    if ctx.minutes >= VOLUME_FROM_MINUTES:
        low, high = volume_band(ctx.minutes)
        words = body_words(sections)
        if words < low:
            out.append(_finding("volume.words", detail="below"))
        elif words > high:
            out.append(_finding("volume.words", detail="above"))
    placed = _placed(sections)
    for j in range(len(placed)):
        if any(
            _pair(sections, placed[i][0], placed[j][0])
            and _jaccard(placed[i][2], placed[j][2]) >= REDUNDANT_JACCARD
            for i in range(j)
        ):
            key = sections[placed[j][0]].section_key
            out.append(_finding("redundancy", key, placed[j][1], "duplicate"))
    return out


def _placed(sections: Sequence[RenderedSection]) -> list[tuple[int, int, frozenset[str]]]:
    """Lines that can repeat one another (framing, presenter, figures and
    tables are never duplicates)."""
    return [
        (si, n, _tokens(_body(ln.text)))
        for si, s in enumerate(sections)
        for n, ln in enumerate(s.lines)
        if ln.kind in ("summary", "bullet", "key_point") and not _TABLE_ROW.match(ln.text)
    ]


def _pair(sections: Sequence[RenderedSection], a: int, b: int) -> bool:
    """Two lines can be duplicates unless one is in the orientation and the
    other is not: §2 has paragraph 2 name "the two or three most specific
    facts", which the sections carry too."""
    top_a = sections[a].section_key == roles.OVERVIEW_KEY
    top_b = sections[b].section_key == roles.OVERVIEW_KEY
    return top_a == top_b


# ── repair ──────────────────────────────────────────────────────────


def _text_of(section: RenderedSection, lines: Sequence[Line]) -> str:
    if section.section_key == roles.OVERVIEW_KEY:
        first = [ln.text for ln in lines if ln.kind in ("framing", "presenter")]
        rest = [ln.text for ln in lines if ln.kind not in ("framing", "presenter")]
        return "\n\n".join(p for p in ("\n".join(first), "\n".join(rest)) if p)
    out: list[str] = []
    for ln in lines:
        table = bool(_TABLE_ROW.match(ln.text))
        if out and table != bool(_TABLE_ROW.match(out[-1])):
            out.append("")
        out.append(ln.text)
    return "\n".join(out)


def _with_lines(
    section: RenderedSection, lines: Sequence[Line], ctx: LintContext
) -> RenderedSection:
    ids = list(dict.fromkeys(i for ln in lines for i in ln.fact_ids))
    known = {f.item_key: f for f in section.facts}
    facts = tuple(known.get(i) or ctx.facts[i] for i in ids if i in known or i in ctx.facts)
    return replace(section, lines=tuple(lines), text=_text_of(section, lines), facts=facts)


def repair(
    sections: Sequence[RenderedSection], ctx: LintContext
) -> tuple[list[RenderedSection], Counter[str]]:
    """Every deterministic repair and fallback, in the order they depend on
    each other. Counts by taxonomy code what it changed."""
    done: Counter[str] = Counter()
    out = [_fix_text(s, ctx, done) for s in sections]
    out = [_drop_lines(s, ctx, done) for s in out]
    out = _repair_orientation(out, ctx, done)
    out = _repair_headings(out, ctx, done)
    out = _repair_sections(out, ctx, done)
    # After the orientation ladder and the chapters, which add lines.
    out = _drop_redundant(out, ctx, done)
    out = _repair_volume(out, ctx, done)
    out = _repair_sections(out, ctx, done, count=False)
    return [s for s in out if s.lines], done


def _prefixed(original: str, core: str) -> str:
    prefix = re.match(r"^\s*-\s", original)
    return (prefix.group(0) if prefix else "") + core


def _fix_text(s: RenderedSection, ctx: LintContext, done: Counter[str]) -> RenderedSection:
    """line.glyph (strip) and line.certainty (the Q4 patch)."""
    lines = []
    changed = False
    for ln in s.lines:
        text = ln.text
        if _GLYPHS.search(text) or _MARKDOWN.search(text):
            text = _MARKDOWN.sub("", _GLYPHS.sub("", text))
            text = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).rstrip()
            done[RULES["line.glyph"].code] += 1
        if ln.kind in _PROSE and _certainty_missing(replace(ln, text=text), ctx):
            unsure = [ctx.facts[i] for i in ln.fact_ids if i in ctx.facts]
            text = _prefixed(text, patch_claim(_body(text), unsure, ctx.language))
            done[RULES["line.certainty"].code] += 1
        changed = changed or text != ln.text
        lines.append(replace(ln, text=text) if text != ln.text else ln)
    return _with_lines(s, lines, ctx) if changed else s


def _drop_lines(s: RenderedSection, ctx: LintContext, done: Counter[str]) -> RenderedSection:
    """A line that breaks a line rule is not rendered (its fact stays
    evidence); a first-person opener is fixed mechanically first (F2); a
    sub-point goes with its parent; past three sub-points, or one that
    restates its parent, is cut."""
    kept: list[Line] = []
    dropped_parent = False
    children = 0
    parent_tokens: frozenset[str] = frozenset()
    voice = _FIRST_PERSON.get(ctx.language, _FIRST_PERSON["en"])
    for ln in s.lines:
        child = _is_bullet(ln) and _is_child(ln)
        if child:
            if dropped_parent:
                continue
            children += 1
            restates = parent_tokens and (
                _jaccard(_tokens(_body(ln.text)), parent_tokens) >= CHILD_RESTATES
            )
            if children > MAX_CHILDREN or restates:
                done[RULES["line.child"].code] += 1
                continue
        elif _is_bullet(ln):
            children = 0
            parent_tokens = _tokens(_body(ln.text))
        fault = line_fault(ln, ctx)
        if fault and fault[0] == "line.person":
            fixed = support.mechanical_third_person(_body(ln.text))
            if fixed and not voice.search(fixed):
                ln = replace(ln, text=_prefixed(ln.text, fixed))
                fault = line_fault(ln, ctx)
        if fault:
            done[fault[2] or RULES[fault[0]].code] += 1
            if _is_bullet(ln) and not child:
                dropped_parent = True
            continue
        if _is_bullet(ln) and not child:
            dropped_parent = False
        kept.append(ln)
    return _with_lines(s, kept, ctx) if len(kept) != len(s.lines) else s


def _drop_redundant(
    sections: list[RenderedSection], ctx: LintContext, done: Counter[str]
) -> list[RenderedSection]:
    """Drop the later of two lines saying the same — or the earlier, when
    the later is the more specific one and the earlier is not in the
    orientation."""
    placed = _placed(sections)
    spec = {(si, n): specificity(sections[si].lines[n], ctx) for si, n, _t in placed}
    drop: set[tuple[int, int]] = set()
    for j in range(len(placed)):
        for i in range(j):
            a, b = (placed[i][0], placed[i][1]), (placed[j][0], placed[j][1])
            if a in drop or not _pair(sections, a[0], b[0]):
                continue
            if _jaccard(placed[i][2], placed[j][2]) < REDUNDANT_JACCARD:
                continue
            earlier_goes = spec[b] > spec[a] and sections[a[0]].section_key != roles.OVERVIEW_KEY
            drop.add(a if earlier_goes else b)
            done[RULES["redundancy"].code] += 1
            break
    if not drop:
        return sections
    return [
        _with_lines(s, [ln for n, ln in enumerate(s.lines) if (si, n) not in drop], ctx)
        if any(d[0] == si for d in drop)
        else s
        for si, s in enumerate(sections)
    ]


def _repair_orientation(
    sections: list[RenderedSection], ctx: LintContext, done: Counter[str]
) -> list[RenderedSection]:
    """T4: map the type word; rebuild paragraph 1 by code when it fails;
    take the next ladder rung below three sentences, trim past six or 140
    words; compose the whole block by code when it is missing. Bullets
    above the first heading were dropped with the line rules or go now."""
    code = RULES["orient.present"].code
    index = next((n for n, s in enumerate(sections) if s.section_key == roles.OVERVIEW_KEY), None)
    if index is None:
        if not any(not f.evidence_only for f in ctx.facts.values()):
            return sections
        sections = [RenderedSection(roles.OVERVIEW_KEY, roles.SUMMARY, ""), *sections]
        index = 0
        done[code] += 1
    top = sections[index]
    stray = [ln for ln in top.lines if _BULLET.match(ln.text) or _TABLE_ROW.match(ln.text)]
    if stray:
        done[code] += len(stray)
    first, second = _paragraphs(top)
    second = [ln for ln in second if not _BULLET.match(ln.text)]
    if first and type_word_fault(first[0].text, ctx):
        mapped = _map_type_word(first[0].text, ctx)
        if mapped != first[0].text:
            first = [replace(first[0], text=mapped), *first[1:]]
            done[RULES["orient.type_words"].code] += 1
    if not first or p1_faults(first, ctx):
        rebuilt = _composed_p1(ctx)
        presenter = [ln for ln in first if ln.kind == "presenter"]
        if rebuilt and (
            not first or len(p1_faults([rebuilt, *presenter], ctx)) < len(p1_faults(first, ctx))
        ):
            first = [rebuilt, *presenter]
            done[RULES["orient.p1"].code] += 1
    second = [ln for ln in second if not _QUOTE_MARKS.search(ln.text)]
    if len(second) < PARA2_SENTENCES[0]:
        ladder = _composed_p2(ctx, second)
        if len(ladder) > len(second):
            second = ladder
            done[RULES["orient.p2"].code] += 1
    while len(second) > PARA2_SENTENCES[0] and (
        len(second) > PARA2_SENTENCES[1]
        or _words(" ".join(ln.text for ln in second)) > PARA2_WORDS[1]
    ):
        second = second[:-1]
        done[RULES["orient.p2"].code] += 1
    lines = [*first, *second]
    if [ln.text for ln in lines] == [ln.text for ln in top.lines]:
        return sections
    return [*sections[:index], _with_lines(top, lines, ctx), *sections[index + 1 :]]


def _map_type_word(text: str, ctx: LintContext) -> str:
    labels = overview.TYPE_LABELS.get(ctx.language, overview.TYPE_LABELS["en"])
    want = labels.get(ctx.recording_type or "") or labels["meeting"]
    text = _MACHINE_LABEL.sub(want, text, count=1)
    for label in sorted(labels.values(), key=len, reverse=True):
        if label != want and text.startswith(label):
            return want + text[len(label) :]
    return text


def _composed_p1(ctx: LintContext) -> Line | None:
    orientation = ctx.brief.get("orientation") or {}
    ids = tuple(i for i in ctx.brief.get("key_fact_ids") or [] if i in ctx.facts)
    ids = ids or tuple(list(ctx.facts)[:1])
    if not ids:
        return None
    text = overview.first_paragraph(
        language=ctx.language,
        recording_type=ctx.recording_type,
        subject=orientation.get("subject") or "",
        speakers=list(orientation.get("speakers") or []),
        guests=list(orientation.get("guests") or []),
        themes=list(orientation.get("themes") or []),
    )
    return Line(text, "framing", ids)


def _composed_p2(ctx: LintContext, current: list[Line]) -> list[Line]:
    facts = sorted(ctx.facts.values(), key=lambda f: f.start_ms)
    candidates = []
    for sentence, ids in overview.composed_sentences(
        facts, language=ctx.language, known=ctx.known, key_ids=ctx.brief.get("key_fact_ids")
    ):
        line = Line(sentence, "summary", tuple(ids))
        if line_fault(line, ctx) is None:
            candidates.append(line)
    return candidates if len(candidates) > len(current) else current


def _fallback_heading(s: RenderedSection, ctx: LintContext) -> str:
    facts = [ctx.facts[i] for ln in s.lines for i in ln.fact_ids if i in ctx.facts]
    if not facts:
        return s.title or ""
    name = overview._top_name(facts, ctx.language, ctx.known)
    if not name:
        # German names the recording does not know: runs of capitalised words.
        runs = Counter(m.group(0) for f in facts for m in _CAPITAL_RUN.finditer(f.text))
        name = runs.most_common(1)[0][0] if runs else ""
    stamp = overview.mmss(min(f.start_ms for f in facts))
    return f"{stamp} — {name}" if name else stamp


def _recase(heading: str, language: str, evidence: str = "") -> str:
    """All caps → sentence case; German keeps its nouns capitalised (every
    word but the function words, the closest code can get). A word stays
    upper case only when the facts spell it so ("USA", "CEO")."""
    spelled = set(_ACRONYM.findall(evidence))
    out = []
    for n, w in enumerate(heading.split()):
        low = w.lower()
        if w.strip(":,.;") in spelled:
            out.append(w)
        elif language == "de":
            out.append(low if n and low in _FUNCTION_WORDS else w[:1].upper() + w[1:].lower())
        else:
            out.append(w[:1].upper() + w[1:].lower() if n == 0 else low)
    return " ".join(out)


def _repair_headings(
    sections: list[RenderedSection], ctx: LintContext, done: Counter[str]
) -> list[RenderedSection]:
    """T2: strip punctuation and "?", recase all caps, cut past 60
    characters to its first 8 words; a generic heading, one naming what
    its section does not say, or one restating the title takes the
    fallback heading (the section's entity and first time); a heading
    saying what the one before it says merges the two sections."""
    out: list[RenderedSection] = []
    title_tokens = _tokens(ctx.title or "")
    code = RULES["heading.form"].code
    for s in sections:
        if not _headed(s):
            out.append(s)
            continue
        heading = (s.title or "").strip()
        faults = heading_faults(heading)
        if "punctuation" in faults or "question" in faults:
            heading = heading.rstrip(":.!?; ").strip()
            done[code] += 1
        evidence = _evidence((i for ln in s.lines for i in ln.fact_ids), ctx)
        if "caps" in faults:
            heading = _recase(heading, ctx.language, evidence)
            done[code] += 1
        if "chars" in faults:
            heading = " ".join(heading.split()[: HEADING_WORDS[1]])
            done[code] += 1
        generic = heading.casefold() in GENERIC_HEADINGS
        unsupported = bool(evidence) and any(
            not _supported(n, evidence) for n in _names(heading, ctx)
        )
        restates = len(_tokens(heading)) >= 2 and _tokens(heading) <= title_tokens
        if generic or unsupported or restates:
            heading = _fallback_heading(s, ctx)
            done[code] += 1
        previous = out[-1] if out and _headed(out[-1]) else None
        if (
            previous
            and _overlap(_tokens(previous.title or ""), _tokens(heading)) > HEADING_MAX_SHARED
        ):
            out[-1] = _merge(previous, s, ctx)
            done[code] += 1
            continue
        out.append(replace(s, title=heading) if heading != s.title else s)
    return out


def _merge(a: RenderedSection, b: RenderedSection, ctx: LintContext) -> RenderedSection:
    return _with_lines(a, [*a.lines, *b.lines], ctx)


def _groups(s: RenderedSection) -> list[list[Line]]:
    """Top-level points with their sub-points (and any table rows)."""
    groups: list[list[Line]] = []
    for ln in s.lines:
        point = (_is_bullet(ln) and not _is_child(ln)) or ln.kind == "figure"
        if groups and not point:
            groups[-1].append(ln)
        else:
            groups.append([ln])
    return groups


def _split(s: RenderedSection, ctx: LintContext, taken: set[str]) -> list[RenderedSection]:
    """At the largest time gap between points; the second half is headed
    by its entity and time."""
    groups = _groups(s)
    low = POINTS_PER_SECTION[0]
    if len(groups) < 2 * low:
        return [s]
    starts = [min((t for ln in g if (t := _start(ln, ctx)) is not None), default=0) for g in groups]
    cut = max(range(low, len(groups) - low + 1), key=lambda k: starts[k] - starts[k - 1])
    first = _with_lines(s, [ln for g in groups[:cut] for ln in g], ctx)
    second = _with_lines(s, [ln for g in groups[cut:] for ln in g], ctx)
    title = _fallback_heading(second, ctx)
    key = roles.generated_key(title, taken)
    taken.add(key)
    return [first, replace(second, title=title, section_key=key)]


def _repair_sections(
    sections: list[RenderedSection], ctx: LintContext, done: Counter[str], *, count: bool = True
) -> list[RenderedSection]:
    """T1: order by first cited time; a one-point section joins its
    neighbour in time; past six points it splits at the largest gap; too
    many sections merge where headings share ≥ 40 % or both spans fit in
    90 s; too few (nothing regenerated) fall back to chapters."""
    code = RULES["sections.order"].code
    head = [s for s in sections if not _headed(s)]
    topics = [s for s in sections if _headed(s)]
    ordered = sorted(topics, key=lambda s: (_span(s, ctx) or (10**12, 0))[0])
    if [s.section_key for s in ordered] != [s.section_key for s in topics]:
        done[code] += 1
    topics = ordered
    low, high = POINTS_PER_SECTION
    n = 0
    while n < len(topics) and len(topics) > 1:
        if _points(topics[n]) < low:
            a = n - 1 if n > 0 else n
            topics[a : a + 2] = [_merge(topics[a], topics[a + 1], ctx)]
            done[code] += 1
            n = max(0, a - 1)
            continue
        n += 1
    taken = {s.section_key for s in sections}
    split: list[RenderedSection] = []
    for s in topics:
        parts = _split(s, ctx, taken) if _points(s) > high else [s]
        done[code] += len(parts) - 1
        split += parts
    topics = split
    if count and ctx.minutes >= SECTIONS_FROM_MINUTES:
        target = target_sections(ctx.minutes)
        while len(topics) > min(SECTIONS_MAX, target + SECTIONS_TOLERANCE):
            pair = _mergeable_pair(topics, ctx)
            if pair is None:
                break
            topics[pair : pair + 2] = [_merge(topics[pair], topics[pair + 1], ctx)]
            done[code] += 1
        if len(topics) < max(SECTIONS_MIN, target - SECTIONS_TOLERANCE):
            chaptered = _chapters(ctx, taken)
            if len(chaptered) > len(topics):
                topics = chaptered
                done[code] += 1
    return [*head, *topics]


def _mergeable_pair(topics: list[RenderedSection], ctx: LintContext) -> int | None:
    for k in range(len(topics) - 1):
        share = _overlap(_tokens(topics[k].title or ""), _tokens(topics[k + 1].title or ""))
        a, b = _span(topics[k], ctx), _span(topics[k + 1], ctx)
        short = bool(a and b and max(a[1], b[1]) - min(a[0], b[0]) < MERGE_SPAN_MS)
        if share >= MERGE_HEADING_SHARE or short:
            return k
    return None


def _chapters(ctx: LintContext, taken: set[str]) -> list[RenderedSection]:
    """Amendment §2.6's chapters, their lines held to the line rules."""
    out = []
    facts = sorted(ctx.facts.values(), key=lambda f: f.start_ms)
    for title, bullets, _ids in overview.chapters(facts, language=ctx.language, known=ctx.known):
        lines = []
        for text, ids, _children in bullets:
            line = Line(f"- {text.strip().rstrip('.')}", "bullet", tuple(ids))
            if line_fault(line, ctx) is None:
                lines.append(line)
        if len(lines) < POINTS_PER_SECTION[0]:
            continue
        key = roles.generated_key(title, taken)
        taken.add(key)
        out.append(_with_lines(RenderedSection(key, roles.TOPICS, "", title=title), lines, ctx))
    return out


def _repair_volume(
    sections: list[RenderedSection], ctx: LintContext, done: Counter[str]
) -> list[RenderedSection]:
    """Below 8·D: render facts that meet the line rules and are not yet
    rendered, by time, into the section whose span they fall in; above
    18·D: drop points from the least specific up, never below two per
    section."""
    if ctx.minutes < VOLUME_FROM_MINUTES:
        return sections
    low, high = volume_band(ctx.minutes)
    code = RULES["volume.words"].code
    words = body_words(sections)
    sections = list(sections)
    if words < low:
        cited = {i for s in sections for ln in s.lines for i in ln.fact_ids}
        topics = [n for n, s in enumerate(sections) if _headed(s)]
        for fact in sorted(ctx.facts.values(), key=lambda f: f.start_ms):
            if words >= low or not topics:
                break
            if fact.item_key in cited or fact.evidence_only or fact.figure or fact.person:
                continue
            line = Line(f"- {fact.text.strip().rstrip('.')}", "bullet", (fact.item_key,))
            if line_fault(line, ctx) is not None:
                continue
            home = _home(sections, topics, fact.start_ms, ctx)
            if home is None:
                break
            lines = _insert_by_time(list(sections[home].lines), line, ctx)
            sections[home] = _with_lines(sections[home], lines, ctx)
            words += _words(_body(line.text))
            done[code] += 1
    elif words > high:
        candidates = sorted(
            (specificity(ln, ctx), -n, si, n)
            for si, s in enumerate(sections)
            if _headed(s)
            for n, ln in enumerate(s.lines)
            if _is_bullet(ln) and not _is_child(ln)
        )
        drop: set[tuple[int, int]] = set()
        points = {si: _points(s) for si, s in enumerate(sections)}
        for _spec, _order, si, n in candidates:
            if words <= high:
                break
            if points[si] <= POINTS_PER_SECTION[0]:
                continue
            owned = sections[si].lines
            group = [n]
            for k in range(n + 1, len(owned)):
                if not _is_child(owned[k]):
                    break
                group.append(k)
            words -= sum(_words(_body(owned[k].text)) for k in group)
            drop.update((si, k) for k in group)
            points[si] -= 1
            done[code] += 1
        sections = [
            _with_lines(s, [ln for n, ln in enumerate(s.lines) if (si, n) not in drop], ctx)
            if any(d[0] == si for d in drop)
            else s
            for si, s in enumerate(sections)
        ]
    return sections


def _home(
    sections: list[RenderedSection], topics: list[int], start_ms: int, ctx: LintContext
) -> int | None:
    best, distance = None, None
    for n in topics:
        if _points(sections[n]) >= POINTS_PER_SECTION[1]:
            continue
        span = _span(sections[n], ctx)
        if span is None:
            continue
        if span[0] <= start_ms <= span[1]:
            gap = 0
        else:
            gap = min(abs(start_ms - span[0]), abs(start_ms - span[1]))
        if distance is None or gap < distance:
            best, distance = n, gap
    return best


def _insert_by_time(lines: list[Line], line: Line, ctx: LintContext) -> list[Line]:
    at = _start(line, ctx) or 0
    for n, ln in enumerate(lines):
        start = _start(ln, ctx)
        if _is_bullet(ln) and not _is_child(ln) and start is not None and start > at:
            return [*lines[:n], line, *lines[n:]]
    return [*lines, line]


# ── lint and enforce ────────────────────────────────────────────────


def lint(sections: Sequence[RenderedSection], ctx: LintContext) -> LintReport:
    """Findings, the repaired document, and what is still found in it."""
    findings = check(sections, ctx)
    repaired, done = repair(list(sections), ctx)
    return LintReport(findings, repaired, done, check(repaired, ctx))


def context_of(
    document: Any, *, known: frozenset[str] = frozenset(), title: str | None = None
) -> LintContext:
    stats = document.stats or {}
    speech = int(stats.get("speech_ms") or 0) - int(stats.get("excluded_ms") or 0)
    orientation = (document.brief or {}).get("orientation") or {}
    names = set(known) | set(orientation.get("names") or [])
    names |= {f.person.name for f in document.facts if getattr(f, "person", None)}
    names |= {n.split(" (")[0] for n in orientation.get("guests") or []}
    names |= set(orientation.get("speakers") or [])
    return LintContext(
        language=str(stats.get("language") or "en"),
        speech_ms=max(0, speech),
        recording_type=stats.get("recording_type"),
        facts={f.item_key: f for f in document.facts},
        known=frozenset(w for n in names for w in [n, *n.split()]),
        brief=dict(document.brief or {}),
        title=title,
    )


async def enforce(
    document: Any,
    *,
    regenerate: Regenerate | None = None,
    known: frozenset[str] = frozenset(),
    title: str | None = None,
) -> Any:
    """The worker's and the harness's call: lint, send hard findings to D2
    once, repair and fall back, record. Never raises: a linter that fails
    leaves the document as it was and says so (``stats.lint.error``)."""
    try:
        ctx = context_of(document, known=known, title=title)
        sections = list(document.sections)
        findings = check(sections, ctx)
        regenerated = 0
        requests = [
            RegenRequest(
                f.rule,
                f.section_key,
                f.line_index,
                _fact_ids_at(sections, f.section_key, f.line_index),
            )
            for f in findings
            if f.hard and RULES[f.rule].hook
        ]
        if regenerate is not None and requests:
            fresh = await regenerate(requests, sections)
            if fresh:
                sections = list(fresh)
                regenerated = len(requests)
        repaired, done = repair(sections, ctx)
        report = LintReport(findings, repaired, done, check(repaired, ctx), regenerated)
        document.sections = report.repaired
        document.stats = {**document.stats, "lint": report.stats()}
    except Exception:  # noqa: BLE001 — the linter never blocks a note by crashing
        logger.warning("doclint.failed", exc_info=True)
        document.stats = {**document.stats, "lint": {"error": True}}
    return document


def _fact_ids_at(
    sections: Sequence[RenderedSection], key: str | None, index: int | None
) -> tuple[str, ...]:
    section = next((s for s in sections if s.section_key == key), None)
    if section is None:
        return ()
    if index is None:
        return tuple(dict.fromkeys(i for ln in section.lines for i in ln.fact_ids))
    return tuple(section.lines[index].fact_ids) if index < len(section.lines) else ()


def as_rendered(
    sections: Iterable[dict[str, Any]], lines: Iterable[dict[str, Any]]
) -> list[RenderedSection]:
    """Produced dicts (eval) or a fixture → rendered sections."""
    by_key: dict[str, list[Line]] = {}
    for ln in lines:
        by_key.setdefault(ln.get("section_key", ""), []).append(
            Line(
                text=ln["text"],
                kind=ln.get("kind", ""),
                fact_ids=tuple(ln.get("fact_ids") or ()),
                parent="parent" if ln.get("parent") else None,
            )
        )
    out = []
    for sec in sections:
        own = tuple(by_key.get(sec["section_key"], ()))
        section = RenderedSection(
            section_key=sec["section_key"],
            role=sec.get("role", ""),
            text=sec.get("text", ""),
            title=sec.get("title"),
            lines=own,
        )
        if not section.text and own:
            section = dataclasses.replace(section, text=_text_of(section, own))
        out.append(section)
    return out


# ── The standard §8: the two rubric questions code can answer ───────


def rubric_auto(sections: Sequence[RenderedSection], ctx: LintContext) -> dict[str, Any]:
    """Q3 (share of bullets with a name, number, date or term: ≥ 90 % → 2,
    60–89 % → 1, else 0) and Q7 (body words within 8·D–18·D → 2, within
    25 % of the band → 1, else 0). None when there is nothing to judge."""
    bullets = [ln for s in sections for ln in s.lines if _is_bullet(ln) and not _is_child(ln)]
    specific = sum(1 for ln in bullets if specificity(ln, ctx) > 0)
    share = (specific / len(bullets)) if bullets else None
    q3 = None if share is None else 2 if share >= 0.9 else 1 if share >= 0.6 else 0
    q7: int | None = None
    words = body_words(sections)
    if ctx.minutes >= VOLUME_FROM_MINUTES:
        low, high = volume_band(ctx.minutes)
        q7 = 2 if low <= words <= high else 1 if 0.75 * low <= words <= 1.25 * high else 0
    return {"Q3": q3, "Q7": q7, "specific_share": share, "words": words}
