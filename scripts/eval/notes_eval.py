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

Summary Engine v2 (Q1) adds every metric of the 2026-09-22 audit
(``notes_scoring.py``), an optional model-judge column (``--judge``,
eval only) and a loud failure when the engine sees no transcript: until
Q1 the harness emitted ``turns[].text`` while the engine reads
``turns[].paragraphs``, so the pipeline arm only ever scored an empty
transcript.

The corpus is data, never code: `--corpus` points at a directory of JSON
files. The committed one is synthetic (no real people); the real gold set
lives in the eval bucket under the consent register and is never in git.
Nothing here prints a transcript, a quote or a name.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, load_registry, write_report  # noqa: E402
from notes_scoring import (  # noqa: E402, F401 — re-exported for the harness tests
    COMPOSED,
    MATCH_THRESHOLD,
    STOP,
    aggregate,
    best_match,
    f2_gates,
    f3_gates,
    overlap,
    score_meeting,
    support,
    words,
)

DEFAULT_CORPUS = REPO / "tests" / "fixtures" / "eval" / "notes"
ENGINE_SRC = REPO / "services" / "note-service" / "src"
TEMPLATES = REPO / "infra" / "seeds" / "templates"
# A fixture without `recorded_on` is anchored here, so relative dates in
# the synthetic set resolve the same way on every machine and every day.
DEFAULT_RECORDED_ON = "2026-01-15"

# Exit codes the nightly job reads.
EXIT_FAILED = 1  # a hallucinated quote, or a meeting the model could not finish
EXIT_BLIND = 2  # the engine saw no transcript — the bug that hid every number
EXIT_NO_CORPUS = 3
# Q4 entity tier (b): off, as in production, unless measured on purpose
# (`--entity-model-tier`); its precision is its own column either way.
ENTITY_MODEL_TIER = False


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
            }
            for t in meeting["transcript"]
        ],
    }
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
    """``{section_key: role}`` from the seed template, through the same
    ``TemplateDefinition`` + ``roles.role_map`` the worker's ``_role_map``
    uses — minus the database."""
    from note_service.domain.meeting_doc import roles
    from template_models import TemplateDefinition

    path = TEMPLATES / f"{code}.json"
    if not path.is_file():
        return {}
    definition = TemplateDefinition.model_validate(json.loads(path.read_text("utf-8")))
    return dict(roles.role_map(definition))


class EngineBlindError(RuntimeError):
    """A non-empty transcript produced zero windows."""


def _fact_dict(fact: Any) -> dict[str, Any]:
    return {
        "item_key": fact.item_key,
        "kind": fact.kind,
        "text": fact.text,
        "quote": fact.quote,
        "turn": fact.turn,
        "certainty": getattr(fact, "certainty", None),
        "owner": fact.owner_label,
        "due_text": fact.due_text,
        "attributed_to": getattr(fact, "attributed_to", None),
        "corrections": [
            [c.surface, c.canonical, c.source] for c in getattr(fact, "corrections", ())
        ],
        "start_ms": fact.start_ms,
        "end_ms": fact.end_ms,
        "window_index": fact.window_index,
        # F3 — the verified payloads.
        "figure": fact.figure.payload() if getattr(fact, "figure", None) else None,
        "person": (
            {
                "name": fact.person.name,
                "role": fact.person.role,
                "organisation": fact.person.organisation,
            }
            if getattr(fact, "person", None)
            else None
        ),
    }


# ── the two arms ────────────────────────────────────────────────────


