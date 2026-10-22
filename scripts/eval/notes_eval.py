#!/usr/bin/env python3
"""The notes gold-set harness: the ``pipeline`` arm (the document engine as it ships)
and the ``single_pass`` arm (one long-context prompt) on the same corpus and metrics.

    make eval-notes BACKEND=dev_mac
    make eval-notes BACKEND=cand_qwen_32b ARM=single_pass

The corpus is data (``--corpus``); the committed one is synthetic, the real gold set is
never in git. Nothing here prints a transcript, a quote or a name.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    REPO,
    Paced,
    load_registry,
    write_report,
)
from notes_gold import fact_text  # noqa: E402
from notes_scoring import (  # noqa: E402, F401 — re-exported for the harness tests
    COMPOSED,
    MATCH_THRESHOLD,
    STOP,
    _body,
    aggregate,
    best_match,
    f2_gates,
    overlap,
    score_meeting,
    sq3_gates,
    support,
    words,
)
from taxonomy import METRIC_CODES  # noqa: E402

from note_service.domain import text as text_rules  # noqa: E402

DEFAULT_CORPUS = REPO / "tests" / "fixtures" / "eval" / "notes"
ENGINE_SRC = REPO / "services" / "note-service" / "src"
TEMPLATES = REPO / "infra" / "seeds" / "templates"

# Exit codes the nightly job reads.
EXIT_FAILED = 1  # a hallucinated quote, or a meeting the model could not finish
EXIT_NO_CORPUS = 3
# Entity model tier: off as in production unless `--entity-model-tier`.


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


def default_speaker_name(label: str) -> str:
    """``SPEAKER_2`` → ``Speaker 2``, as the ASR result view does."""
    if label.startswith("SPEAKER_") and label[8:].isdigit():
        return f"Speaker {label[8:]}"
    return label


def as_asr_result(meeting: dict[str, Any]) -> dict[str, Any]:
    """The gold file in the shape the worker snapshots: the ASR result
    view (``asr_models.output``), with turns as paragraphs and names
    applied. The engine reads exactly this, so the harness measures what
    ships."""
    gold = meeting.get("gold") or {}
    names: dict[str, str] = dict(gold.get("speakers") or {})
    labels = list(dict.fromkeys(t["speaker"] for t in meeting["transcript"]))
    speaker_names = {label: names.get(label) or default_speaker_name(label) for label in labels}
    result: dict[str, Any] = {
        "language": meeting.get("language", "en"),
        "result_rev": 1,
        "speaker_names": speaker_names,
        "name_candidates": list(gold.get("name_candidates") or []),
        "turns": [
            {
                "speaker": t["speaker"],
                "name": speaker_names[t["speaker"]],
                "start_ms": t["t_start_ms"],
                "end_ms": t["t_end_ms"],
                "paragraphs": [t["text"]],
                # The ASR's per-turn language, as the result view carries it.
                **({"language": t["language"]} if t.get("language") else {}),
            }
            for t in meeting["transcript"]
        ],
    }
    if meeting.get("noise"):
        result["noise"] = list(meeting["noise"])
    if meeting.get("recorded_on"):
        result["recorded_on"] = meeting["recorded_on"]
    return result


def template_code(family: Any, language: str) -> str:
    """The seed template the worker would find for this family and
    language: ``meeting_notes_de``, else the English one."""
    localised = f"{family.template_prefix}_{language}"
    if language != "en" and (TEMPLATES / f"{localised}.json").is_file():
        return localised
    return str(family.template_prefix)


def role_map(code: str) -> dict[str, str]:
    """``{section_key: role}`` from the seed template, through ``TemplateDefinition`` +
    ``roles.role_map`` — minus the database."""
    from note_service.domain import roles
    from template_models import TemplateDefinition

    path = TEMPLATES / f"{code}.json"
    if not path.is_file():
        return {}
    definition = TemplateDefinition.model_validate(json.loads(path.read_text("utf-8")))
    return dict(roles.role_map(definition))


# Sprint R0 removed the pipeline arm (the old writing path). Sprint P3 adds the arm that
# scores the notes the writer (P1) stores; until then ``single_pass`` is the only arm.
ARMS = ("single_pass",)


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
    lines = [
        *({"kind": "summary", "text": t} for t in obj.get("summary", []) if t),
        *({"kind": "decision", "text": d.text} for d in decisions),
        *({"kind": "action", "text": a.text} for a in actions),
    ]
    return {
        "seconds": time.monotonic() - started,
        "lines": [{"section_key": "single_pass", "fact_ids": [], **line} for line in lines],
        "facts": [],
        "brief": {},
        "stats": {},
        "noise_ranges": [],
        # Cites nothing, so its support is read against the transcript.
        "evidence": "transcript",
        "note_text": "\n\n".join(
            block
            for block in (
                "\n".join(obj.get("summary", [])),
                "\n".join(f"- {d.text}" for d in decisions),
                "\n".join(f"- {a.text}" for a in actions),
            )
            if block
        ),
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
    lines: list[str] = [
        line["text"] if isinstance(line, dict) else line
        for line in produced["lines"]
        if line and (not isinstance(line, dict) or line.get("kind") not in ("heading", "note"))
    ]
    text = transcript_text(meeting)

    row: dict[str, Any] = {"meeting": meeting["id"], "language": meeting.get("language", "en")}

    # Key facts: did the document say the things a reader needed?
    missed: list[str] = []
    for i, fact in enumerate(gold.get("key_facts", [])):
        _, best = best_match(fact_text(fact), lines)
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

    # Every quote is verbatim and from the turn claimed, compared the way the
    # engine compares (`verify.normalise_quote`); raw text comparison flagged
    # ASR punctuation differences as hallucinations.
    from _textrules import normalise_quote, strip_turn_header

    norm_text = normalise_quote(text)
    for quote, turn in produced["quotes"]:
        needle = normalise_quote(strip_turn_header(quote or ""))
        verbatim = bool(needle) and needle in norm_text
        in_turn = False
        if 0 <= turn < len(meeting["transcript"]):
            in_turn = bool(needle) and needle in normalise_quote(
                meeting["transcript"][turn]["text"]
            )
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


def cost_summary(backend: str, totals: Totals, hours: float) -> dict[str, Any]:
    """``cost_cents`` and ``cost_cents_per_meeting_hour`` from the token
    totals at the rates the ledger uses; None when the backend is unpriced."""
    try:
        from jobs import CostTable
        from models import UsageRecord

        table = CostTable.load(REPO / "config" / "model_costs.yaml")
        if not table.is_priced(backend):
            return {"cost_cents": None, "cost_cents_per_meeting_hour": None}
        cents = table.estimate_cents(
            UsageRecord(
                backend=backend,
                model_id="",
                operation="eval",
                ok=True,
                latency_ms=0,
                input_tokens=totals.input_tokens,
                output_tokens=totals.output_tokens,
            )
        )
    except Exception:  # noqa: BLE001 — a missing cost table is a null column
        return {"cost_cents": None, "cost_cents_per_meeting_hour": None}
    return {
        "cost_cents": round(cents, 2),
        "cost_cents_per_meeting_hour": round(cents / hours, 2) if hours else None,
    }


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


# ── the judge column (eval only) ────────────────────────────────────

JUDGE_PROBLEMS = ("none", "new_claim", "wrong_number", "wrong_actor", "stronger_than_said", "other")
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["supported", "problem"],
    "properties": {
        "supported": {"type": "boolean"},
        "problem": {"type": "string", "enum": list(JUDGE_PROBLEMS)},
    },
}
JUDGE_SYSTEM = (
    "You check one line of a meeting record against the facts it cites. Each fact has "
    "a statement and the verbatim words it was taken from. Answer supported=true only "
    "if everything the line says is carried by those facts: no new claim, no number "
    "that is not there, no different person, nothing stated more certainly than it "
    "was said. A reporting clause that names who said something is not a new claim. "
    "Otherwise name the problem. Judge only; do not rewrite."
)


@dataclass
class JudgeTotals:
    judged: int = 0
    unsupported: int = 0
    disagree: int = 0
    problems: Counter = field(default_factory=Counter)
    # One record per judged line for support_calibration.py; carries text, local disk only.
    records: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        if not self.judged:
            return {
                "judge_unsupported_rate": None,
                "judge_problems": {},
                "deterministic_vs_judge_disagreement": None,
            }
        return {
            "judge_unsupported_rate": self.unsupported / self.judged,
            "judge_problems": dict(sorted(self.problems.items())),
            "deterministic_vs_judge_disagreement": self.disagree / self.judged,
            "judge_lines": self.judged,
        }


async def judge(
    produced: dict[str, Any],
    provider: Any,
    totals: JudgeTotals,
    usage: Totals,
    *,
    language: str = "en",
    meeting_id: str = "",
) -> None:
    """One call per composed line that cites facts: the line and those
    facts' text and quote — never the transcript. Records whether the
    deterministic support check would have said the same."""
    facts = {f["item_key"]: f for f in produced.get("facts", [])}
    for line in produced.get("lines", []):
        cited = [facts[i] for i in line.get("fact_ids", []) if i in facts]
        if line.get("kind") not in COMPOSED or not cited:
            continue
        listing = "\n".join(f'- {f["text"]} (said: "{f["quote"]}")' for f in cited)
        prompt = f"Line:\n{line['text']}\n\nFacts it cites:\n{listing}"
        answer = await provider.complete(
            prompt, JUDGE_SCHEMA, max_tokens=200, temperature=0.0, system=JUDGE_SYSTEM
        )
        usage.input_tokens += int(getattr(answer, "input_tokens", 0) or 0)
        usage.output_tokens += int(getattr(answer, "output_tokens", 0) or 0)
        verdict = answer.json if isinstance(answer.json, dict) else {}
        supported = bool(verdict.get("supported"))
        problem = verdict.get("problem") if verdict.get("problem") in JUDGE_PROBLEMS else "other"
        totals.judged += 1
        totals.unsupported += 0 if supported else 1
        totals.problems[problem] += 1
        evidence = [f"{f['text']} {f['quote']}" for f in cited]
        deterministic = support(line["text"], evidence, language)
        totals.disagree += 1 if deterministic != supported else 0
        body = _body(line["text"])
        totals.records.append(
            {
                "meeting": meeting_id,
                "language": language,
                "kind": line.get("kind"),
                "text": line["text"],
                "ratio": text_rules.support_ratio(body, " ".join(evidence), language),
                # The rules the threshold does not decide: a line failing
                # them is unsupported at any threshold.
                "rules_ok": support(line["text"], evidence, language, threshold=0.0),
                "judge_supported": supported,
                "problem": problem,
            }
        )


_STAT_KEYS = (
    # Task 4: the code that wrote it, throttling, the type decision, failed calls by reason.
    "build",
    "throttle",
    "classify",
    "summary_failure",
    "call_failures",
    "lines_composed",
    "lines_model_kept",
    "holder_sources",
    "address_cues",
    "name_conflicts",
    # N2: what a writing profile did (numbers and booleans only).
    "instructions_applied",
    "length_scale",
    "target_words",
    "facts_kept",
    "facts_dropped_quote",
    "facts_dropped_noise",
    "facts_dropped_example",
    "example_echo_dropped",
    "noise_passages",
    "facts_downgraded",
    "numbers_removed",
    "facts_after_merge",
    # Form
    "facts_dropped_paraphrase",
    "facts_flagged_paraphrase",
    "lines_kept",
    "noise_flagged",
    "noise_confirmed",
    "noise_advisory",
    "noise_overridden",
    "excluded_ms",
    "speech_ms",
    "summary_retries",
    "summary_fallback",
    # Context
    "redundant_lines",
    "lines_total",
    "recording_type",
    "recording_type_source",
    # The funnel and the profile, per meeting.
    "blocks",
    "block_chapters",
    "block_calls",
    "windows_restated",
    "summary_ladder",
    "small_model_profile",
    # The coverage diagnosis, per window and per third.
    "windows",
    "facts_by_third",
    "lines_by_third",
    "reduce_input_facts",
    "reduce_cited_facts",
    "reduce_cited_by_third",
    "excluded_speech_ms",
    "blocks_planned",
    "blocks_rendered",
    "sections_rendered",
    "window_chars",
    "context_window",
    "speech_minutes_by_third",
    "coverage_retry",
    "coverage_retry_facts",
    "coverage_retry_skipped",
    "coverage_gaps",
    "blocks_source",
    "blocks_boundaries",
    "blocks_merged_small",
    "salient_appended",
    "salient_skipped_full",
    # B2 T1: why the gate dropped lines and why block calls failed, per generation.
    "lines_unsupported",
    "block_failures",
    "topics_failure",
    "summary_fallback",
    "outline",
    # A2: pronoun sentences accepted on the run's holder.
    "attribution_anaphora",
    # Review step 3: one speaker or a memo — attribution implicit, and the lines it let through.
    "attribution_implicit",
    "attribution_implicit_lines",
    # A1: the holder re-ask and the turn rule.
    "holders_reasked",
    "holders_repaired",
    "holders_from_turn",
    "holders_unknown",
)


def _recall(rows: list[dict[str, Any]]) -> float | None:
    """Micro-averaged ``key_fact_recall`` over rows carrying ``[hits, total]``."""
    hits = total = 0
    for r in rows:
        pair = r.get("key_fact_recall")
        if isinstance(pair, list) and len(pair) == 2:
            hits += pair[0]
            total += pair[1]
    return round(hits / total, 3) if total else None


def cell_rollup(all_runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per language × family over every run (B2 T1): how often the model path wrote
    the summary and the blocks, and the gate's reasons. Numbers only."""
    from note_service.domain import families

    cells: dict[str, list[dict[str, Any]]] = {}
    for run in all_runs:
        for row in run["meetings"]:
            if row.get("failed"):
                continue
            stats = row.get("stats") or {}
            family = families.family_for_recording_type(stats.get("recording_type")).meeting_type
            cells.setdefault(f"{row.get('language', '?')}/{family}", []).append(row)
    out: dict[str, dict[str, Any]] = {}
    for cell, rows in sorted(cells.items()):
        n = len(rows)
        ladders = Counter(r.get("summary_ladder") or "none" for r in rows)
        reasons: Counter[str] = Counter()
        failures: Counter[str] = Counter()
        for r in rows:
            reasons.update((r.get("stats") or {}).get("lines_unsupported") or {})
            failures.update((r.get("stats") or {}).get("block_failures") or {})
        chaptered = sum(1 for r in rows if ((r.get("stats") or {}).get("block_chapters") or 0) > 0)
        model_path = sum(
            1
            for r in rows
            if r.get("summary_ladder") == "model"
            and not ((r.get("stats") or {}).get("block_chapters") or 0)
        )
        out[cell] = {
            "n": n,
            "meetings": sorted({r["meeting"] for r in rows}),
            "summary_ladder": dict(ladders),
            "chaptered": chaptered,
            "model_path_share": round(model_path / n, 3),
            "fallback_share": round(1 - model_path / n, 3),
            "block_chapters_mean": round(
                sum((r.get("stats") or {}).get("block_chapters") or 0 for r in rows) / n, 2
            ),
            "facts_kept_mean": round(
                sum((r.get("stats") or {}).get("facts_kept") or 0 for r in rows) / n, 1
            ),
            "facts_dropped_paraphrase": sum(
                (r.get("stats") or {}).get("facts_dropped_paraphrase") or 0 for r in rows
            ),
            "lines_unsupported": dict(sorted(reasons.items())),
            "block_failures": dict(sorted(failures.items())),
            # A2: the two drop reasons the run rule targets, and the anaphora it allowed.
            "attribution_drops": reasons.get("attribution", 0),
            "hedge_drops": reasons.get("hedge", 0),
            "attribution_anaphora": sum(
                (r.get("stats") or {}).get("attribution_anaphora") or 0 for r in rows
            ),
            "key_fact_recall": _recall(rows),
        }
    return out


