#!/usr/bin/env python3
"""The notes gold-set harness (Sprint 33 B-2, run for Sprint 37's bake-off).

    make eval-notes BACKEND=dev_mac                      # the real pipeline
    make eval-notes BACKEND=cand_qwen_32b ARM=single_pass  # the baseline arm
    ENV=staging make eval-notes BACKEND=hf_eu CORPUS=eval/notes/v1

Two arms, same corpus, same metrics:

* **pipeline** — the document engine as it actually runs: windowed
  extraction, verification in code, merge, render. This is what ships.
* **single_pass** — one long-context prompt asking for the whole
  document. The architecture of the category on a frontier model, and the
  bar our extra machinery has to clear (Sprint 37 B-4, arm C).

Metrics are the ones the GA gates are written in: key-fact recall,
action/decision precision and recall, owner accuracy, citation precision
and the faithfulness invariant (a quote that is not in the transcript).
Cost and seconds are per meeting-hour, because that is the unit a
capacity line and a price are written in.

The corpus is data, never code: `--corpus` points at a directory of JSON
files. The committed one is synthetic (no real people); the real gold set
lives in the eval bucket under the consent register and is never in git.
Nothing here prints a transcript, a quote or a name.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, load_registry, write_report  # noqa: E402

DEFAULT_CORPUS = REPO / "tests" / "fixtures" / "eval" / "notes"
ENGINE_SRC = REPO / "services" / "note-service" / "src"

# A produced line matches a gold fact when they share this much of the
# gold fact's content words. Deliberately lenient on wording and strict on
# content: "Priya sends the release note to support by Thursday" and
# "Release note to support — Priya, Thursday" are the same fact.
MATCH_THRESHOLD = 0.6

_WORD = re.compile(r"[\w']+", re.UNICODE)
# Words that carry no content in any of the three languages we ship.
STOP = frozenset(
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
        "in",
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
)


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


def overlap(gold: str, produced: str) -> float:
    g = words(gold)
    return len(g & words(produced)) / len(g) if g else 0.0


def best_match(gold: str, lines: list[str]) -> tuple[int, float]:
    scored = [(i, overlap(gold, line)) for i, line in enumerate(lines)]
    return max(scored, key=lambda p: p[1], default=(-1, 0.0))


@dataclass
class Counts:
    """One metric's tally across the corpus. Sums, then one division."""

    hit: int = 0
    total: int = 0

    def add(self, hit: bool) -> None:
        self.hit += 1 if hit else 0
        self.total += 1

    @property
    def rate(self) -> float | None:
        return (self.hit / self.total) if self.total else None


@dataclass
class Totals:
    key_facts: Counts = field(default_factory=Counts)
    actions_recall: Counts = field(default_factory=Counts)
    actions_precision: Counts = field(default_factory=Counts)
    decisions_recall: Counts = field(default_factory=Counts)
    decisions_precision: Counts = field(default_factory=Counts)
    owners: Counts = field(default_factory=Counts)
    citations: Counts = field(default_factory=Counts)
    seconds: float = 0.0
    audio_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    windows: int = 0
    windows_failed: int = 0


def transcript_text(meeting: dict[str, Any]) -> str:
    return " ".join(t["text"] for t in meeting["transcript"])


def audio_seconds(meeting: dict[str, Any]) -> float:
    turns = meeting["transcript"]
    return (turns[-1]["t_end_ms"] / 1000.0) if turns else 0.0


def as_asr_result(meeting: dict[str, Any]) -> dict[str, Any]:
    """The gold file in the shape the engine reads (an ASR result)."""
    return {
        "language": meeting.get("language", "en"),
        "result_rev": 1,
        "turns": [
            {
                "speaker": t["speaker"],
                "start_ms": t["t_start_ms"],
                "end_ms": t["t_end_ms"],
                "text": t["text"],
            }
            for t in meeting["transcript"]
        ],
    }


# ── the two arms ────────────────────────────────────────────────────


async def run_pipeline(meeting: dict[str, Any], provider: Any) -> dict[str, Any]:
    """The engine, exactly as the worker runs it."""
    from note_service.domain.meeting_doc import pipeline, types

    family = types.family_for_type(meeting.get("meeting_type"))
    started = time.monotonic()
    document = await pipeline.run(
        as_asr_result(meeting),
        provider=provider,
        role_by_key={},
        language=meeting.get("language", "en"),
        family=family,
    )
    return {
        "seconds": time.monotonic() - started,
        "lines": [f.text for f in document.facts],
        "actions": [
            f
            for f in document.facts
            if f.kind in ("action", "commitment_ours", "commitment_theirs")
        ],
        "decisions": [f for f in document.facts if f.kind == "decision"],
        "quotes": [(f.quote, f.turn) for f in document.facts],
        "windows": document.windows_total,
        "windows_failed": document.windows_failed,
    }


