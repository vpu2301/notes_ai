#!/usr/bin/env python3
"""Sprint P3 — the scoring harness on the notes the writer stores (or writes from fixtures).

    make score-notes NOTE_IDS=<uuid|code>[,…] [RUNS=3] [JUDGE=dev_mac] [HANDSCORE=dir] [REFERENCES=dir]
    make score-notes-fixtures BACKEND=dev_mac [CORPUS=tests/fixtures/eval/notes] [RUNS=1]

Per generation: the hand-table scorer (``notes_scoring.best_match`` on folded text,
uncalibrated), the judge (unsupported-line rate: each cited line against the turns it
cites), the structural metrics (sections, words per minute, bullets with cites, bad and
nearest cites, lines without a reference, the holder named per section, dates later than
the recording, identifiers altered, the check call's marks) and the comparison to a
reference note where one exists (internal only). Output: one Markdown table per run under
``docs/eval/writer-v2-<date>.md`` (+ a JSON sidecar), numbers only — never a line of a
note, a quote or a name.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, git_sha  # noqa: E402
from notes_eval import (  # noqa: E402
    JUDGE_SCHEMA,
    JUDGE_SYSTEM,
    Paced,
    as_asr_result,
    load_registry,
)
from notes_gold import fact_text  # noqa: E402
from notes_scoring import best_match  # noqa: E402

ENGINE_SRC = REPO / "services" / "note-service" / "src"
sys.path.insert(0, str(ENGINE_SRC))

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
DOCS_EVAL = REPO / "docs" / "eval"
MATCH = 0.5
# "Name:" at the start of a line, or a reporting verb: the holder is named.
_HOLDER = re.compile(
    r"^[\w'’ .-]{2,40}:\s|\b(said|says|sagte|sagt|meint|warnt|erklärt|сказав|сказала|каже)\b",
    re.IGNORECASE,
)
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b")
_NUMBER = re.compile(r"\d[\d.,:/-]*\d|\d")


@dataclass(slots=True)
class Scored:
    code: str
    run: int
    generation_id: str
    language: str
    metrics: dict[str, Any] = field(default_factory=dict)


# ── Metrics ─────────────────────────────────────────────────────────────


def _digits(text: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in _NUMBER.findall(text) if re.sub(r"\D", "", n)}


def _dates_after(text: str, recorded_on: date | None) -> int:
    if recorded_on is None:
        return 0
    found: list[date] = []
    for y, m, d in _ISO.findall(text):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    for d, m, y in _DMY.findall(text):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return sum(1 for f in found if f > recorded_on)


def structure(
    text: str, items: list[dict[str, Any]], stats: dict[str, Any], recorded_on: date | None
) -> dict[str, Any]:
    """The shape of a note, as numbers. ``items`` are the stored rows (or the rows a
    fixture run produced): kind, section_key, text, cites, cite_nearest, payload, check."""
    bullets = [i for i in items if i.get("kind") in ("bullet", "vote", "claim", "table_row")]
    cited = [i for i in items if i.get("cites")]
    sections: dict[str, list[dict[str, Any]]] = {}
    for i in items:
        sections.setdefault(str(i.get("section_key")), []).append(i)
    holder_named = sum(
        1
        for rows in sections.values()
        if any(_HOLDER.search(str(r.get("text") or "")) for r in rows)
    )
    altered = 0
    for i in cited:
        payload = i.get("payload") or {}
        turns = payload.get("turns") if isinstance(payload, dict) else None
        evidence = " ".join(str(t.get("text") or "") for t in (turns or [])) or str(
            i.get("quote") or ""
        )
        if not evidence:
            continue
        have = _digits(evidence)
        altered += sum(
            1 for n in _digits(str(i.get("text") or "")) if n not in have and len(n) >= 2
        )
    minutes = float(stats.get("speech_minutes") or 0.0)
    if not minutes and cited:
        minutes = max(int(i.get("end_ms") or 0) for i in cited) / 60_000
    words = len(text.split())
    check = stats.get("check") if isinstance(stats.get("check"), dict) else None
    return {
        "words": words,
        "speech_minutes": round(minutes, 1),
        "words_per_minute": round(words / minutes, 1) if minutes else None,
        "sections": len(sections),
        "items": len(items),
        "bullets": len(bullets),
        "bullets_cited": sum(1 for i in bullets if i.get("cites")),
        "cited_share": round(sum(1 for i in bullets if i.get("cites")) / len(bullets), 3)
        if bullets
        else None,
        "no_reference": sum(1 for i in bullets if not i.get("cites")),
        "nearest_cites": sum(1 for i in items if i.get("cite_nearest")),
        "bad_cites": int(stats.get("bad_cites") or 0),
        "holder_named_sections": round(holder_named / len(sections), 3) if sections else None,
        "dates_after_recording": sum(
            _dates_after(str(i.get("text") or ""), recorded_on) for i in items
        ),
        "identifiers_altered": altered,
        "check_items": check.get("items") if check else None,
        "check_unsupported": check.get("unsupported") if check else None,
        "merge_failed": bool(stats.get("merge_failed")),
        "calls": stats.get("calls"),
        "latency_ms": stats.get("latency_ms"),
    }


def _lines(items: list[dict[str, Any]]) -> list[str]:
    return [str(i.get("text") or "") for i in items if str(i.get("text") or "").strip()]


def recall(facts: list[str], lines: list[str], language: str) -> dict[str, Any] | None:
    """The share of facts a line carries at ≥ ``MATCH`` of their words (uncalibrated)."""
    if not facts:
        return None
    hit = sum(1 for f in facts if best_match(f, lines, language)[1] >= MATCH)
    return {"facts": len(facts), "matched": hit, "recall": round(hit / len(facts), 3)}


def reference_lines(text: str) -> list[str]:
    """A reference note's claims: its bullets, else its sentences."""
    bullets = [
        re.sub(r"^\s*[-*•]\s*", "", ln).strip()
        for ln in text.splitlines()
        if re.match(r"^\s*[-*•]\s+", ln)
    ]
    if bullets:
        return bullets
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 4]


