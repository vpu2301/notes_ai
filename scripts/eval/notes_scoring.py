"""Scorers for every notes-audit metric: pure functions, a gold meeting and an arm's
``produced`` dict in, numbers out. Pinned by ``tests/unit/test_notes_scoring.py``.
Sprint R0 removed the writing path; the lexical rules the scorer shares with the item
writer live in ``note_service.domain.text``, the rest in ``_textrules``. Sprint P3
rewires the harness to read stored notes.

    produced = {"lines": [...], "facts": [...], "stats": {...}, "brief": {...},
                "noise_ranges": [...], "title": str | None, "evidence": "facts" | "transcript"}

``evidence`` is what a line's support is checked against (the single-pass arm cites
nothing, so its lines are checked against the whole transcript). Reports carry numbers
and ids only: a failed ``must_*`` check is reported as the INDEX of the string.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ENGINE_SRC = Path(__file__).resolve().parents[2] / "services" / "note-service" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))

from note_service.domain import text as text_rules  # noqa: E402

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import _normalize  # noqa: E402
import _textrules  # noqa: E402

# ── Matching gold text to lines ──

# Share of a gold fact's content words a line must carry to match it:
# lenient on wording, strict on content.
MATCH_THRESHOLD = 0.6

_WORD = re.compile(r"[\w']+", re.UNICODE)
# Stopwords for the three shipped languages.
STOP = frozenset(
    # fmt: off
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "will",
        "would",
        "der",
        "die",
        "das",
        "und",
        "oder",
        "von",
        "zu",
        "für",
        "am",
        "mit",
        "aus",
        "ist",
        "sind",
        "war",
        "waren",
        "wird",
        "werden",
        "і",
        "та",
        "в",
        "на",
        "до",
        "з",
        "із",
        "для",
        "що",
        "це",
        "є",
        "був",
        "була",
    ]
    # fmt: on
)


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


def overlap(
    gold: str, produced: str, language: str = "en", holders: frozenset[str] = frozenset()
) -> float:
    """Gold words found in the produced line, both through ``_normalize.fold`` (a
    reporting clause or holder suffix is not a claim), each with the compound rule."""
    g = words(_normalize.fold(gold, language, holders=holders))
    have = words(_normalize.fold(produced, language, holders=holders))
    if not g:
        return 0.0
    hit = sum(1 for w in g if w in have or any(_normalize._token_matches(w, h) for h in have))
    return hit / len(g)


def best_match(
    gold: str, lines: list[str], language: str = "en", holders: frozenset[str] = frozenset()
) -> tuple[int, float]:
    scored = [(i, overlap(gold, line, language, holders)) for i, line in enumerate(lines)]
    return max(scored, key=lambda p: p[1], default=(-1, 0.0))


# ── Support: does what a line says rest on what it cites? ───────────

REDUNDANT_JACCARD = 0.6
# Lines the metrics look at (headings and the transcript note are structure).
_NOT_CONTENT = frozenset({"heading", "note"})
# Lines a model composes about facts, so the ones that can overstate them.
COMPOSED = frozenset({"framing", "summary", "bullet"})
_UNSURE = frozenset({"opinion", "prediction", "proposal", "allegation", "estimate"})

# The hedge markers are the engine's (``support.MODALITY_MARKERS``).

# Context-pass recording names mapped onto the gold enum (single-pass arm,
# older reports).
TYPE_ALIASES: dict[str, str] = {
    "meeting": "meeting",
    "team meeting": "meeting",
    "teambesprechung": "meeting",
    "besprechung": "meeting",
    "meeting notes": "meeting",
    "командна зустріч": "meeting",
    "зустріч": "meeting",
    "client call": "client_call",
    "kundengespräch": "client_call",
    "sales call": "sales_call",
    "verkaufsgespräch": "sales_call",
    "продажний дзвінок": "sales_call",
    "interview": "interview",
    "інтерв'ю": "interview",
    "one-on-one": "one_on_one",
    "one on one": "one_on_one",
    "1:1": "one_on_one",
    "einzelgespräch": "one_on_one",
    "розмова один на один": "one_on_one",
    "podcast": "podcast_broadcast",
    "broadcast": "podcast_broadcast",
    "news": "podcast_broadcast",
    "nachrichten": "podcast_broadcast",
    "nachrichtenpodcast": "podcast_broadcast",
    "sendung": "podcast_broadcast",
    "подкаст": "podcast_broadcast",
    "lecture": "lecture_webinar",
    "webinar": "lecture_webinar",
    "talk": "lecture_webinar",
    "vortrag": "lecture_webinar",
    "vorlesung": "lecture_webinar",
    "лекція": "lecture_webinar",
    "вебінар": "lecture_webinar",
    "presentation": "presentation_demo",
    "demo": "presentation_demo",
    "walkthrough": "presentation_demo",
    "produktvorstellung": "presentation_demo",
    "презентація": "presentation_demo",
    "voice memo": "voice_memo",
    "sprachnotiz": "voice_memo",
}


def tokens(text: str, language: str = "en") -> frozenset[str]:
    """The shared content tokens (``text.content_tokens``): stop words out, long words
    cut to a stem, so wording is free."""
    return frozenset(text_rules.content_tokens(text, language))


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").replace(".", "") for n in _textrules.NUMBER.findall(text)} - {""}


def _body(text: str) -> str:
    """A line without its list marker or heading hashes."""
    return text_rules.body(text)


def support(
    line: str, cited: list[str], language: str = "en", *, threshold: float | None = None
) -> bool:
    """A line is supported when half its content, every number and every name is in what it
    cites; ratio and name rule are the shared ones (``note_service.domain.text``).
    """
    evidence = " ".join(cited)
    body = _body(line)
    floor = text_rules.line_support_threshold(language) if threshold is None else threshold
    if text_rules.support_ratio(body, evidence, language) < floor:
        return False
    if not _numbers(line) <= _numbers(evidence):
        return False
    return not text_rules.new_names(body, evidence)


def invents(line: str, evidence: list[str]) -> bool:
    """A number or a name in the line that no evidence of the run has."""
    joined = " ".join(evidence)
    if not _numbers(line) <= _numbers(joined):
        return True
    return bool(text_rules.new_names(_body(line), joined))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _contains(text: str, needle: str) -> bool:
    folded = unicodedata.normalize("NFKC", text).casefold()
    want = unicodedata.normalize("NFKC", needle).casefold().strip()
    if not want:
        return False
    return re.search(rf"(?<!\w){re.escape(want)}(?!\w)", folded) is not None


# ── Per-meeting scoring ─────────────────────────────────────────────


@dataclass
class Ratio:
    """A numerator and a denominator, summed across meetings before one
    division — so a two-line meeting does not weigh as much as a
    forty-line one."""

    hit: int = 0
    total: int = 0

    def add(self, hit: bool) -> None:
        self.hit += 1 if hit else 0
        self.total += 1

    @property
    def rate(self) -> float | None:
        return (self.hit / self.total) if self.total else None

    def pair(self) -> list[int]:
        return [self.hit, self.total]


def _third_of(meeting: dict[str, Any], gold_fact: str) -> int:
    """Which third of the recording a gold fact was said in: the turn
    that shares most of its words, placed on the recording's clock."""
    turns = meeting.get("transcript") or []
    if not turns:
        return 1
    index, _ = best_match(gold_fact, [t["text"] for t in turns])
    start, end = turns[0]["t_start_ms"], turns[-1]["t_end_ms"]
    at = turns[max(index, 0)]
    middle = (at["t_start_ms"] + at["t_end_ms"]) / 2
    share = (middle - start) / max(1, end - start)
    return 1 if share < 1 / 3 else (2 if share < 2 / 3 else 3)