async def run_pipeline(meeting: dict[str, Any], provider: Any) -> dict[str, Any]:
    """The engine, exactly as the worker runs it: the result view the
    worker snapshots, the template's roles, the meeting's date and the
    ASR's name candidates."""
    from types import SimpleNamespace

    from note_service.domain.glossary import Term
    from note_service.domain.meeting_doc import pipeline, types, windows
    from note_service.jobs.generate_note import _recording_type

    language = meeting.get("language", "en")
    meeting_type = meeting.get("meeting_type") or "auto"
    gold = meeting.get("gold") or {}
    glossary = tuple(
        Term(t["term"], t.get("kind", "person"), tuple(t.get("heard_as") or ()))
        for t in gold.get("glossary") or []
    )
    # The note's template, as creation would have picked it for this type.
    template_family = types.family_for_type(meeting_type)
    result = as_asr_result(meeting)
    started = time.monotonic()
    # Q3: the worker's own decision — the author's type, a specific
    # template, or the classifier on the opening windows (a model call).
    turns = windows.turns_from_result(result)
    built = windows.build_windows(turns)
    recording_type, source = await _recording_type(
        provider,
        meeting=SimpleNamespace(meeting_type=meeting_type, calendar_context={}),
        template_family=template_family,
        built=built,
        turns=turns,
        language=language,
    )
    document = await pipeline.run(
        result,
        provider=provider,
        role_by_key=role_map(template_code(template_family, language)),
        language=language,
        meeting_date=date.fromisoformat(meeting.get("recorded_on") or DEFAULT_RECORDED_ON),
        # Q4: the people the worker knows (_known_names) — candidates, the
        # roster's names and the glossary's persons — and the glossary.
        name_candidates=frozenset(
            {*(result.get("name_candidates") or ()), *(gold.get("speakers") or {}).values()}
            | {t.term for t in glossary if t.kind == "person"}
        ),
        glossary=glossary,
        entity_model_tier=ENTITY_MODEL_TIER,
        family=types.family_for_recording_type(recording_type),
        built=built,
        recording_type=recording_type,
        recording_type_source=source,
    )
    if document.windows_total == 0 and any(t["text"].strip() for t in meeting["transcript"]):
        raise EngineBlindError(meeting["id"])
    titles = {s.section_key: s.title for s in document.sections}
    return {
        "seconds": time.monotonic() - started,
        "lines": [
            {
                "section_key": key,
                # F2 — which topic a line sits under, and whether it is a
                # sub-point, for the r02 checklist.
                "section_title": titles.get(key),
                "parent": bool(getattr(line, "parent", None)),
                "kind": line.kind,
                "text": line.text,
                "fact_ids": list(line.fact_ids),
                "dates": [m.iso() for m in line.dates],
            }
            for key, line in document.lines
        ],
        # Q3: what the engine resolved each spoken date to.
        "dates": list(
            {
                (m.text, m.iso()): {"text": m.text, "resolved": m.iso()}
                for _key, line in document.lines
                for m in line.dates
            }.values()
        ),
        "facts": [_fact_dict(f) for f in document.facts],
        "actions": [
            f
            for f in document.facts
            if f.kind in ("action", "commitment_ours", "commitment_theirs")
        ],
        "decisions": [f for f in document.facts if f.kind == "decision"],
        "quotes": [(f.quote, f.turn) for f in document.facts],
        "windows": document.windows_total,
        "windows_failed": document.windows_failed,
        "stats": dict(document.stats),
        "brief": dict(document.brief),
        "noise_ranges": [list(r) for r in document.noise_ranges],
        "evidence": "facts",
        # The note as a reader sees it — only ever written to local disk
        # (--save-notes, for blind rating), never into a report.
        "note_text": "\n\n".join(
            (f"## {s.title}\n{s.text}" if s.title else s.text) for s in document.sections
        ),
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

    # The invariant: every quote is verbatim, and from the turn claimed —
    # compared the way the engine compares (`verify.normalise_quote`, an
    # echoed "[3] Anna (00:12): " header removed). Comparing raw lowercase
    # text called every quote with a comma the ASR placed differently a
    # hallucination, and failed runs whose quotes were all real.
    from note_service.domain.meeting_doc.verify import normalise_quote, strip_turn_header

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
    "was said. Otherwise name the problem. Judge only; do not rewrite."
)


@dataclass
class JudgeTotals:
    judged: int = 0
    unsupported: int = 0
    disagree: int = 0
    problems: Counter = field(default_factory=Counter)

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
    produced: dict[str, Any], provider: Any, totals: JudgeTotals, usage: Totals
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
        deterministic = support(line["text"], [f"{f['text']} {f['quote']}" for f in cited])
        totals.disagree += 1 if deterministic != supported else 0


