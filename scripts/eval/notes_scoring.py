"""Scorers for every metric in the Summary Engine v2 audit (Q1 T5).

Pure functions: a gold meeting and what an arm produced in, numbers out.
The harness (``notes_eval.py``) and the regression checklists
(``notes_assert.py``) call them; ``tests/unit/test_notes_scoring.py``
pins each rule on a hand-built case.

What an arm produces, as this module reads it::

    produced = {
        "lines": [{"section_key", "kind", "text", "fact_ids"}],
        "facts": [{"item_key", "kind", "text", "quote", "certainty",
                   "start_ms", "end_ms", "window_index"}],
        "stats": {...}, "brief": {...},
        "noise_ranges": [[start_ms, end_ms, reason]],
        "title": str | None,
        "evidence": "facts" | "transcript",
    }

``evidence`` is what a line's support is checked against. The pipeline
cites facts, so its lines are checked against the facts they cite. The
single-pass baseline cites nothing by construction; its lines are checked
against the whole transcript — the most generous reading, which keeps
the comparison honest rather than scoring the baseline zero for a column
it cannot have.

Reports carry numbers and ids only. No scorer returns a line, a gold
string or a transcript word: a failed ``must_*`` check is reported as
the INDEX of the string.
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

from note_service.domain.meeting_doc import prompts, verify  # noqa: E402
from note_service.domain.meeting_doc import support as support_rules  # noqa: E402

# ── Matching gold text to lines (unchanged from the Sprint 33 harness) ──

# A produced line matches a gold fact when they share this much of the
# gold fact's content words. Deliberately lenient on wording and strict on
# content: "Priya sends the release note to support by Thursday" and
# "Release note to support — Priya, Thursday" are the same fact.
MATCH_THRESHOLD = 0.6

_WORD = re.compile(r"[\w']+", re.UNICODE)
# Words that carry no content in any of the three languages we ship.
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


def overlap(gold: str, produced: str) -> float:
    g = words(gold)
    return len(g & words(produced)) / len(g) if g else 0.0


def best_match(gold: str, lines: list[str]) -> tuple[int, float]:
    scored = [(i, overlap(gold, line)) for i, line in enumerate(lines)]
    return max(scored, key=lambda p: p[1], default=(-1, 0.0))


# ── Support: does what a line says rest on what it cites? ───────────

# The engine's own per-language threshold (F3 amendment §2.10).
SUPPORT_THRESHOLD = support_rules.LINE_SUPPORT_DEFAULT
REDUNDANT_JACCARD = 0.6
# Lines the metrics look at. A heading is structure; the transcript note
# is ours, rendered from a closed vocabulary.
_NOT_CONTENT = frozenset({"heading", "note"})
# Lines written ABOUT facts rather than FROM one fact: the lines a model
# composes, and so the ones that can say more than their facts do.
COMPOSED = frozenset({"framing", "summary", "bullet"})
_UNSURE = frozenset({"opinion", "prediction", "proposal", "allegation", "estimate"})

# The hedge markers are the engine's (``support.MODALITY_MARKERS``, Q4).

# What the context pass may call a recording, mapped onto the gold enum.
# Q3 replaces the source with `stats.recording_type`; the map stays for
# the single-pass arm and older reports.
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
    """The engine's content tokens (``support.content_tokens``): stop words
    out, long words cut to a stem, so wording is free."""
    return frozenset(support_rules.content_tokens(text, language))


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").replace(".", "") for n in verify._NUMBER.findall(text)} - {""}


def _body(text: str) -> str:
    """A line without its list marker or heading hashes."""
    return support_rules._body(text)


def support(
    line: str, cited: list[str], language: str = "en", *, threshold: float | None = None
) -> bool:
    """A line is supported when at least half its content is in the text and
    quotes of what it cites, every number in it is too, and it names nobody
    they do not. The ratio and the name rule are the engine's own
    (``meeting_doc.support``), so the eval and the gate cannot disagree."""
    evidence = " ".join(cited)
    body = _body(line)
    floor = support_rules.line_support_threshold(language) if threshold is None else threshold
    if support_rules.support_ratio(body, evidence, language) < floor:
        return False
    if not _numbers(line) <= _numbers(evidence):
        return False
    return not support_rules.new_names(body, evidence)


def invents(line: str, evidence: list[str]) -> bool:
    """A number or a name in the line that no evidence of the run has."""
    joined = " ".join(evidence)
    if not _numbers(line) <= _numbers(joined):
        return True
    return bool(support_rules.new_names(_body(line), joined))


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

    # Example echo: a line that repeats a prompt example.
    row["example_echo"] = sum(1 for ln in lines if prompts.echoes_example(ln["text"]))

    # Key-fact recall, overall and per third of the recording.
    texts = [ln["text"] for ln in content]
    recall = Ratio()
    thirds = {1: Ratio(), 2: Ratio(), 3: Ratio()}
    missed: list[int] = []
    for i, fact in enumerate(gold.get("key_facts", [])):
        text = fact["text"] if isinstance(fact, dict) else fact
        _, best = best_match(text, texts)
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
    # Q4: which tier got a name right, and how often the model tier was right.
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
    markers = support_rules.MODALITY_MARKERS.get(language, support_rules.MODALITY_MARKERS["en"])
    hedges = Ratio()
    for hedged in gold.get("hedged", []):
        index, best = best_match(hedged["fact"], texts)
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

    # Q5: every written line can open its evidence, and the key-dates block
    # carries the dates the recording set.
    row["lines_cited"] = [sum(1 for ln in content if ln.get("fact_ids")), len(content)]
    wanted = [d for d in gold.get("dates", []) if d.get("tense") != "past"]
    if wanted and any("kind" in ln for ln in lines):
        in_block = {v for ln in lines if ln.get("kind") == "date" for v in ln.get("dates") or []}
        row["key_dates_recall"] = [sum(1 for d in wanted if d["resolved"] in in_block), len(wanted)]

    # F2: statements, not quotes. A line that is (nearly) a transcript
    # sentence, a line that informs nobody, a line in the speaker's voice.
    sentences = transcript_sentences(meeting)
    row["copied_lines"] = sum(1 for ln in content if copies_transcript(ln["text"], sentences))
    row["no_information_lines"] = sum(
        1 for ln in content if not informs(ln["text"], ln.get("kind"), language)
    )
    row["first_person_lines"] = sum(
        1
        for ln in content
        if ln.get("kind") not in _TASK_LINE_KINDS and support_rules.first_person(_body(ln["text"]))
    )

    # F3: figures, presenter, contact.
    row.update(score_f3(gold, produced, lines))

    # Error taxonomy detectors (docs/eval/error-taxonomy.md).
    names = {*known_names, *(e["canonical"] for e in gold.get("entities", []))}
    row.update(score_taxonomy(meeting, produced, content, names))
    # Sprint D2: composition to the standard.
    row.update(score_d2(meeting, produced))
    linted = lint_produced(meeting, produced)
    if linted is not None:
        row["lint"] = linted
        # The document standard §8: Q3 and Q7, the questions code can answer.
        auto = rubric_auto(meeting, produced)
        row["rubric_auto"] = {k: auto[k] for k in ("Q3", "Q7")} if auto else {}

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


# ── Sprint SQ3: reads like a note ───────────────────────────────────

# The web client's speaker rule (web/src/lib/richText.ts), verbatim.
SPEAKER_TURN = re.compile(r"^(?!https?:)([^\s*_`:][^*_`:]{0,39}?):\s+(?=\S)")
REDUNDANCY_BAR = 0.05


def score_sq3(produced: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """``speaker_shaped_lines`` — paragraph lines a client would draw as a
    transcript turn (D-FORM); ``order_inversions`` — bullets in a section
    whose first cited fact was said before the previous bullet's;
    ``redundancy_ok`` — this note repeats itself on fewer than 5 % of lines."""
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


# ── Sprint SQ2: the whole recording is in the note ──────────────────

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


def sq2_gates(
    summary: dict[str, Any],
    *,
    baseline_unsupported: float | None = None,
    staging: bool = False,
) -> dict[str, bool]:
    """Sprint SQ2 acceptance on a corpus (01-quality-criteria §3 numbers):
    recall ≥ 0.70, worst ÷ best third ≥ 0.80, sections within the band on
    ≥ 90 %, near-empty notes ≤ 10 %, no section with fewer than two points,
    unsupported no higher than the SQ1 baseline of the same arm; time
    (≤ 300 s per meeting-hour at p95) only on staging."""
    out: dict[str, bool] = {}
    checks = (
        ("sq2_key_fact_recall_70pct", "key_fact_recall", lambda v: v >= 0.70),
        ("sq2_by_third_ratio_80pct", "by_third_ratio", lambda v: v >= 0.80),
        ("sq2_sections_count_ok_90pct", "sections_count_ok", lambda v: v >= 0.90),
        ("sq2_near_empty_10pct", "near_empty_rate", lambda v: v <= 0.10),
        ("sq2_no_one_bullet_section", "one_bullet_sections", lambda v: v == 0),
    )
    for name, key, ok in checks:
        value = summary.get(key)
        if value is not None:
            out[name] = bool(ok(value))
    unsupported = summary.get("unsupported_rate")
    if baseline_unsupported is not None and unsupported is not None:
        out["sq2_unsupported_not_above_sq1"] = unsupported <= baseline_unsupported + 1e-9
    p95 = summary.get("seconds_per_meeting_hour_p95")
    if staging and p95 is not None:
        out["sq2_p95_seconds_per_meeting_hour_300"] = p95 <= 300
    return out


# ── F2: statements, not quotes ──────────────────────────────────────

# Lines that are a task or an outcome: short by nature, phrased as said.
_TASK_LINE_KINDS = frozenset({"action", "commitment_ours", "commitment_theirs", "decision"})
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


# ── Sprint SQ1: the criteria the summary track gates on ──────────────

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
    """SM-05: gold participants with ≥ 5 % of the speech or a role other
    than plain participant, named in the orientation (recall); people the
    orientation names who are not participants (precision). The universe of
    people is the gold's — participants, candidates and person entities —
    so a word that is not a name is never counted against precision."""
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


def _opinion_attribution(gold: dict[str, Any], texts: list[str]) -> list[int] | None:
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
        index, best = best_match(fact["text"], texts)
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
    """SM-02b: lines checked against the human-corrected transcript too. A
    name or number the ASR text has but the truth has not is the
    transcript's error carried into the note (``propagated_from_asr``), not
    the writer's invention."""
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
    attribution = _opinion_attribution(gold, texts)
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
    """The line is a transcript sentence, or nearly all of one — the
    engine's own ``is_copied`` rule against every sentence said."""
    body = _body(line)
    return any(verify.is_copied(body, sentence) for sentence in sentences)