def _merged_span(ranges: list[tuple[int, int]]) -> int:
    """Milliseconds covered by the ranges, overlaps counted once."""
    total = 0
    current: list[int] | None = None
    for start, end in sorted(ranges):
        if current is None or start > current[1]:
            if current is not None:
                total += current[1] - current[0]
            current = [start, max(start, end)]
        else:
            current[1] = max(current[1], end)
    if current is not None:
        total += current[1] - current[0]
    return total


def _same_name(a: str, b: str) -> bool:
    """The same person or organisation: the whole name, or its last word."""
    fa, fb = " ".join(a.casefold().split()), " ".join(b.casefold().split())
    return bool(fa and fb) and (fa == fb or fa.split()[-1] == fb.split()[-1])


def recording_type_of(label: str | None) -> str | None:
    if not label:
        return None
    folded = " ".join(label.casefold().split())
    if folded in TYPE_ALIASES:
        return TYPE_ALIASES[folded]
    for alias, value in sorted(TYPE_ALIASES.items(), key=lambda p: -len(p[0])):
        if alias in folded:
            return value
    return None


def _evidence(fact: dict[str, Any]) -> str:
    """What a fact carries: its statement, its verbatim words, and what
    verification found in the turn — the owner, the deadline, and (Q4) the
    holder of the position."""
    parts = (
        fact.get("text"),
        fact.get("quote"),
        fact.get("owner"),
        fact.get("due_text"),
        fact.get("attributed_to"),
    )
    return " ".join(p for p in parts if p)


def _claim(line: dict[str, Any]) -> str:
    """What a line claims. A key-date line (Q5) opens with a date the code
    formatted from a verified mention ("23.09.2026 00:00 — …"); the claim
    is what follows it."""
    text = line["text"]
    if line.get("kind") == "date" and " — " in text:
        return text.split(" — ", 1)[1]
    return text