_STAT_KEYS = (
    "facts_kept",
    "facts_dropped_quote",
    "facts_dropped_noise",
    "facts_dropped_example",
    "example_echo_dropped",
    "noise_passages",
    "facts_downgraded",
    "numbers_removed",
    "facts_after_merge",
    # Q2
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
    # Q3
    "redundant_lines",
    "lines_total",
    "recording_type",
    "recording_type_source",
)


LOCAL = REPO / "scripts" / "eval" / "local"


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
) -> int:
    sys.path.insert(0, str(ENGINE_SRC))
    from models import ProviderError, build_chat_provider

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
    provider = build_chat_provider(resolved)
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

    runner = run_pipeline if arm == "pipeline" else run_single_pass
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
            except EngineBlindError:
                print("engine saw no transcript", file=sys.stderr)
                print(f"  {meeting['id']}: 0 windows for a non-empty transcript", file=sys.stderr)
                await provider.aclose()
                return EXIT_BLIND
            except ProviderError as exc:
                failed = True
                rows.append({"meeting": meeting["id"], "failed": True, "error_kind": str(exc.kind)})
                print(f"  {meeting['id']:<26} FAIL {exc.kind}")
                continue
            row = score(meeting, produced, totals)
            audit = score_meeting(meeting, produced)
            row.update(audit)
            row["windows"] = produced["windows"]
            row["lines"] = len(produced["lines"])
            stats = produced.get("stats") or {}
            row["stats"] = {k: stats[k] for k in _STAT_KEYS if k in stats}
            if judge_ok:
                try:
                    await judge(produced, judge_provider, judge_totals, totals)
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
        summary.update(aggregate(audit_rows, types=types))
        summary["meetings_scored"] = len(audit_rows)
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
        all_runs.append({"run": run_index + 1, "summary": summary, "meetings": rows})
        print(f"  run {run_index + 1}: " + json.dumps(summary))

    await provider.aclose()
    if judge_provider is not None:
        await judge_provider.aclose()
    report = {
        "arm": arm,
        "backend": resolved.name,
        "model_id": resolved.model_id,
        "processor": resolved.processor.model_dump() if resolved.processor else None,
        "judge_model_id": judge_model,
        "corpus": str(corpus.relative_to(REPO)) if corpus.is_relative_to(REPO) else corpus.name,
        "meetings": len(meetings),
        "runs": all_runs,
    }
    if arm == "pipeline":
        from note_service.domain.meeting_doc.prompts import PROMPT_VERSION

        report["prompt_version"] = PROMPT_VERSION
        # F2 acceptance: no copied, chatter or first-person line, and recall
        # within a point of the pre-F2 report.
        baseline_recall = None
        if f2_baseline is not None and f2_baseline.is_file():
            baseline = json.loads(f2_baseline.read_text("utf-8"))
            baseline_recall = baseline["runs"][-1]["summary"].get("key_fact_recall")
        gates = f2_gates(all_runs[-1]["summary"], baseline_recall=baseline_recall)
        gates.update(f3_gates(all_runs[-1]["summary"]))
        report["f2_gates"] = gates
        for name, ok in gates.items():
            print(f"  F2 gate {name}: {'PASS' if ok else 'FAIL'}")
    path = write_report(f"notes-{arm}", resolved.name, report)
    print(f"wrote {path}")
    # A hallucinated quote is a failed run, not a lower score: the whole
    # design says a fact without verbatim words does not reach the page.
    hallucinated = any(m.get("hallucinated_quote") for r in all_runs for m in r["meetings"])
    return EXIT_FAILED if (hallucinated or failed) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--arm", choices=["pipeline", "single_pass"], default="pipeline")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--runs", type=int, default=1, help="repeat for variance (the bake-off uses 3)")
    ap.add_argument("--judge", default=None, help="backend for the model-judge column (eval only)")
    ap.add_argument(
        "--entity-model-tier",
        action="store_true",
        help="let the model respell unknown names (measures model_tier_precision)",
    )
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
    args = ap.parse_args()
    ENTITY_MODEL_TIER = args.entity_model_tier
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
            )
        )
    )