def informs(line: str, kind: str | None, language: str = "en") -> bool:
    """The engine's ``no_information`` rule (``support.carries_information``)."""
    body = _body(line)
    return support_rules.carries_information(
        body,
        language,
        short_ok=kind in _TASK_LINE_KINDS,
        has_date=verify._has_date_word(body),
    )


# ── F3: figures, presenter, contact ─────────────────────────────────


def _value(text: str, language: str = "en") -> Any:
    from note_service.domain.meeting_doc import numbers

    return numbers.parse_value(text or "", language)


def _name_match(gold: str, produced: str) -> bool:
    """Same quantity: most of the gold name's content words."""
    return overlap(gold, produced) >= 0.5


def score_f3(gold: dict[str, Any], produced: dict[str, Any], lines: list[dict[str, Any]]) -> dict:
    """``figure_recall`` (gold figures found with their value),
    ``figure_value_accuracy`` (of produced figures naming a gold quantity,
    the value right), ``qualifier_preservation``, ``presenter_accuracy``,
    ``contact_present`` — pairs ``[hit, total]``; absent when the gold has
    nothing to score."""
    out: dict[str, Any] = {}
    made = [f["figure"] for f in produced.get("facts", []) if f.get("figure")]
    wanted = gold.get("figures") or []
    if wanted:
        recall = Ratio()
        values = Ratio()
        qualifiers = Ratio()
        for want in wanted:
            value = _value(want["value"])
            named = [m for m in made if _name_match(want["name"], m["name"])]
            right = [m for m in named if _value(m["value"]) == value]
            recall.add(bool(right))
            for m in named:
                values.add(_value(m["value"]) == value)
            if want.get("qualifier") and right:
                qualifiers.add(any(m.get("qualifier") == want["qualifier"] for m in right))
        out["figure_recall"] = recall.pair()
        out["figure_value_accuracy"] = values.pair()
        out["qualifier_preservation"] = qualifiers.pair()
    presenter = gold.get("presenter")
    if presenter:
        # SQ3 T2: the presenter is named in paragraph 1 (framing) now.
        text = "\n".join(ln["text"] for ln in lines if ln.get("kind") in ("presenter", "framing"))
        fields = [presenter["name"], presenter.get("role"), presenter.get("organisation")]
        out["presenter_accuracy"] = [
            sum(1 for f in fields if f and _contains(text, f)),
            sum(1 for f in fields if f),
        ]
    contact = gold.get("contact") or []
    if contact:
        text = "\n".join(ln["text"] for ln in lines if ln.get("kind") == "next_step")
        out["contact_present"] = (
            [sum(1 for c in contact if best_match(c, [text])[1] >= MATCH_THRESHOLD), len(contact)]
            if text
            else [0, len(contact)]
        )
    return out