def score_meeting(meeting: dict[str, Any], produced: dict[str, Any]) -> dict[str, Any]:
    """Every audit metric for one meeting, as counts (``[hit, total]``)
    and a few ids. Aggregate with :func:`aggregate`."""
    gold = meeting.get("gold") or {}
    language = meeting.get("language", "en")
    lines = [ln for ln in produced.get("lines", []) if ln.get("text", "").strip()]
    content = [ln for ln in lines if ln.get("kind") not in _NOT_CONTENT]
    facts = {f["item_key"]: f for f in produced.get("facts", [])}
    # Review step 2: the holders every matcher folds out (gold names, speakers, holders found).
    holders = frozenset(
        h
        for h in (
            *gold.get("name_candidates", []),
            *(gold.get("speakers") or {}).values(),
            *(f.get("attributed_to") or "" for f in facts.values()),
            *(c.get("holder") or "" for c in gold.get("certainties") or []),
        )
        if h and h.strip()
    )
    transcript = [t["text"] for t in meeting.get("transcript", [])]
    by_transcript = produced.get("evidence") == "transcript"
    all_evidence = transcript if by_transcript else [_evidence(f) for f in facts.values()]

    def cited(line: dict[str, Any]) -> list[str]:
        if by_transcript:
            return transcript
        return [_evidence(facts[i]) for i in line.get("fact_ids", []) if i in facts]

    row: dict[str, Any] = {}

    # Unsupported lines: composed lines whose content their facts do not carry.
    unsupported = Ratio()
    for line in content:
        if line.get("kind") in COMPOSED:
            unsupported.add(not support(line["text"], cited(line), language))
    row["unsupported"] = unsupported.pair()

    # Invented claims: a number or a name no evidence of the run has.
    row["invented_claims"] = sum(1 for ln in content if invents(_claim(ln), all_evidence))

    # Key-fact recall, overall and per third of the recording.
    texts = [ln["text"] for ln in content]
    recall = Ratio()
    thirds = {1: Ratio(), 2: Ratio(), 3: Ratio()}
    missed: list[int] = []
    for i, fact in enumerate(gold.get("key_facts", [])):
        text = fact["text"] if isinstance(fact, dict) else fact
        _, best = best_match(text, texts, language, holders)
        hit = best >= MATCH_THRESHOLD
        recall.add(hit)
        # v3 names the third (from the transcript's timestamps); v2 infers it.
        third = fact.get("third") if isinstance(fact, dict) else None
        thirds[third if third in (1, 2, 3) else _third_of(meeting, text)].add(hit)
        if not hit:
            missed.append(i)
    row["key_fact_recall"] = recall.pair()
    row["recall_by_third"] = {str(k): v.pair() for k, v in thirds.items()}
    row["key_facts_missed"] = missed

    # Excluded speech: seconds set aside as noise over seconds of speech.
    speech = _merged_span([(t["t_start_ms"], t["t_end_ms"]) for t in meeting.get("transcript", [])])
    noise = _merged_span([(int(r[0]), int(r[1])) for r in produced.get("noise_ranges", [])])
    row["excluded_ms"] = [noise, speech]

    # Recording type.
    want = meeting.get("recording_type")
    if want:
        brief = produced.get("brief") or {}
        stats = produced.get("stats") or {}
        got = stats.get("recording_type") or recording_type_of(brief.get("conversation_type"))
        row["recording_type"] = [1 if got == want else 0, 1]

    # Redundancy: lines that say what another line says.
    # A key-date line (Q5) is an index entry: it repeats its fact on purpose.
    indexed = [ln for ln in content if ln.get("kind") != "date"]
    toks = [tokens(_body(ln["text"]), language) for ln in indexed]
    repeated = set()
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            if _jaccard(toks[i], toks[j]) >= REDUNDANT_JACCARD:
                repeated.update((i, j))
    row["redundancy"] = [len(repeated), len(indexed)]

    # Entities: the canonical name written, and no ASR-only spelling of it.
    known_names = {*gold.get("name_candidates", []), *(gold.get("speakers") or {}).values()}
    everything = "\n".join([*texts, produced.get("title") or ""])
    entities, knowable = Ratio(), Ratio()
    # Which tier got a name right, and how often the model tier was right.
    corrections = [c for f in facts.values() for c in f.get("corrections") or []]
    by_source: dict[str, int] = {}
    for entity in gold.get("entities", []):
        canonical = entity["canonical"]
        last = canonical.split()[-1]
        named = _contains(everything, canonical) or _contains(everything, last)
        wrong = [
            s
            for s in entity.get("surface_forms", [])
            if not _contains(canonical, s) and _contains(everything, s)
        ]
        ok = named and not wrong
        entities.add(ok)
        if canonical in known_names:
            knowable.add(ok)
        if ok:
            source = next((c[2] for c in corrections if _same_name(c[1], canonical)), "as_heard")
            by_source[source] = by_source.get(source, 0) + 1
    row["entity_accuracy"] = entities.pair()
    row["entity_accuracy_knowable"] = knowable.pair()
    row["entity_sources"] = by_source
    if gold.get("entities"):
        model = [c for c in corrections if c[2] == "model"]
        right = sum(
            1 for c in model if any(_same_name(c[1], e["canonical"]) for e in gold["entities"])
        )
        row["model_tier_precision"] = [right, len(model)]

    # Hedges: a hedged gold statement is still hedged where it is written.
    markers = _textrules.MODALITY_MARKERS.get(language, _textrules.MODALITY_MARKERS["en"])
    hedges = Ratio()
    for hedged in gold.get("hedged", []):
        index, best = best_match(hedged["fact"], texts, language, holders)
        if best < MATCH_THRESHOLD:
            continue
        line = content[index]
        flagged = any(
            (facts.get(i) or {}).get("certainty") not in (None, "fact")
            for i in line.get("fact_ids", [])
        )
        hedges.add(flagged or any(_contains(line["text"], m) for m in markers))
    row["hedge_preservation"] = hedges.pair()

    # Attribution: an opinion or a forecast says whose it is.
    holders = {
        tok
        for name in [
            *known_names,
            *(e["canonical"] for e in gold.get("entities", [])),
            *(f.get("attributed_to") or "" for f in facts.values()),
        ]
        for tok in name.split()
        if tok[:1].isupper()
    }
    attributed = Ratio()
    for line in content:
        if line.get("kind") == "framing":
            continue  # the framing describes the recording, it holds no position
        certainties = {(facts.get(i) or {}).get("certainty") for i in line.get("fact_ids", [])}
        if certainties & _UNSURE:
            attributed.add(any(_contains(line["text"], h) for h in holders))
    row["attribution"] = attributed.pair()

    row["date_resolution"] = date_resolution(gold, produced)

    # Every written line can open its evidence; the key-dates block carries
    # the dates the recording set.
    row["lines_cited"] = [sum(1 for ln in content if ln.get("fact_ids")), len(content)]
    # A1: certainty and holder at extraction, against the gold labels (matched by a phrase
    # of the quote or the text); holder presence over every claim-type fact the run kept.
    row.update(certainty_columns(gold.get("certainties") or [], list(facts.values()), language))
    # B4: what the written lines are — the speaker's words, one fact, or several.
    row["provenance"] = {
        k: sum(1 for ln in content if (ln.get("provenance") or "none") == k)
        for k in ("verbatim", "paraphrase", "composed", "none")
    }
    # B4: the relayed claims the gold names, found as rows of the claims table.
    claim_rows = [ln for ln in lines if ln.get("kind") == "claim"]
    wanted_claims = gold.get("claims") or []
    if wanted_claims:
        hits = 0
        found_each: list[bool] = []
        for want in wanted_claims:
            texts = want.get("claim") or []
            who = want.get("who")
            verdicts = want.get("verdict") or []
            for ln in claim_rows:
                if (
                    any(_normalize.contains(ln["text"], t, language) for t in texts)
                    and (not who or _normalize.contains(ln["text"], who, language))
                    and (
                        not verdicts
                        or any(_normalize.contains(ln["text"], v, language) for v in verdicts)
                    )
                ):
                    hits += 1
                    found_each.append(True)
                    break
            else:
                found_each.append(False)
        row["claims_recall"] = [hits, len(wanted_claims)]
        # Review step 2: per gold claim, for the agreement check with notes_assert.
        row["claims_found"] = found_each
    wanted = [d for d in gold.get("dates", []) if d.get("tense") != "past"]
    if wanted and any("kind" in ln for ln in lines):
        in_block = {v for ln in lines if ln.get("kind") == "date" for v in ln.get("dates") or []}
        row["key_dates_recall"] = [sum(1 for d in wanted if d["resolved"] in in_block), len(wanted)]

    # Statements, not quotes: copied, empty or first-person lines.
    sentences = transcript_sentences(meeting)
    row["copied_lines"] = sum(1 for ln in content if copies_transcript(ln["text"], sentences))
    row["no_information_lines"] = sum(
        1 for ln in content if not informs(ln["text"], ln.get("kind"), language)
    )
    row["first_person_lines"] = sum(
        1
        for ln in content
        if ln.get("kind") not in _TASK_LINE_KINDS and _textrules.first_person(_body(ln["text"]))
    )

    # Error taxonomy detectors (docs/eval/error-taxonomy.md).
    names = {*known_names, *(e["canonical"] for e in gold.get("entities", []))}
    row.update(score_taxonomy(meeting, produced, content, names))

    # Checklists, by index.
    row["must_contain_failed"] = [
        i for i, s in enumerate(gold.get("must_contain", [])) if not _contains(everything, s)
    ]
    row["must_not_contain_failed"] = [
        i for i, s in enumerate(gold.get("must_not_contain", [])) if _contains(everything, s)
    ]
    row.update(score_sq1(meeting, produced))
    row.update(score_sq2(meeting, produced))
    row.update(score_sq3(produced, row))
    return row


