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

SUPPORT_THRESHOLD = 0.5
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


def support(line: str, cited: list[str], language: str = "en") -> bool:
    """A line is supported when at least half its content is in the text and
    quotes of what it cites, every number in it is too, and it names nobody
    they do not. The ratio and the name rule are the engine's own
    (``meeting_doc.support``), so the eval and the gate cannot disagree."""
    evidence = " ".join(cited)
    body = _body(line)
    if support_rules.support_ratio(body, evidence, language) < SUPPORT_THRESHOLD:
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
        _, best = best_match(fact, texts)
        hit = best >= MATCH_THRESHOLD
        recall.add(hit)
        thirds[_third_of(meeting, fact)].add(hit)
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

    # Checklists, by index.
    row["must_contain_failed"] = [
        i for i, s in enumerate(gold.get("must_contain", [])) if not _contains(everything, s)
    ]
    row["must_not_contain_failed"] = [
        i for i, s in enumerate(gold.get("must_not_contain", [])) if _contains(everything, s)
    ]
    return row


# ── F2: statements, not quotes ──────────────────────────────────────

# Lines that are a task or an outcome: short by nature, phrased as said.
_TASK_LINE_KINDS = frozenset({"action", "commitment_ours", "commitment_theirs", "decision"})
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


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

_PAIRS = (
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
    invented = echo = 0
    f2 = {"copied_lines": 0, "no_information_lines": 0, "first_person_lines": 0}
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
        for key in f2:
            f2[key] += int(row.get(key) or 0)
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
        **f2,
    }


def _sum_sources(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        for source, n in (row.get("entity_sources") or {}).items():
            out[source] = out.get(source, 0) + int(n)
    return dict(sorted(out.items()))