def f3_gates(summary: dict[str, Any]) -> dict[str, bool]:
    """F3 acceptance where the corpus has the gold for it: every value
    right, recall ≥ 0.85, every qualifier kept, presenter ≥ 0.9."""
    gates: dict[str, bool] = {}
    for name, key, bar in (
        ("figure_value_accuracy == 1.0", "figure_value_accuracy", 1.0),
        ("figure_recall >= 0.85", "figure_recall", 0.85),
        ("qualifier_preservation == 1.0", "qualifier_preservation", 1.0),
        ("presenter_accuracy >= 0.9", "presenter_accuracy", 0.9),
    ):
        value = summary.get(key)
        if value is not None:
            gates[name] = value >= bar
    return gates


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
        # The engine's mention may carry its preposition ("am montag") or
        # not; the gold text may too. Same words, same resolution.
        text = " ".join(want["text"].casefold().split())
        for d in exposed:
            said = " ".join((d.get("text") or "").casefold().split())
            if said and (text in said or said in text) and d.get("resolved") == want["resolved"]:
                return True
        return False

    return [sum(1 for d in wanted if found(d)), len(wanted)]


# ── Aggregation ─────────────────────────────────────────────────────

# ── Error taxonomy detectors (docs/eval/error-taxonomy.md) ──────────