# ── Reads like a note ───────────────────────────────────

# The web client's speaker rule (web/src/lib/richText.ts), verbatim.
SPEAKER_TURN = re.compile(r"^(?!https?:)([^\s*_`:][^*_`:]{0,39}?):\s+(?=\S)")
REDUNDANCY_BAR = 0.05


def score_sq3(produced: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """``speaker_shaped_lines`` (D-FORM), ``order_inversions``, ``redundancy_ok`` (< 5 % repeats)."""
    facts = {f["item_key"]: f for f in produced.get("facts", [])}
    shaped = 0
    inversions = 0
    last: dict[str, int] = {}
    for ln in produced.get("lines", []):
        text = ln.get("text", "")
        kind = ln.get("kind")
        if kind not in ("bullet", "heading") and not text.lstrip().startswith(("-", "|", "#")):
            shaped += 1 if SPEAKER_TURN.match(text.lstrip()) else 0
        if kind == "bullet" and not ln.get("parent"):
            starts = [facts[i]["start_ms"] for i in ln.get("fact_ids", []) if i in facts]
            if starts:
                key = ln.get("section_key") or ""
                if key in last and min(starts) < last[key]:
                    inversions += 1
                last[key] = min(starts)
    dup, total = row.get("redundancy") or [0, 0]
    return {
        "speaker_shaped_lines": shaped,
        "order_inversions": inversions,
        "redundancy_ok": int(not total or dup / total < REDUNDANCY_BAR),
    }


def sq3_gates(summary: dict[str, Any]) -> dict[str, bool]:
    """Sprint SQ3 acceptance by code (the raters' rubric is separate)."""
    out: dict[str, bool] = {}
    checks = (
        ("sq3_d_form_zero", "speaker_shaped_lines", lambda v: v == 0),
        ("sq3_participant_precision_95pct", "participant_precision", lambda v: v >= 0.95),
        ("sq3_participant_recall_90pct", "participant_recall", lambda v: v >= 0.90),
        ("sq3_label_lines_zero", "label_lines", lambda v: v == 0),
        ("sq3_filler_lines_zero", "filler_lines", lambda v: v == 0),
        ("sq3_redundancy_ok_95pct", "redundancy_ok_rate", lambda v: v >= 0.95),
        ("sq3_order_inversions_zero", "order_inversions", lambda v: v == 0),
        ("sq3_title_ok_100pct", "title_ok", lambda v: v >= 1.0),
    )
    for name, key, ok in checks:
        value = summary.get(key)
        if value is not None:
            out[name] = bool(ok(value))
    return out


# ── The whole recording is in the note ──────────────────

NEAR_EMPTY_LINES = 3  # fewer cited content lines than this is near-empty
NEAR_EMPTY_FROM_MS = 2 * 60_000  # recordings shorter than this are not judged
MIN_SECTION_BULLETS = 2


def score_sq2(meeting: dict[str, Any], produced: dict[str, Any]) -> dict[str, Any]:
    """``one_bullet_sections`` — headed topic sections with fewer than two
    points; ``near_empty`` — a recording of two minutes or more whose note
    has fewer than three cited lines (1/0, None below two minutes)."""
    roles_by_key = {s.get("section_key"): s.get("role") for s in produced.get("sections") or []}
    points: dict[str, int] = {}
    for line in produced.get("lines", []):
        key = line.get("section_key")
        if roles_by_key.get(key) != "topics":
            continue
        points.setdefault(key, 0)
        if line.get("kind") == "bullet" and not line.get("parent"):
            points[key] += 1
    cited_lines = sum(
        1
        for ln in produced.get("lines", [])
        if ln.get("fact_ids") and ln.get("kind") not in _NOT_CONTENT
    )
    turns = meeting.get("transcript") or []
    span = (turns[-1]["t_end_ms"] - turns[0]["t_start_ms"]) if turns else 0
    return {
        "one_bullet_sections": sum(1 for n in points.values() if n < MIN_SECTION_BULLETS),
        "near_empty": (int(cited_lines < NEAR_EMPTY_LINES) if span >= NEAR_EMPTY_FROM_MS else None),
    }


# ── Statements, not quotes ──────────────────────────────────────

# Lines that are a task or an outcome: short by nature, phrased as said.
_TASK_LINE_KINDS = frozenset({"action", "commitment_ours", "commitment_theirs", "decision"})
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


# ── The criteria the summary track gates on ──────────────

GENERIC_TITLE_WORDS = frozenset(
    {
        "meeting", "call", "sync", "notes", "podcast", "episode", "folge", "podcast-folge",
        "besprechung", "meeting-notizen", "gespräch", "interview", "update",
        "зустріч", "нарада", "розмова", "подкаст", "the", "a", "der", "die", "das", "weekly",
        "wöchentlich", "team", "call:", "follow-up",
    }
)  # fmt: skip
TITLE_MIN, TITLE_MAX = 30, 80
PARTICIPANT_MIN_SHARE = 0.05


def _surname(name: str) -> str:
    parts = [p for p in name.split() if p[:1].isupper()]
    return (parts[-1] if parts else name).casefold()


def _orientation(produced: dict[str, Any]) -> str:
    """What says who speaks: the orientation and roles sections, else the
    first section (an older document has no roles)."""
    sections = produced.get("sections") or []
    picked = [s.get("text") or "" for s in sections if s.get("role") in ("orientation", "roles")]
    if not picked and sections:
        picked = [sections[0].get("text") or ""]
    return "\n".join(picked)


def _participants(gold: dict[str, Any], produced: dict[str, Any]) -> dict[str, list[int]]:
    """Gold participants (>= 5 % of speech or a non-plain role) named in the orientation
    (recall), and orientation names that are not participants (precision).
    """
    wanted = [
        p for p in gold.get("participants") or []
        if p.get("name") and (p.get("speech_share", 0) >= PARTICIPANT_MIN_SHARE or p.get("role") != "participant")
    ]  # fmt: skip
    if not wanted:
        return {}
    text = _orientation(produced).casefold()
    named = {_surname(p["name"]) for p in wanted}
    people = named | {
        _surname(n) for n in gold.get("name_candidates") or []
    } | {
        _surname(e["canonical"]) for e in gold.get("entities") or [] if e.get("kind", "person") == "person"
    }  # fmt: skip
    mentioned = {n for n in people if n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text)}
    return {
        "participant_recall": [len(named & mentioned), len(named)],
        "participant_precision": [len(named & mentioned), len(mentioned)],
    }