async def judge(items: list[dict[str, Any]], provider: Any, language: str) -> dict[str, Any]:
    """Each cited line against the turns it cites: the unsupported-line rate."""
    judged = unsupported = failed = 0
    for i in items:
        if not i.get("cites"):
            continue
        payload = i.get("payload") or {}
        turns = payload.get("turns") if isinstance(payload, dict) else None
        if not turns:
            turns = [
                {
                    "start_ms": i.get("start_ms", 0),
                    "speaker": i.get("speaker_name"),
                    "text": i.get("quote", ""),
                }
            ]
        listing = "\n".join(
            f'- said: "{t.get("text", "")}"' + (f" ({t['speaker']})" if t.get("speaker") else "")
            for t in turns
        )
        prompt = f"Line:\n{i['text']}\n\nFacts it cites:\n{listing}"
        try:
            answer = await provider.complete(
                prompt, JUDGE_SCHEMA, max_tokens=200, temperature=0.0, system=JUDGE_SYSTEM
            )
        except Exception:  # noqa: BLE001 — a failed call is a null, never a verdict
            failed += 1
            continue
        verdict = answer.json if isinstance(getattr(answer, "json", None), dict) else {}
        judged += 1
        unsupported += 0 if verdict.get("supported") else 1
    return {
        "judged": judged,
        "unsupported": unsupported,
        "unsupported_rate": round(unsupported / judged, 3) if judged else None,
        "failed_calls": failed,
    }