# D-LABEL: a diarizer label or a default name as an actor. "Erzähler/in"
# and "the narrator" count outside the framing line, which lists speakers.
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
    """``label_lines`` (D-LABEL), ``unresolved_subject`` (F-SUBJ),
    ``unspecific_bullets`` (D-SPEC), ``volume`` = [words, audio seconds]
    (D-VOL) and ``headings`` = [headed sections, audio seconds]
    (D-STRUCT)."""
    from note_service.domain.meeting_doc.verify import _has_date_word

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
        if support_rules.specificity(
            _DEFAULT_LABEL.sub("", ln["text"]),
            language,
            known=known,
            has_date=_has_date_word(ln["text"]),
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


# ── Sprint D2: composition to the standard ─────────────────────────


def score_d2(meeting: dict[str, Any], produced: dict[str, Any]) -> dict[str, Any]:
    """Per note: ``sections_in_band``, ``headings_pass``, ``bullets_specific``,
    ``children``, ``subject_failures``, ``narrator_attribution_errors``,
    ``roles_correct``, ``orientation_p1_ok``, ``lint_first_pass``,
    ``lint_after_regeneration``, ``summary_ladder``. Pairs are
    ``[hit, total]``; absent when the arm writes no sections."""
    from note_service.domain.meeting_doc import doclint
    from note_service.domain.meeting_doc import support as rules

    inputs = _lint_inputs(meeting, produced)
    if inputs is None:
        return {}
    sections, ctx = inputs
    out: dict[str, Any] = {}
    headed = [s for s in sections if s.role == "topics" and (s.title or "").strip()]
    if ctx.minutes >= doclint.SECTIONS_FROM_MINUTES:
        target = doclint.target_sections(ctx.minutes)
        low = max(doclint.SECTIONS_MIN, target - doclint.SECTIONS_TOLERANCE)
        high = min(doclint.SECTIONS_MAX, target + doclint.SECTIONS_TOLERANCE)
        out["sections_in_band"] = [1 if low <= len(headed) <= high else 0, 1]
    good = [
        s
        for s in headed
        if not doclint.heading_faults(s.title or "")
        and (s.title or "").casefold() not in doclint.GENERIC_HEADINGS
    ]
    out["headings_pass"] = [len(good), len(headed)]
    points = [
        (s, n, ln)
        for s in sections
        for n, ln in enumerate(s.lines)
        if ln.kind == "bullet" and not ln.parent
    ]
    out["bullets_specific"] = [
        sum(1 for _s, _n, ln in points if doclint.specificity(ln, ctx) > 0),
        len(points),
    ]
    with_children = sum(1 for s, n, _ln in points if n + 1 < len(s.lines) and s.lines[n + 1].parent)
    out["children"] = [with_children, len(points)]
    out["subject_failures"] = sum(
        1
        for s in sections
        for ln in s.lines
        if (fault := doclint.line_fault(ln, ctx)) and fault[0] == "line.subject"
    )
    stats = produced.get("stats") or {}
    roles = stats.get("roles") or {}
    names = (meeting.get("gold") or {}).get("speakers") or {}
    errors = 0
    for fact in produced.get("facts", []):
        holder = fact.get("attributed_to")
        label = fact.get("speaker_label")
        if not holder:
            continue
        if rules.real_name(holder) is None:
            errors += 1  # a label as a holder
        elif (
            roles.get(label) in ("narrator", "host")
            and holder == names.get(label)
            and not _FIRST_PERSON_CUE.search(fact.get("quote", ""))
        ):
            errors += 1  # the narrator holding what it reports
    out["narrator_attribution_errors"] = errors
    gold_roles = (meeting.get("gold") or {}).get("roles") or {}
    if gold_roles:
        out["roles_correct"] = [
            sum(1 for label, role in gold_roles.items() if roles.get(label) == role),
            len(gold_roles),
        ]
    top = next((s for s in sections if s.section_key == "gen:overview"), None)
    first = [ln for ln in top.lines if ln.kind in ("framing", "presenter")] if top else []
    if first:
        out["orientation_p1_ok"] = [0 if doclint.p1_faults(first, ctx) else 1, 1]
    lint = stats.get("lint") or {}
    if lint and not lint.get("error"):
        hard = {c for c, sev in doclint.SEVERITY.items() if sev in doclint.HARD}
        found = set(lint.get("findings_by_code") or {}) & hard
        left = set(lint.get("unresolved_hard") or {})
        out["lint_first_pass"] = [0 if found else 1, 1]
        out["lint_after_regeneration"] = [0 if left else 1, 1]
    if stats.get("summary_ladder"):
        out["summary_ladder"] = stats["summary_ladder"]
    return out


_FIRST_PERSON_CUE = re.compile(r"\b(?:ich|wir|I|we|я|ми)\b", re.IGNORECASE)


def d2_gates(summary: dict[str, Any]) -> dict[str, bool]:
    """Sprint D2 acceptance 2: the linter passes first time on ≥ 90 % of
    notes and after one regeneration on ≥ 98 %; roles and types right on
    ≥ 95 %; no rendered line whose subject is a pronoun or a label."""
    if summary.get("lint_first_pass") is None:
        return {}
    out = {
        "d2_lint_first_pass_90pct": summary["lint_first_pass"] >= 0.9,
        "d2_lint_after_regeneration_98pct": summary["lint_after_regeneration"] >= 0.98,
        "d2_no_subject_failures": summary["subject_failures"] == 0,
    }
    if summary.get("roles_correct") is not None:
        out["d2_roles_correct_95pct"] = summary["roles_correct"] >= 0.95
    if summary.get("recording_type_acc") is not None:
        out["d2_type_correct_95pct"] = summary["recording_type_acc"] >= 0.95
    return out


# F- codes that are S2 (docs/eval/error-taxonomy.md); the other F- codes the
# linter reports are S1.
_S2_F = frozenset({"F-COPY", "F-DESC", "F-TYPE", "F-DROP", "F-COV"})


def d1_gates(summary: dict[str, Any]) -> dict[str, bool]:
    """Sprint D1 acceptance 2, on eval/notes/v2: no unresolved S1; unresolved
    S2 in ≤ 2 % of notes; volume and section bands met on ≥ 90 %; no line
    with a label or pronoun subject, none that names, counts and dates
    nothing."""
    if summary.get("d1_unresolved_s1") is None:
        return {}
    return {
        "d1_no_unresolved_s1": summary["d1_unresolved_s1"] == 0,
        "d1_unresolved_s2_le_2pct": summary["d1_unresolved_s2_share"] <= 0.02,
        "d1_volume_band_90pct": summary["d1_volume_band"] >= 0.9,
        "d1_section_band_90pct": summary["d1_section_band"] >= 0.9,
        "d1_no_label_or_pronoun_subject": summary["d1_label_or_pronoun_lines"] == 0,
        "d1_no_unspecific_line": summary["d1_unspecific_lines"] == 0,
    }


def _lint_inputs(meeting: dict[str, Any], produced: dict[str, Any]) -> tuple[Any, Any] | None:
    """The produced note as the linter reads it: rendered sections and a
    context from the meeting. None when the arm writes no sections."""
    from types import SimpleNamespace

    from note_service.domain.meeting_doc import doclint

    if "sections" not in produced:
        return None
    sections = doclint.as_rendered(produced["sections"], produced.get("lines", []))
    speech = _merged_span([(t["t_start_ms"], t["t_end_ms"]) for t in meeting.get("transcript", [])])
    excluded = _merged_span([(int(r[0]), int(r[1])) for r in produced.get("noise_ranges", [])])
    gold = meeting.get("gold") or {}
    names = [
        *gold.get("name_candidates", []),
        *(gold.get("speakers") or {}).values(),
        *(e["canonical"] for e in gold.get("entities", [])),
    ]
    stats = produced.get("stats") or {}
    facts = {
        f["item_key"]: SimpleNamespace(
            item_key=f["item_key"],
            text=f.get("text", ""),
            quote=f.get("quote", ""),
            start_ms=int(f.get("start_ms") or 0),
            certainty=f.get("certainty"),
            evidence_only=bool(f.get("evidence_only")),
            figure=f.get("figure"),
            person=f.get("person"),
        )
        for f in produced.get("facts", [])
    }
    ctx = doclint.LintContext(
        language=meeting.get("language", "en"),
        speech_ms=max(0, speech - excluded),
        recording_type=stats.get("recording_type"),
        facts=facts,  # type: ignore[arg-type]
        known=frozenset(w for n in names for w in [n, *n.split()]),
        brief=dict(produced.get("brief") or {}),
        title=produced.get("title"),
    )
    return sections, ctx


def lint_produced(meeting: dict[str, Any], produced: dict[str, Any]) -> dict[str, Any] | None:
    """Sprint D1 — what the linter says about a produced note, by the same
    module production uses. A note the pipeline arm wrote was enforced
    already (``stats.lint``): its unresolved findings are what is left. Any
    other note is checked as it stands."""
    from note_service.domain.meeting_doc import doclint

    stats_lint = (produced.get("stats") or {}).get("lint")
    if stats_lint and not stats_lint.get("error"):
        return dict(stats_lint)
    inputs = _lint_inputs(meeting, produced)
    if inputs is None:
        return None
    findings = doclint.check(*inputs)
    return {
        "findings_by_code": doclint._count(f.code for f in findings),
        "unresolved": doclint._count(f.code for f in findings),
        "unresolved_rules": doclint._count(f.rule for f in findings),
        "unresolved_hard": doclint._count(f.code for f in findings if f.hard),
    }


def rubric_auto(meeting: dict[str, Any], produced: dict[str, Any]) -> dict[str, Any] | None:
    from note_service.domain.meeting_doc import doclint

    inputs = _lint_inputs(meeting, produced)
    return None if inputs is None else doclint.rubric_auto(*inputs)


_PAIRS = (
    # Sprint D2
    "sections_in_band",
    "headings_pass",
    "bullets_specific",
    "children",
    "roles_correct",
    "orientation_p1_ok",
    "lint_first_pass",
    "lint_after_regeneration",
    "unresolved_subject",
    "unspecific_bullets",
    "volume",
    "headings",
    "figure_recall",
    "figure_value_accuracy",
    "qualifier_preservation",
    "presenter_accuracy",
    "contact_present",
    "lines_cited",
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
    # Sprint SQ1
    "participant_recall",
    "participant_precision",
    "opinion_attribution",
    "title_ok",
)


def _rate(pair: list[int] | None) -> float | None:
    return (pair[0] / pair[1]) if pair and pair[1] else None


def aggregate(
    rows: list[dict[str, Any]], *, types: list[str | None] | None = None
) -> dict[str, Any]:
    """Corpus metrics from per-meeting rows: numerators and denominators
    summed first, then divided."""
    sums: dict[str, list[int]] = {k: [0, 0] for k in _PAIRS}
    thirds = {k: [0, 0] for k in ("1", "2", "3")}
    excluded = [0, 0]
    invented = echo = labels = 0
    lint_found: dict[str, int] = {}
    lint_codes: dict[str, int] = {}
    s1_left = s2_notes = volume_ok = sections_ok = 0
    subject_left = unspecific_left = 0
    auto: dict[str, list[int]] = {"Q3": [], "Q7": []}
    subject_failures = narrator_errors = 0
    ladders: dict[str, int] = {}
    linted_docs = lint_clean = 0
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
        echo += int(row.get("example_echo") or 0)
        labels += int(row.get("label_lines") or 0)
        subject_failures += int(row.get("subject_failures") or 0)
        narrator_errors += int(row.get("narrator_attribution_errors") or 0)
        if row.get("summary_ladder"):
            ladders[row["summary_ladder"]] = ladders.get(row["summary_ladder"], 0) + 1
        for q, score in (row.get("rubric_auto") or {}).items():
            if score is not None:
                auto[q].append(int(score))
        if "lint" in row:
            lint = row["lint"]
            left = lint.get("unresolved") or {}
            left_rules = lint.get("unresolved_rules") or {}
            linted_docs += 1
            lint_clean += 0 if left else 1
            for code, count in (lint.get("findings_by_code") or {}).items():
                lint_found[code] = lint_found.get(code, 0) + int(count)
            for code, count in left.items():
                lint_codes[code] = lint_codes.get(code, 0) + int(count)
            hard = lint.get("unresolved_hard") or {}
            s1_left += sum(int(n) for c, n in hard.items() if c.startswith("F-") and c not in _S2_F)
            s2_notes += 1 if any(not c.startswith("F-") or c in _S2_F for c in hard) else 0
            volume_ok += 0 if left_rules.get("volume.words") else 1
            sections_ok += 0 if left_rules.get("sections.count") else 1
            subject_left += int(left_rules.get("line.subject") or 0)
            unspecific_left += int(left_rules.get("line.specific") or 0)
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
        "example_echo": echo,
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
        "key_dates_recall": _rate(sums["key_dates_recall"]),
        "entity_sources": _sum_sources(rows),
        "date_resolution": _rate(sums["date_resolution"]),
        "figure_recall": _rate(sums["figure_recall"]),
        "figure_value_accuracy": _rate(sums["figure_value_accuracy"]),
        "qualifier_preservation": _rate(sums["qualifier_preservation"]),
        "presenter_accuracy": _rate(sums["presenter_accuracy"]),
        "contact_present": _rate(sums["contact_present"]),
        **f2,
        # Error taxonomy detectors.
        "label_lines": labels,
        "unresolved_subject_rate": _rate(sums["unresolved_subject"]),
        "unspecific_bullet_rate": _rate(sums["unspecific_bullets"]),
        "words_per_minute": (
            sums["volume"][0] * 60 / sums["volume"][1] if sums["volume"][1] else None
        ),
        # Sprint D2: composition.
        "sections_in_band": _rate(sums["sections_in_band"]),
        "headings_pass": _rate(sums["headings_pass"]),
        "bullets_specific_share": _rate(sums["bullets_specific"]),
        "children_share": _rate(sums["children"]),
        "subject_failures": subject_failures,
        "narrator_attribution_errors": narrator_errors,
        "roles_correct": _rate(sums["roles_correct"]),
        "orientation_p1_ok": _rate(sums["orientation_p1_ok"]),
        "lint_first_pass": _rate(sums["lint_first_pass"]),
        "lint_after_regeneration": _rate(sums["lint_after_regeneration"]),
        "summary_ladder": dict(sorted(ladders.items())),
        # Sprint D1: what the linter found, what it could not repair, and the
        # numbers its gates read.
        "lint_findings": dict(sorted(lint_found.items())),
        "lint_unresolved": dict(sorted(lint_codes.items())),
        "lint_clean_rate": (lint_clean / linted_docs) if linted_docs else None,
        "d1_unresolved_s1": s1_left if linted_docs else None,
        "d1_unresolved_s2_share": (s2_notes / linted_docs) if linted_docs else None,
        "d1_volume_band": (volume_ok / linted_docs) if linted_docs else None,
        "d1_section_band": (sections_ok / linted_docs) if linted_docs else None,
        "d1_label_or_pronoun_lines": subject_left if linted_docs else None,
        "d1_unspecific_lines": unspecific_left if linted_docs else None,
        # The rubric's Q3 and Q7 read by code, mean of 0–2 per note.
        "rubric_auto_q3": (sum(auto["Q3"]) / len(auto["Q3"])) if auto["Q3"] else None,
        "rubric_auto_q7": (sum(auto["Q7"]) / len(auto["Q7"])) if auto["Q7"] else None,
        "headings_per_10_min": (
            sums["headings"][0] * 600 / sums["headings"][1] if sums["headings"][1] else None
        ),
        # Sprint SQ1 (01-quality-criteria §3).
        "participant_precision": _rate(sums["participant_precision"]),
        "participant_recall": _rate(sums["participant_recall"]),
        "opinion_attribution": _rate(sums["opinion_attribution"]),
        "filler_lines": sq1["filler_lines"],
        "title_ok": _rate(sums["title_ok"]),
        "by_third_ratio": (min(present) / max(present)) if present and max(present) > 0 else None,
        # Sprint SQ2.
        "sections_count_ok": (sections_ok / linted_docs) if linted_docs else None,
        "near_empty_rate": _rate(near_empty),
        "one_bullet_sections": one_bullet,
        # Sprint SQ3.
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