def _opinion_attribution(
    gold: dict[str, Any],
    texts: list[str],
    language: str = "en",
    holders: frozenset[str] = frozenset(),
) -> list[int] | None:
    """SM-06: of the gold opinions the note carries, those whose line names
    their holder."""
    facts = {f["id"]: f for f in gold.get("key_facts") or [] if isinstance(f, dict) and "id" in f}
    ops = gold.get("opinions") or []
    if not ops or not texts:
        return None
    hit = total = 0
    for op in ops:
        fact = facts.get(op.get("fact"))
        if fact is None:
            continue
        index, best = best_match(fact["text"], texts, language, holders)
        if best < MATCH_THRESHOLD:
            continue
        total += 1
        holder = _surname(op["holder"])
        hit += 1 if re.search(rf"(?<!\w){re.escape(holder)}(?!\w)", texts[index].casefold()) else 0
    return [hit, total] if total else None


def filler_lines(lines: list[dict[str, Any]], *, cited_evidence: bool) -> int:
    """SM-09: a line that adds no fact — its content words are a subset of
    another line's, or (when lines cite facts) it cites none."""
    sets = [words(ln["text"]) for ln in lines]
    count = 0
    for i, ln in enumerate(lines):
        own = sets[i]
        if not own:
            continue
        subset = any(j != i and own <= sets[j] and own != sets[j] for j in range(len(sets)))
        uncited = cited_evidence and ln.get("kind") in COMPOSED and not ln.get("fact_ids")
        count += 1 if subset or uncited else 0
    return count


def title_checks(produced: dict[str, Any], evidence: str) -> dict[str, Any]:
    """TI-01, TI-03, TI-04 by code. TI-02 (names the whole recording) is the
    raters' question and stays None here."""
    title = (produced.get("title") or "").strip()
    if not title:
        return {}
    ok_length = TITLE_MIN <= len(title) <= TITLE_MAX and title.count(":") <= 1
    names = [w.strip(".,:;!?\"'()") for w in title.split()[1:] if w[:1].isupper()]
    folded_evidence = evidence.casefold()
    names_ok = all(n.casefold() in folded_evidence for n in names if len(n) > 2)
    content = {w.casefold().strip(".,:;!?") for w in title.split()} - GENERIC_TITLE_WORDS
    not_generic = any(len(w) > 2 for w in content)
    return {
        "title_ok": [int(ok_length and names_ok and not_generic), 1],
        "title_length_ok": ok_length,
        "title_names_supported": names_ok,
        "title_not_generic": not_generic,
    }