LOCAL = REPO / "scripts" / "eval" / "local"


def save_judge_lines(path: Path, run: int, records: list[dict[str, Any]]) -> None:
    """The judged lines, for support_calibration.py — local disk only, like
    notes: a line's text is content."""
    path = path.resolve()
    if not path.is_relative_to(LOCAL.resolve()):
        raise SystemExit(f"--judge-lines must be under {LOCAL}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps({"run": run, **record}, ensure_ascii=False) + "\n")


def save_note(folder: Path, meeting_id: str, text: str) -> None:
    """A note's text for blind rating. Only under the gitignored
    ``scripts/eval/local/`` — a note written from a real recording is
    content, and content never enters the repo."""
    folder = folder.resolve()
    if not folder.is_relative_to(LOCAL.resolve()):
        raise SystemExit(f"--save-notes must be under {LOCAL}")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{meeting_id}.md").write_text(text + "\n", encoding="utf-8")


async def main(
    arm: str,
    backend_name: str,
    corpus: Path,
    runs: int,
    judge_backend: str | None = None,
    save_notes: Path | None = None,
    f2_baseline: Path | None = None,
    judge_lines: Path | None = None,
    label: str | None = None,
    sq1_baseline: Path | None = None,
    allow_stale: bool = False,
) -> int:
    sys.path.insert(0, str(ENGINE_SRC))
    from models import ProviderError, build_chat_provider

    if arm not in ARMS:
        print(
            f"arm {arm!r} is not available (Sprint P3 adds the stored-notes arm)", file=sys.stderr
        )
        return EXIT_NO_CORPUS
    if not corpus.is_dir():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return EXIT_NO_CORPUS
    meetings = [json.loads(p.read_text("utf-8")) for p in sorted(corpus.glob("*.json"))]
    meetings = [m for m in meetings if "transcript" in m]
    if not meetings:
        print(f"no meetings in {corpus}", file=sys.stderr)
        return EXIT_NO_CORPUS

    registry = load_registry()
    resolved = registry.backend(backend_name, expect_kind="chat")
    # A rate limit is waited out, never scored as the model's answer.
    provider = Paced(build_chat_provider(resolved))
    print(
        f"arm={arm} backend={resolved.name} model={resolved.model_id} "
        f"processor={resolved.processor.name if resolved.processor else '-'}"
    )
    judge_provider = None
    judge_model = None
    if judge_backend:
        try:
            judged = registry.backend(judge_backend, expect_kind="chat")
            judge_provider = build_chat_provider(judged)
            judge_model = judged.model_id
        except Exception as exc:  # noqa: BLE001 — a judge that cannot start is a null column
            print(f"judge unavailable ({type(exc).__name__}); column will be null")

    runner = run_single_pass
    all_runs: list[dict[str, Any]] = []
    failed = False
    for run_index in range(runs):
        totals = Totals()
        judge_totals = JudgeTotals()
        judge_ok = judge_provider is not None
        rows: list[dict[str, Any]] = []
        audit_rows: list[dict[str, Any]] = []
        types: list[str | None] = []
        for meeting in meetings:
            try:
                produced = await runner(meeting, provider)
            except ProviderError as exc:
                failed = True
                rows.append({"meeting": meeting["id"], "failed": True, "error_kind": str(exc.kind)})
                print(f"  {meeting['id']:<26} FAIL {exc.kind}")
                continue
            row = score(meeting, produced, totals)
            audit = score_meeting(meeting, produced)
            # Review step 4: the five global writer assertions, per meeting, in the report.
            from notes_assert import global_checks as _global_checks

            audit["global_checks"] = dict(_global_checks(produced))
            row.update(audit)
            row["windows"] = produced["windows"]
            row["lines"] = len(produced["lines"])
            # What a reader gets: sections written, bullets rendered.
            row["sections"] = len(produced.get("sections") or [])
            row["bullets"] = sum(1 for ln in produced["lines"] if ln.get("kind") == "bullet")
            # N2: the form a writing profile changes.
            row["summary_sentences"] = sum(
                1 for ln in produced["lines"] if ln.get("kind") == "summary"
            )
            row["topic_sections"] = sum(
                1 for s in produced.get("sections") or [] if s.get("role") == "topics"
            )
            stats = produced.get("stats") or {}
            row["stats"] = {k: stats[k] for k in _STAT_KEYS if k in stats}
            if judge_ok:
                try:
                    await judge(
                        produced,
                        judge_provider,
                        judge_totals,
                        totals,
                        language=meeting.get("language", "en"),
                        meeting_id=meeting["id"],
                    )
                except Exception as exc:  # noqa: BLE001
                    judge_ok = False
                    print(f"  judge failed ({type(exc).__name__}); column will be null")
            rows.append(row)
            audit_rows.append(audit)
            if save_notes is not None and run_index == 0:
                save_note(save_notes, meeting["id"], produced.get("note_text", ""))
            types.append(meeting.get("recording_type") or meeting.get("meeting_type"))
            print(
                f"  {meeting['id']:<26} {row['seconds']:6.1f}s  windows={row['windows']} "
                f"lines={row['lines']} actions={row.get('actions', 0)} "
                f"decisions={row.get('decisions', 0)}"
                + (
                    f"  missed key facts {row['key_facts_missed']}"
                    if row["key_facts_missed"]
                    else ""
                )
            )
        hours = totals.audio_seconds / 3600.0
        summary = summarise(totals, hours)
        # Cost at config/model_costs.yaml's rates, per meeting-hour.
        summary.update(cost_summary(resolved.name, totals, hours))
        summary.update(aggregate(audit_rows, types=types))
        # Time per meeting-hour, p95.
        per_hour = sorted(
            r["seconds"] / (audio_seconds(m) / 3600)
            for r, m in zip(rows, meetings, strict=False)
            if not r.get("failed") and r.get("seconds") is not None and audio_seconds(m) > 0
        )
        summary["seconds_per_meeting_hour_p95"] = (
            round(per_hour[min(len(per_hour) - 1, int(0.95 * len(per_hour)))], 1)
            if per_hour
            else None
        )
        summary["meetings_scored"] = len(audit_rows)
        scored = [r for r in rows if not r.get("failed")]
        for key in ("summary_sentences", "sections", "topic_sections"):
            summary[f"{key}_mean"] = (
                round(sum(r.get(key, 0) for r in scored) / len(scored), 2) if scored else None
            )
        summary["meetings_failed"] = sum(1 for r in rows if r.get("failed"))
        if judge_provider is not None:
            summary.update(
                judge_totals.summary()
                if judge_ok
                else {
                    "judge_unsupported_rate": None,
                    "judge_problems": None,
                    "deterministic_vs_judge_disagreement": None,
                }
            )
        if judge_lines is not None and judge_ok:
            save_judge_lines(judge_lines, run_index + 1, judge_totals.records)
        all_runs.append({"run": run_index + 1, "summary": summary, "meetings": rows})
        print(f"  run {run_index + 1}: " + json.dumps(summary))

    await provider.aclose()
    if judge_provider is not None:
        await judge_provider.aclose()
    first_build = next(
        (
            m["stats"]["build"]
            for r in all_runs
            for m in r["meetings"]
            if m.get("stats", {}).get("build")
        ),
        None,
    )
    print(f"build: {first_build}")
    report = {
        "build": first_build,
        "arm": arm,
        "backend": resolved.name,
        "model_id": resolved.model_id,
        "processor": resolved.processor.model_dump() if resolved.processor else None,
        "judge_model_id": judge_model,
        "corpus": str(corpus.relative_to(REPO)) if corpus.is_relative_to(REPO) else corpus.name,
        "context_window": resolved.caps.context_window,
        "label": label,
        "meetings": len(meetings),
        "runs": all_runs,
        # B2 T1: language × family cells over every run.
        "by_cell": cell_rollup(all_runs),
        # docs/eval/error-taxonomy.md — which defect each metric measures.
        "metric_codes": {k: list(v) for k, v in METRIC_CODES.items()},
    }
    path = write_report(
        f"notes-{arm}",
        resolved.name,
        report,
        suffix=f"-{label}" if label else "",
        allow_stale=allow_stale,
    )
    print(f"wrote {path}")
    # A hallucinated quote is a failed run, not a lower score.
    hallucinated = any(m.get("hallucinated_quote") for r in all_runs for m in r["meetings"])
    return EXIT_FAILED if (hallucinated or failed) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--arm", choices=list(ARMS), default="single_pass")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--runs", type=int, default=1, help="repeat for variance (the bake-off uses 3)")
    ap.add_argument("--judge", default=None, help="backend for the model-judge column (eval only)")
    ap.add_argument(
        "--save-notes",
        type=Path,
        default=None,
        help="write each note's text here for blind rating (must be under scripts/eval/local/)",
    )
    ap.add_argument(
        "--f2-baseline",
        type=Path,
        default=REPO / "docs" / "eval" / "notes-baseline-pipeline.json",
        help="pre-F2 report whose key_fact_recall the F2 recall gate compares against",
    )
    ap.add_argument(
        "--judge-lines",
        type=Path,
        default=None,
        help="append every judged line (ratio, rules, verdict) as JSONL for "
        "support_calibration.py (must be under scripts/eval/local/)",
    )
    ap.add_argument(
        "--sq1-baseline",
        type=Path,
        default=None,
        help="SQ1 report of the same arm: SQ2's unsupported gate may not exceed its rate",
    )
    ap.add_argument(
        "--label",
        default=None,
        help="suffix for the report file name (the local bake-off writes one report per candidate)",
    )
    ap.add_argument(
        "--allow-stale",
        action="store_true",
        help="Task 4: write the report although the engine that ran is not this checkout",
    )
    args = ap.parse_args()
    sys.exit(
        asyncio.run(
            main(
                args.arm,
                args.backend,
                args.corpus,
                args.runs,
                args.judge,
                args.save_notes,
                args.f2_baseline,
                args.judge_lines,
                args.label,
                args.sq1_baseline,
                allow_stale=args.allow_stale,
            )
        )
    )