# ── Sources: stored notes, or fixtures written now ──────────────────────


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def stored(
    dsn: str, ids: list[str], *, runs: int, generation_ids: list[str] | None
) -> list[tuple[str, str, str, dict[str, Any], list[dict[str, Any]], date | None, str]]:
    """``(code, generation_id, text, stats, items, recorded_on, language)`` per generation."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    out = []
    try:
        if generation_ids:
            gens = await conn.fetch(
                """SELECT g.id, g.note_id, g.stats, g.text, n.code FROM note_generations g
                   JOIN notes n ON n.id = g.note_id
                   WHERE g.id::text = ANY($1) AND g.text IS NOT NULL ORDER BY n.code, g.created_at""",
                generation_ids,
            )
        else:
            notes = await conn.fetch(
                "SELECT id, code FROM notes WHERE id::text = ANY($1) OR code = ANY($1) ORDER BY code",
                ids,
            )
            gens = []
            for n in notes:
                gens.extend(
                    await conn.fetch(
                        """SELECT g.id, g.note_id, g.stats, g.text, $2::text AS code
                           FROM note_generations g WHERE g.note_id = $1
                           AND g.status IN ('complete', 'partial') AND g.text IS NOT NULL
                           ORDER BY g.created_at DESC LIMIT $3""",
                        n["id"],
                        n["code"],
                        runs,
                    )
                )
        for g in gens:
            rows = await conn.fetch(
                """SELECT kind, section_key, text, cites, cite_nearest, payload, quote,
                          start_ms, end_ms, speaker_name, "check", position
                   FROM note_generated_items WHERE generation_id = $1 ORDER BY position""",
                g["id"],
            )
            items = [
                {**dict(r), "payload": _json(r["payload"]), "cites": list(r["cites"] or [])}
                for r in rows
            ]
            started = await conn.fetchval(
                "SELECT started_at FROM note_meetings WHERE note_id = $1", g["note_id"]
            )
            stats = _json(g["stats"]) or {}
            out.append(
                (
                    str(g["code"]),
                    str(g["id"]),
                    str(g["text"]),
                    stats,
                    items,
                    started.date() if started else None,
                    str(stats.get("language") or "en"),
                )
            )
    finally:
        await conn.close()
    return out


async def from_fixtures(
    corpus: Path, ids: list[str] | None, *, provider: Any, runs: int, save: Path | None
) -> list[tuple[str, str, str, dict[str, Any], list[dict[str, Any]], date | None, str, list[str]]]:
    """Write each fixture's transcript with the writer, then score it like a stored note.
    The gold key facts stand in for the hand table."""
    from note_service.domain import note_markdown, transcript, writer
    from note_service.jobs import generate_note

    out = []
    files = sorted(corpus.glob("*.json"))
    for path in files:
        meeting = json.loads(path.read_text("utf-8"))
        if "transcript" not in meeting or (ids and meeting.get("id") not in ids):
            continue
        result = as_asr_result(meeting)
        turns = transcript.prepare_turns(
            transcript.turns_from_result(result), language=meeting.get("language", "en")
        ).turns
        recorded = (
            date.fromisoformat(meeting["recorded_on"]) if meeting.get("recorded_on") else None
        )
        for run in range(1, runs + 1):
            written = await writer.write(
                turns,
                provider=provider,
                language=meeting.get("language", "en"),
                recording_date=recorded,
                instruction_text=None,
                template_name=writer.template_name_for(
                    meeting.get("meeting_type"), None, chosen=False
                ),
            )
            parsed = note_markdown.parse(written.text, turns)
            rows = generate_note.item_rows(parsed, turns)
            stats = dict(written.stats)
            stats.update({"bad_cites": parsed.bad_cites, "sections": len(parsed.sections)})
            if save:
                folder = save / str(meeting["id"])
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"run{run}.md").write_text(written.text, "utf-8")
            facts = [fact_text(f) for f in (meeting.get("gold") or {}).get("key_facts") or []]
            out.append(
                (
                    str(meeting["id"]),
                    f"fixture-{run}",
                    written.text,
                    stats,
                    rows,
                    recorded,
                    str(meeting.get("language", "en")),
                    facts,
                )
            )
    return out


# ── Report ──────────────────────────────────────────────────────────────

COLUMNS = (
    ("words", "words"),
    ("words_per_minute", "w/min"),
    ("sections", "sections"),
    ("bullets", "bullets"),
    ("cited_share", "cited"),
    ("no_reference", "no ref"),
    ("nearest_cites", "nearest"),
    ("bad_cites", "bad cites"),
    ("holder_named_sections", "holder/section"),
    ("dates_after_recording", "dates>rec"),
    ("identifiers_altered", "ids altered"),
    ("check_unsupported", "check unsup"),
    ("hand_recall", "hand recall"),
    ("judge_unsupported_rate", "judge unsup"),
    ("reference_recall", "ref recall"),
)


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}" if value < 10 else f"{value:.0f}"
    return str(value)


def table(rows: list[Scored]) -> str:
    head = "| code | run | " + " | ".join(label for _k, label in COLUMNS) + " |"
    rule = "|" + "---|" * (len(COLUMNS) + 2)
    body = [
        f"| {r.code} | {r.run} | " + " | ".join(_cell(r.metrics.get(k)) for k, _l in COLUMNS) + " |"
        for r in rows
    ]
    return "\n".join([head, rule, *body])


def means(rows: list[Scored]) -> list[Scored]:
    by_code: dict[str, list[Scored]] = {}
    for r in rows:
        by_code.setdefault(r.code, []).append(r)
    out = []
    for code, group in by_code.items():
        metrics: dict[str, Any] = {}
        for key, _label in COLUMNS:
            values = [
                g.metrics.get(key) for g in group if isinstance(g.metrics.get(key), (int, float))
            ]
            metrics[key] = round(statistics.fmean(values), 3) if values else None
        out.append(
            Scored(
                code=code,
                run=len(group),
                generation_id="mean",
                language=group[0].language,
                metrics=metrics,
            )
        )
    return out


def write_report(rows: list[Scored], *, label: str, judge_backend: str | None) -> Path:
    DOCS_EVAL.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    suffix = f"-{label}" if label else ""
    md = DOCS_EVAL / f"writer-v2-{day}{suffix}.md"
    runs = sorted({r.run for r in rows}, key=str)
    parts = [
        f"# Writer v2 — scoring {day}{(' — ' + label) if label else ''}",
        "",
        f"Numbers only. git `{git_sha()}`, judge `{judge_backend or '—'}`, hand recall = "
        f"`best_match` ≥ {MATCH} on folded text (uncalibrated). `cited` = share of bullets "
        "with a transcript time; `holder/section` = share of sections naming a holder; "
        "`ids altered` = numbers in a line absent from the turns it cites; `check unsup` = "
        "the check call's marks (— when the call was off); `ref recall` = share of the "
        "reference note's lines found (internal).",
        "",
    ]
    for run in runs:
        parts += [f"## Run {run}", "", table([r for r in rows if r.run == run]), ""]
    if len(runs) > 1:
        parts += ["## Mean over runs (run column = runs counted)", "", table(means(rows)), ""]
    md.write_text("\n".join(parts), "utf-8")
    (md.with_suffix(".json")).write_text(
        json.dumps(
            {
                "date": day,
                "git": git_sha(),
                "judge": judge_backend,
                "rows": [
                    {
                        "code": r.code,
                        "run": r.run,
                        "generation_id": r.generation_id,
                        "language": r.language,
                        **r.metrics,
                    }
                    for r in rows
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        "utf-8",
    )
    return md


def _handscore(folder: Path | None, code: str) -> list[str]:
    if folder is None:
        return []
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except ValueError:
            continue
        if data.get("id") == code or path.stem == code:
            return [str(f.get("fact") or f.get("text") or "") for f in data.get("facts") or []]
    return []


def _reference(folder: Path | None, code: str) -> list[str]:
    if folder is None:
        return []
    for path in (folder / f"{code}.md", folder / f"{code}.txt"):
        if path.exists():
            return reference_lines(path.read_text("utf-8"))
    path = folder / f"{code}.json"
    if path.exists():
        data = json.loads(path.read_text("utf-8"))
        return [fact_text(f) for f in (data.get("gold") or data).get("key_facts") or []]
    return []


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--note-ids", default="", help="stored notes: uuids or codes, comma-separated")
    ap.add_argument("--generation-ids", default="", help="stored generations to score (uuids)")
    ap.add_argument(
        "--runs", type=int, default=1, help="newest N generations per note; fixtures: write N times"
    )
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--fixtures", type=Path, default=None, help="write and score a fixture corpus")
    ap.add_argument("--ids", default="", help="with --fixtures: only these meeting ids")
    ap.add_argument("--backend", default=None, help="with --fixtures: the writer's backend")
    ap.add_argument("--judge", default=None, help="backend for the judge column")
    ap.add_argument(
        "--handscore",
        type=Path,
        default=None,
        help="folder of hand tables (<code>.json or id field)",
    )
    ap.add_argument(
        "--references",
        type=Path,
        default=None,
        help="folder of reference notes (<code>.md|.json), internal",
    )
    ap.add_argument(
        "--save", type=Path, default=None, help="with --fixtures: save the written notes here"
    )
    ap.add_argument("--label", default="", help="report suffix")
    args = ap.parse_args(argv)

    judge_provider = None
    registry = None
    if args.judge or args.fixtures:
        from models import build_chat_provider

        registry = load_registry()
    if args.judge and registry is not None:
        try:
            judge_provider = Paced(
                build_chat_provider(registry.backend(args.judge, expect_kind="chat"))
            )
        except Exception as exc:  # noqa: BLE001
            print(f"judge unavailable ({type(exc).__name__}); column will be null")

    scored: list[Scored] = []
    if args.fixtures:
        if not args.backend or registry is None:
            print("--fixtures needs --backend", file=sys.stderr)
            return 2
        provider = Paced(build_chat_provider(registry.backend(args.backend, expect_kind="chat")))
        ids = [i for i in args.ids.split(",") if i]
        for code, gen, text, stats, items, recorded, language, facts in await from_fixtures(
            args.fixtures, ids or None, provider=provider, runs=args.runs, save=args.save
        ):
            metrics = structure(text, items, stats, recorded)
            lines = _lines(items)
            hand = recall(facts, lines, language)
            metrics["hand_recall"] = hand["recall"] if hand else None
            metrics["hand_facts"] = hand["facts"] if hand else None
            if judge_provider is not None:
                verdict = await judge(items, judge_provider, language)
                metrics["judge_unsupported_rate"] = verdict["unsupported_rate"]
                metrics["judge_judged"] = verdict["judged"]
            run = int(gen.rsplit("-", 1)[-1])
            scored.append(
                Scored(code=code, run=run, generation_id=gen, language=language, metrics=metrics)
            )
    else:
        ids = [i for i in args.note_ids.split(",") if i]
        gen_ids = [i for i in args.generation_ids.split(",") if i]
        if not ids and not gen_ids:
            ap.error("--note-ids, --generation-ids or --fixtures")
        counters: dict[str, int] = {}
        for code, gen, text, stats, items, recorded, language in await stored(
            args.dsn, ids, runs=args.runs, generation_ids=gen_ids or None
        ):
            counters[code] = counters.get(code, 0) + 1
            metrics = structure(text, items, stats, recorded)
            lines = _lines(items)
            hand = recall(_handscore(args.handscore, code), lines, language)
            metrics["hand_recall"] = hand["recall"] if hand else None
            metrics["hand_facts"] = hand["facts"] if hand else None
            ref = recall(_reference(args.references, code), lines, language)
            metrics["reference_recall"] = ref["recall"] if ref else None
            metrics["reference_lines"] = ref["facts"] if ref else None
            if judge_provider is not None:
                verdict = await judge(items, judge_provider, language)
                metrics["judge_unsupported_rate"] = verdict["unsupported_rate"]
                metrics["judge_judged"] = verdict["judged"]
            scored.append(
                Scored(
                    code=code,
                    run=counters[code],
                    generation_id=gen,
                    language=language,
                    metrics=metrics,
                )
            )
    if not scored:
        print("nothing to score", file=sys.stderr)
        return 3
    path = write_report(scored, label=args.label, judge_backend=args.judge)
    print(f"wrote {path.relative_to(REPO)} ({len(scored)} generations)")
    print(table(scored))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