def _faithfulness_vs_truth(
    meeting: dict[str, Any], content: list[dict[str, Any]], asr_evidence: list[str]
) -> dict[str, int]:
    """Lines checked against the human-corrected transcript too: an ASR-only name or number
    is ``propagated_from_asr``, not the writer's invention.
    """
    truth = [t["text"] for t in meeting.get("reference_transcript") or []]
    if not truth:
        return {}
    propagated = invented = 0
    for ln in content:
        claim = _claim(ln)
        wrong_vs_truth = invents(claim, truth)
        if not wrong_vs_truth:
            continue
        if invents(claim, asr_evidence):
            invented += 1
        else:
            propagated += 1
    return {"propagated_from_asr": propagated, "invented_vs_truth": invented}


def score_sq1(meeting: dict[str, Any], produced: dict[str, Any]) -> dict[str, Any]:
    gold = meeting.get("gold") or {}
    lines = [ln for ln in produced.get("lines", []) if ln.get("text", "").strip()]
    content = [ln for ln in lines if ln.get("kind") not in _NOT_CONTENT]
    texts = [ln["text"] for ln in content]
    asr = [t["text"] for t in meeting.get("transcript", [])]
    row: dict[str, Any] = {}
    row.update(_participants(gold, produced))
    attribution = _opinion_attribution(gold, texts, meeting.get("language", "en"))
    if attribution is not None:
        row["opinion_attribution"] = attribution
    row["filler_lines"] = filler_lines(content, cited_evidence=produced.get("evidence") == "facts")
    row.update(
        title_checks(
            produced, "\n".join([*asr, *(_evidence(f) for f in produced.get("facts", []))])
        )
    )
    row.update(_faithfulness_vs_truth(meeting, content, asr))
    return row


def transcript_sentences(meeting: dict[str, Any]) -> list[str]:
    """Every turn, and every sentence of every turn."""
    out: list[str] = []
    for turn in meeting.get("transcript", []):
        text = turn.get("text", "")
        out.append(text)
        out.extend(part for part in _SENTENCE_END.split(text) if part.strip())
    return out


def copies_transcript(line: str, sentences: list[str]) -> bool:
    """The line is a transcript sentence, or nearly all of one (the ``is_copied``
    rule against every sentence said)."""
    body = _body(line)
    return any(_textrules.is_copied(body, sentence) for sentence in sentences)


def informs(line: str, kind: str | None, language: str = "en") -> bool:
    """The ``no_information`` rule (``carries_information``)."""
    body = _body(line)
    return _textrules.carries_information(
        body,
        language,
        short_ok=kind in _TASK_LINE_KINDS,
        has_date=_textrules.has_date_word(body),
    )


def f2_gates(summary: dict[str, Any], *, baseline_recall: float | None) -> dict[str, bool]:
    """F2 acceptance on a corpus: no copied, chatter or first-person line,
    and key-fact recall no more than one point under the pre-F2 baseline."""
    gates = {
        "copied_lines == 0": summary.get("copied_lines") == 0,
        "no_information_lines == 0": summary.get("no_information_lines") == 0,
        "first_person_lines == 0": summary.get("first_person_lines") == 0,
    }
    recall = summary.get("key_fact_recall")
    if baseline_recall is not None and recall is not None:
        gates["key_fact_recall >= baseline - 0.01"] = recall >= baseline_recall - 0.01
    return gates


def date_resolution(gold: dict[str, Any], produced: dict[str, Any]) -> list[int] | None:
    """``[resolved right, gold dates]`` — or None while the engine exposes
    no resolved dates (Q3 wires ``produced["dates"]``: ``[{text, resolved}]``)."""
    exposed = produced.get("dates")
    wanted = gold.get("dates") or []
    if exposed is None or not wanted:
        return None

    def found(want: dict[str, Any]) -> bool:
        # Either side may carry the preposition ("am montag"); same words, same resolution.
        text = " ".join(want["text"].casefold().split())
        for d in exposed:
            said = " ".join((d.get("text") or "").casefold().split())
            if said and (text in said or said in text) and d.get("resolved") == want["resolved"]:
                return True
        return False

    return [sum(1 for d in wanted if found(d)), len(wanted)]


# ── Aggregation ─────────────────────────────────────────────────────

# ── Error taxonomy detectors (docs/eval/error-taxonomy.md) ──────────

# D-LABEL: a diarizer label or default name as an actor (narrator counts
# outside the framing line, which lists speakers).
_DEFAULT_LABEL = re.compile(
    r"\bSPEAKER_\d+\b|\b(?:[Ss]peaker|[Ss]precher(?:in)?)\s\d+\b|\b[Uu]nknown speaker\b|\bUNKNOWN\b"
)
_NARRATOR_LABEL = re.compile(r"Erzähler/in|\bthe narrator\b|\bоповідач\b", re.IGNORECASE)
# F-SUBJ: a line whose subject is a bare pronoun.
_PRONOUNS: dict[str, frozenset[str]] = {
    "en": frozenset({"he", "she", "they", "him", "her", "his", "their", "them"}),
    "de": frozenset({"er", "sie", "ihm", "ihn", "ihr", "sein", "seine", "ihre"}),
    "uk": frozenset({"він", "вона", "вони", "його", "її", "їх", "йому", "їй"}),
}
# "Zunächst — …": a connective before the sentence proper.
_LEAD = re.compile(r"^[^—]{1,20}—\s+")
_PROSE_KINDS = frozenset({"summary", "bullet", "key_point"})