SINGLE_PASS_SYSTEM = (
    "You write meeting notes. Given a transcript, write the notes a participant would "
    "send round afterwards: a short summary, the decisions, and the action items with "
    "owners and dates. Write in the language of the meeting. Do not invent anything."
)

SINGLE_PASS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "decisions", "actions"],
    "properties": {
        "summary": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "decisions": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "actions": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "owner": {"type": ["string", "null"]},
                    "due": {"type": ["string", "null"]},
                },
            },
        },
    },
}


async def run_single_pass(meeting: dict[str, Any], provider: Any) -> dict[str, Any]:
    """Arm C: one prompt, one pass, no verification. The bar."""
    lines = [
        f"[{t['speaker']} {t['t_start_ms'] // 1000}s] {t['text']}" for t in meeting["transcript"]
    ]
    prompt = "Transcript:\n" + "\n".join(lines) + "\n\nWrite the notes now."
    started = time.monotonic()
    result = await provider.complete(
        prompt, SINGLE_PASS_SCHEMA, max_tokens=2048, temperature=0.2, system=SINGLE_PASS_SYSTEM
    )
    obj = result.json if isinstance(result.json, dict) else {}
    actions = [
        type(
            "A",
            (),
            {"text": a.get("text", ""), "owner_label": a.get("owner"), "quote": "", "turn": -1},
        )()
        for a in obj.get("actions", [])
        if a.get("text")
    ]
    decisions = [
        type("D", (), {"text": d, "owner_label": None, "quote": "", "turn": -1})()
        for d in obj.get("decisions", [])
        if d
    ]
    return {
        "seconds": time.monotonic() - started,
        "lines": [
            *obj.get("summary", []),
            *[d.text for d in decisions],
            *[a.text for a in actions],
        ],
        "actions": actions,
        "decisions": decisions,
        # No citations by construction: that is the point of the comparison.
        "quotes": [],
        "windows": 1,
        "windows_failed": 0,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


# ── scoring ─────────────────────────────────────────────────────────


def score(meeting: dict[str, Any], produced: dict[str, Any], totals: Totals) -> dict[str, Any]:
    gold = meeting.get("gold", {})
    lines: list[str] = [line for line in produced["lines"] if line]
    text = transcript_text(meeting)
    norm_text = " ".join(text.lower().split())

    row: dict[str, Any] = {"meeting": meeting["id"], "language": meeting.get("language", "en")}

    # Key facts: did the document say the things a reader needed?
    missed: list[str] = []
    for i, fact in enumerate(gold.get("key_facts", [])):
        _, best = best_match(fact, lines)
        hit = best >= MATCH_THRESHOLD
        totals.key_facts.add(hit)
        if not hit:
            missed.append(f"#{i + 1}")
    row["key_facts_missed"] = missed

    # Actions and decisions, both directions.
    for kind, produced_items, gold_items, rec, prec in (
        (
            "action",
            produced["actions"],
            gold.get("actions", []),
            totals.actions_recall,
            totals.actions_precision,
        ),
        (
            "decision",
            produced["decisions"],
            gold.get("decisions", []),
            totals.decisions_recall,
            totals.decisions_precision,
        ),
    ):
        produced_texts = [item.text for item in produced_items]
        for entry in gold_items:
            want = entry["text"] if isinstance(entry, dict) else entry
            index, best = best_match(want, produced_texts)
            hit = best >= MATCH_THRESHOLD
            rec.add(hit)
            # Owner accuracy is only meaningful on a matched action.
            if hit and kind == "action" and isinstance(entry, dict) and entry.get("owner"):
                got = (produced_items[index].owner_label or "").strip().casefold()
                totals.owners.add(got == str(entry["owner"]).strip().casefold())
        gold_texts = [e["text"] if isinstance(e, dict) else e for e in gold_items]
        for produced_text in produced_texts:
            _, best = best_match(produced_text, gold_texts) if gold_texts else (-1, 0.0)
            prec.add(best >= MATCH_THRESHOLD)
        row[f"{kind}s"] = len(produced_items)

    # The invariant: every quote is verbatim, and from the turn claimed.
    for quote, turn in produced["quotes"]:
        verbatim = bool(quote) and " ".join(quote.lower().split()) in norm_text
        in_turn = False
        if 0 <= turn < len(meeting["transcript"]):
            turn_text = " ".join(meeting["transcript"][turn]["text"].lower().split())
            in_turn = bool(quote) and " ".join(quote.lower().split()) in turn_text
        totals.citations.add(verbatim and in_turn)
        if not verbatim:
            row["hallucinated_quote"] = True

    totals.seconds += produced["seconds"]
    totals.audio_seconds += audio_seconds(meeting)
    totals.input_tokens += int(produced.get("input_tokens", 0) or 0)
    totals.output_tokens += int(produced.get("output_tokens", 0) or 0)
    totals.windows += produced["windows"]
    totals.windows_failed += produced["windows_failed"]
    row["seconds"] = round(produced["seconds"], 1)
    return row


def summarise(totals: Totals, hours: float) -> dict[str, Any]:
    def f1(p: float | None, r: float | None) -> float | None:
        return (2 * p * r / (p + r)) if (p and r) else None

    return {
        "key_fact_recall": totals.key_facts.rate,
        "action_recall": totals.actions_recall.rate,
        "action_precision": totals.actions_precision.rate,
        "action_f1": f1(totals.actions_precision.rate, totals.actions_recall.rate),
        "decision_recall": totals.decisions_recall.rate,
        "decision_precision": totals.decisions_precision.rate,
        "owner_accuracy": totals.owners.rate,
        "citation_precision": totals.citations.rate,
        "window_failure_rate": (totals.windows_failed / totals.windows) if totals.windows else None,
        "seconds_per_meeting_hour": round(totals.seconds / hours, 1) if hours else None,
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
    }


async def main(arm: str, backend_name: str, corpus: Path, runs: int) -> int:
    sys.path.insert(0, str(ENGINE_SRC))
    from models import ProviderError, build_chat_provider

    registry = load_registry()
    resolved = registry.backend(backend_name, expect_kind="chat")
    provider = build_chat_provider(resolved)
    print(
        f"arm={arm} backend={resolved.name} model={resolved.model_id} "
        f"processor={resolved.processor.name if resolved.processor else '-'}"
    )

    meetings = [json.loads(p.read_text("utf-8")) for p in sorted(corpus.glob("*.json"))]
    if not meetings:
        print(f"no meetings in {corpus}", file=sys.stderr)
        return 2

    runner = run_pipeline if arm == "pipeline" else run_single_pass
    all_runs: list[dict[str, Any]] = []
    for run_index in range(runs):
        totals = Totals()
        rows: list[dict[str, Any]] = []
        for meeting in meetings:
            try:
                produced = await runner(meeting, provider)
            except ProviderError as exc:
                rows.append({"meeting": meeting["id"], "error_kind": str(exc.kind)})
                print(f"  {meeting['id']:<26} FAIL {exc.kind}")
                continue
            row = score(meeting, produced, totals)
            rows.append(row)
            print(
                f"  {meeting['id']:<26} {row['seconds']:6.1f}s  "
                f"actions={row.get('actions', 0)} decisions={row.get('decisions', 0)}"
                + (
                    f"  missed key facts {row['key_facts_missed']}"
                    if row["key_facts_missed"]
                    else ""
                )
            )
        hours = totals.audio_seconds / 3600.0
        summary = summarise(totals, hours)
        all_runs.append({"run": run_index + 1, "summary": summary, "meetings": rows})
        print(f"  run {run_index + 1}: " + json.dumps(summary))

    await provider.aclose()
    report = {
        "arm": arm,
        "backend": resolved.name,
        "model_id": resolved.model_id,
        "processor": resolved.processor.model_dump() if resolved.processor else None,
        "corpus": str(corpus.relative_to(REPO)) if corpus.is_relative_to(REPO) else str(corpus),
        "meetings": len(meetings),
        "runs": all_runs,
    }
    if arm == "pipeline":
        from note_service.domain.meeting_doc.prompts import PROMPT_VERSION

        report["prompt_version"] = PROMPT_VERSION
    path = write_report(f"notes-{arm}", resolved.name, report)
    print(f"wrote {path}")
    # A hallucinated quote is a failed run, not a lower score: the whole
    # design says a fact without verbatim words does not reach the page.
    return 1 if any(m.get("hallucinated_quote") for r in all_runs for m in r["meetings"]) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--arm", choices=["pipeline", "single_pass"], default="pipeline")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--runs", type=int, default=1, help="repeat for variance (the bake-off uses 3)")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.arm, args.backend, args.corpus, args.runs)))