def score_taxonomy(
    meeting: dict[str, Any],
    produced: dict[str, Any],
    content: list[dict[str, Any]],
    known_names: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """``label_lines`` (D-LABEL), ``unresolved_subject`` (F-SUBJ), ``unspecific_bullets``
    (D-SPEC), ``volume`` (D-VOL) and ``headings`` (D-STRUCT).
    """
    language = meeting.get("language", "en")
    pronouns = _PRONOUNS.get(language, _PRONOUNS["en"])
    known = frozenset(n for name in known_names for n in [name, *name.split()] if n)
    out: dict[str, Any] = {}
    out["label_lines"] = sum(
        1
        for ln in content
        if _DEFAULT_LABEL.search(ln["text"])
        or (ln.get("kind") != "framing" and _NARRATOR_LABEL.search(ln["text"]))
    )
    prose = [ln for ln in content if ln.get("kind") in _PROSE_KINDS]
    unresolved = 0
    for ln in prose:
        words = _LEAD.sub("", _body(ln["text"]).strip()).split()
        if words and words[0].strip(",.;:").casefold() in pronouns:
            unresolved += 1
    out["unresolved_subject"] = [unresolved, len(prose)]
    bullets = [ln for ln in content if ln.get("kind") == "bullet"]
    vague = sum(
        1
        for ln in bullets
        # A label is not a name, and its digit is not a number.
        if _textrules.specificity(
            _DEFAULT_LABEL.sub("", ln["text"]),
            language,
            known=known,
            has_date=_textrules.has_date_word(ln["text"]),
        )
        == 0
    )
    out["unspecific_bullets"] = [vague, len(bullets)]
    turns = meeting.get("transcript", [])
    seconds = (turns[-1]["t_end_ms"] - turns[0]["t_start_ms"]) // 1000 if turns else 0
    words = sum(len(_body(ln["text"]).split()) for ln in content)
    out["volume"] = [words, seconds]
    if "sections" in produced:
        headed = sum(
            1
            for sec in produced["sections"]
            if sec.get("role") == "topics" and (sec.get("title") or "").strip()
        )
        out["headings"] = [headed, seconds]
    return out


_PAIRS = (
    "unresolved_subject",
    "unspecific_bullets",
    "volume",
    "headings",
    "lines_cited",
    "claims_recall",
    "certainty_accuracy",
    "certainty_labels_found",
    "holder_accuracy",
    "holder_presence",
    "key_dates_recall",
    "model_tier_precision",
    "unsupported",
    "key_fact_recall",
    "recording_type",
    "redundancy",
    "entity_accuracy",
    "entity_accuracy_knowable",
    "hedge_preservation",
    "attribution",
    "date_resolution",
    # Summary criteria
    "participant_recall",
    "participant_precision",
    "opinion_attribution",
    "title_ok",
)


def _rate(pair: list[int] | None) -> float | None:
    return (pair[0] / pair[1]) if pair and pair[1] else None


# A1: a gold label accepts the engine's finer value for the same thing (B2's relayed-claim
# verdicts are allegations with a verdict; a plain fact may carry no certainty at all).
_CERTAINTY_EQUIVALENT: dict[str, frozenset[str]] = {
    "allegation": frozenset({"allegation", "reported", "unproven", "refuted"}),
    "fact": frozenset({"fact", "none"}),
}
_CLAIM_TYPES = frozenset(
    {
        "statement",
        "allegation",
        "opinion",
        "prediction",
        "estimate",
        "proposal",
        "reported",
        "unproven",
        "refuted",
    }
)


def certainty_columns(
    labels: list[dict[str, Any]], facts: list[dict[str, Any]], language: str = "en"
) -> dict[str, Any]:
    """``certainty_accuracy`` [right, labelled and found], ``holder_accuracy`` [right, labelled
    with a holder and found with one], ``holder_presence`` [with a holder, claim-type facts]."""
    out: dict[str, Any] = {}
    claim_facts = [f for f in facts if (f.get("certainty") or "") in _CLAIM_TYPES]
    out["holder_presence"] = [
        sum(1 for f in claim_facts if (f.get("attributed_to") or "").strip()),
        len(claim_facts),
    ]
    out["holders_from_turn"] = sum(
        1 for f in claim_facts if "holder_from_turn" in (f.get("flags") or [])
    )
    out["holders_unknown"] = sum(
        1 for f in claim_facts if "holder_unknown" in (f.get("flags") or [])
    )
    if not labels:
        return out
    right = found = holder_right = holder_judged = 0
    # Diagnosis (A1 review): every (gold, predicted) pair, for the confusion matrix.
    pairs: list[list[str]] = []
    for label in labels:
        hit = next(
            (
                f
                for f in facts
                if _normalize.contains(f.get("quote") or "", label["match"], language)
                or _normalize.contains(f.get("text") or "", label["match"], language)
            ),
            None,
        )
        if hit is None:
            continue
        found += 1
        got = hit.get("certainty") or "none"
        pairs.append([label["certainty"], got])
        accepted = _CERTAINTY_EQUIVALENT.get(label["certainty"], frozenset({label["certainty"]}))
        right += got in accepted
        want = (label.get("holder") or "").strip()
        have = (hit.get("attributed_to") or "").strip()
        if want and have:
            holder_judged += 1
            holder_right += want.split()[-1].casefold() == have.split()[-1].casefold()
    out["certainty_accuracy"] = [right, found]
    out["certainty_labels_found"] = [found, len(labels)]
    out["holder_accuracy"] = [holder_right, holder_judged]
    out["certainty_pairs"] = pairs
    return out


def _provenance_share(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    totals = dict.fromkeys(("verbatim", "paraphrase", "composed", "none"), 0)
    for row in rows:
        for k, v in (row.get("provenance") or {}).items():
            totals[k] = totals.get(k, 0) + int(v)
    n = sum(totals.values())
    return {k: round(v / n, 3) for k, v in totals.items()} if n else None


def aggregate(
    rows: list[dict[str, Any]], *, types: list[str | None] | None = None
) -> dict[str, Any]:
    """Corpus metrics from per-meeting rows: numerators and denominators
    summed first, then divided."""
    sums: dict[str, list[int]] = {k: [0, 0] for k in _PAIRS}
    thirds = {k: [0, 0] for k in ("1", "2", "3")}
    excluded = [0, 0]
    invented = labels = 0
    f2 = {"copied_lines": 0, "no_information_lines": 0, "first_person_lines": 0}
    sq1 = {"filler_lines": 0, "propagated_from_asr": 0, "invented_vs_truth": 0}
    truth_docs = 0
    one_bullet = 0
    near_empty = [0, 0]
    shaped = inversions = 0
    redundancy_ok = [0, 0]
    by_type: dict[str, list[int]] = {}
    for n, row in enumerate(rows):
        for key in _PAIRS:
            pair = row.get(key)
            if pair:
                sums[key][0] += pair[0]
                sums[key][1] += pair[1]
        for key, pair in (row.get("recall_by_third") or {}).items():
            thirds[key][0] += pair[0]
            thirds[key][1] += pair[1]
        if row.get("excluded_ms"):
            excluded[0] += row["excluded_ms"][0]
            excluded[1] += row["excluded_ms"][1]
        invented += int(row.get("invented_claims") or 0)
        labels += int(row.get("label_lines") or 0)
        for key in f2:
            f2[key] += int(row.get(key) or 0)
        for key in sq1:
            sq1[key] += int(row.get(key) or 0)
        truth_docs += 1 if "propagated_from_asr" in row else 0
        one_bullet += int(row.get("one_bullet_sections") or 0)
        shaped += int(row.get("speaker_shaped_lines") or 0)
        inversions += int(row.get("order_inversions") or 0)
        if "redundancy_ok" in row:
            redundancy_ok[0] += int(row["redundancy_ok"])
            redundancy_ok[1] += 1
        if row.get("near_empty") is not None:
            near_empty[0] += int(row["near_empty"])
            near_empty[1] += 1
        kind = (types or [None] * len(rows))[n] or "unlabelled"
        bucket = by_type.setdefault(kind, [0, 0])
        pair = row.get("key_fact_recall") or [0, 0]
        bucket[0] += pair[0]
        bucket[1] += pair[1]
    per_third = {k: _rate(v) for k, v in thirds.items()}
    present = [v for v in per_third.values() if v is not None]
    return {
        "unsupported_rate": _rate(sums["unsupported"]),
        "invented_claims": invented,
        "key_fact_recall": _rate(sums["key_fact_recall"]),
        "coverage_ratio": (min(present) / max(present)) if present and max(present) > 0 else None,
        "recall_by_third": per_third,
        "recall_by_type": {k: _rate(v) for k, v in sorted(by_type.items())},
        "excluded_speech": _rate(excluded),
        "recording_type_acc": _rate(sums["recording_type"]),
        "redundancy": _rate(sums["redundancy"]),
        "entity_accuracy": _rate(sums["entity_accuracy"]),
        "entity_accuracy_knowable": _rate(sums["entity_accuracy_knowable"]),
        "hedge_preservation": _rate(sums["hedge_preservation"]),
        "attribution_rate": _rate(sums["attribution"]),
        "model_tier_precision": _rate(sums["model_tier_precision"]),
        "lines_cited": _rate(sums["lines_cited"]),
        "claims_recall": _rate(sums["claims_recall"]),
        # A1
        "certainty_accuracy": _rate(sums["certainty_accuracy"]),
        "certainty_labels_found": _rate(sums["certainty_labels_found"]),
        "holder_accuracy": _rate(sums["holder_accuracy"]),
        "holder_presence": _rate(sums["holder_presence"]),
        "holders_from_turn": int(sum(r.get("holders_from_turn") or 0 for r in rows)),
        "holders_unknown": int(sum(r.get("holders_unknown") or 0 for r in rows)),
        # B4: the share of written lines that are verbatim, one fact or several.
        "provenance_share": _provenance_share(rows),
        "key_dates_recall": _rate(sums["key_dates_recall"]),
        "entity_sources": _sum_sources(rows),
        "date_resolution": _rate(sums["date_resolution"]),
        **f2,
        # Error taxonomy detectors.
        "label_lines": labels,
        "unresolved_subject_rate": _rate(sums["unresolved_subject"]),
        "unspecific_bullet_rate": _rate(sums["unspecific_bullets"]),
        "words_per_minute": (
            sums["volume"][0] * 60 / sums["volume"][1] if sums["volume"][1] else None
        ),
        "headings_per_10_min": (
            sums["headings"][0] * 600 / sums["headings"][1] if sums["headings"][1] else None
        ),
        # Summary criteria.
        "participant_precision": _rate(sums["participant_precision"]),
        "participant_recall": _rate(sums["participant_recall"]),
        "opinion_attribution": _rate(sums["opinion_attribution"]),
        "filler_lines": sq1["filler_lines"],
        "title_ok": _rate(sums["title_ok"]),
        "by_third_ratio": (min(present) / max(present)) if present and max(present) > 0 else None,
        # Coverage (``sections_count_ok`` was the old linter's band; P3 decides its successor).
        "sections_count_ok": None,
        "near_empty_rate": _rate(near_empty),
        "one_bullet_sections": one_bullet,
        # Form.
        "speaker_shaped_lines": shaped,
        "order_inversions": inversions,
        "redundancy_ok_rate": _rate(redundancy_ok),
        # Per document, and only over documents scored against the truth.
        "propagated_from_asr": (sq1["propagated_from_asr"] / truth_docs) if truth_docs else None,
        "invented_vs_truth": (sq1["invented_vs_truth"] / truth_docs) if truth_docs else None,
    }


def _sum_sources(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        for source, n in (row.get("entity_sources") or {}).items():
            out[source] = out.get(source, 0) + int(n)
    return dict(sorted(out.items()))
