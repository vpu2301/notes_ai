#!/usr/bin/env python3
"""Blind pairwise rating: our engine against the one-prompt baseline
(Summary Engine v2, Q4 T7).

    # 1. both arms, notes saved locally (gitignored)
    make eval-notes BACKEND=dev_mac ARM=pipeline    CORPUS=… SAVE=scripts/eval/local/notes-pipeline
    make eval-notes BACKEND=dev_mac ARM=single_pass CORPUS=… SAVE=scripts/eval/local/notes-single
    # 2. the sheets
    python scripts/eval/notes_pairs.py build --a scripts/eval/local/notes-pipeline \\
        --b scripts/eval/local/notes-single --corpus … --out scripts/eval/local/pairs-2026-10-01
    # 3. three raters fill ratings.csv; then
    python scripts/eval/notes_pairs.py score scripts/eval/local/pairs-…/ratings.csv \\
        scripts/eval/local/pairs-…/key.csv --corpus …

``build`` writes one Markdown file per pair — the transcript, the gold
facts, and the two notes as "Note L" and "Note R" in a random order — plus
``sheet.csv`` for the raters and ``key.csv`` (which arm is left) kept apart
from it. Everything stays under ``scripts/eval/local/``: the notes and the
transcripts are content.

``score`` reads the raters' ``ratings.csv`` (``pair_id, rater, preferred
[L|R|tie], accuracy, completeness, usefulness, readability`` — scores 1–5 —
and, since the F3 amendment after r03 (§2.10), ``overview_L, overview_R``:
the overview question answered for each note, yes/partly/no) and prints the pipeline's preference rate with a 95 % Wilson interval,
per recording type and language, and inter-rater agreement. It writes
numbers only to ``docs/eval/notes-pairs-<date>.json``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DOCS_EVAL, REPO  # noqa: E402

LOCAL = REPO / "scripts" / "eval" / "local"
SCORES = ("accuracy", "completeness", "usefulness", "readability")
PIPELINE = "pipeline"
# F3 amendment §2.10 — one question on the overview alone, asked of both
# notes of a pair (the rater does not know which is ours). Gate: "yes" for
# our notes on ≥ 90 % of answers on v2.
OVERVIEW_QUESTION = (
    "From the top two paragraphs only: can you say what this recording is, "
    "who speaks, and what it covers? (yes / partly / no)"
)
OVERVIEW_ANSWERS = ("yes", "partly", "no")
OVERVIEW_GATE = 0.9


def _local(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(LOCAL.resolve()):
        raise SystemExit(f"{path}: pairs live under {LOCAL} (gitignored), not in the repo")
    return resolved


def _meetings(corpus: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(corpus.glob("*.json")):
        if path.name.endswith(".assertions.json"):
            continue
        data = json.loads(path.read_text("utf-8"))
        if "transcript" in data:
            out[data["id"]] = data
    return out


def _role_headings() -> frozenset[str]:
    """The fixed-role section headings in every language (decisions, action
    items, …) — not topics."""
    engine = REPO / "services" / "note-service" / "src"
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    from note_service.domain.meeting_doc.render import ROLE_LABELS

    return frozenset(label.casefold() for table in ROLE_LABELS.values() for label in table.values())


def topic_lines(note: str, arm: str = PIPELINE) -> str:
    """F2's blind round rates topic bullets only. From our note: every line
    under a heading that is not a fixed role (sub-points included); with no
    topic headings, the opening block's bullets. The baseline has no topics:
    its first paragraph — the points it chose to make — as bullets."""
    if arm != PIPELINE:
        first = note.strip().split("\n\n", 1)[0]
        return "\n".join(
            ln if ln.lstrip().startswith("- ") else f"- {ln.strip()}"
            for ln in first.splitlines()
            if ln.strip()
        )
    roles = _role_headings()
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in note.splitlines():
        if line.startswith("## "):
            blocks.append((line[3:].strip(), []))
        elif line.strip():
            blocks[-1][1].append(line.rstrip())
    topics = [
        (title, lines)
        for title, lines in blocks
        if title and title.casefold() not in roles and lines
    ]
    if topics:
        return "\n\n".join(f"## {title}\n" + "\n".join(lines) for title, lines in topics)
    return "\n".join(ln for ln in blocks[0][1] if ln.lstrip().startswith("- "))


def build(a: Path, b: Path, corpus: Path, out: Path, *, seed: int = 0, section: str = "all") -> int:
    """One pair per meeting both arms wrote a note for. ``a`` is the
    pipeline, ``b`` the baseline; which one is left is random, and only
    ``key.csv`` knows."""
    out = _local(out)
    out.mkdir(parents=True, exist_ok=True)
    meetings = _meetings(corpus)
    rng = random.Random(seed)
    ids = sorted(m for m in meetings if (a / f"{m}.md").is_file() and (b / f"{m}.md").is_file())
    sheet: list[list[str]] = [
        ["pair_id", "rater", "preferred", *SCORES, "overview_L", "overview_R"]
    ]
    key: list[list[str]] = [["pair_id", "meeting_id", "left", "right"]]
    for n, meeting_id in enumerate(ids, 1):
        pair_id = f"p{n:03d}"
        notes = {PIPELINE: (a / f"{meeting_id}.md").read_text("utf-8"),
                 "single_pass": (b / f"{meeting_id}.md").read_text("utf-8")}  # fmt: skip
        if section == "topics":
            notes = {arm: topic_lines(text, arm) for arm, text in notes.items()}
        left, right = (PIPELINE, "single_pass") if rng.random() < 0.5 else ("single_pass", PIPELINE)
        meeting = meetings[meeting_id]
        transcript = "\n".join(
            f"[{t['t_start_ms'] // 60000:02d}:{t['t_start_ms'] // 1000 % 60:02d}] "
            f"{t['speaker']}: {t['text']}"
            for t in meeting["transcript"]
        )
        facts = "\n".join(f"- {f}" for f in meeting.get("gold", {}).get("key_facts", []))
        (out / f"{pair_id}.md").write_text(
            f"# Pair {pair_id}\n\n## Transcript\n\n{transcript}\n\n"
            f"## What the note should carry\n\n{facts}\n\n"
            f"## Note L\n\n{notes[left]}\n\n## Note R\n\n{notes[right]}\n\n"
            f"## Overview question (each note: overview_L, overview_R)\n\n{OVERVIEW_QUESTION}\n",
            encoding="utf-8",
        )
        sheet.append([pair_id, "", "", "", "", "", "", "", ""])
        key.append([pair_id, meeting_id, left, right])
    for name, rows in (("sheet.csv", sheet), ("key.csv", key)):
        with (out / name).open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
    print(f"{len(ids)} pairs in {out}")
    return 0


def wilson(wins: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson score interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def score(ratings_path: Path, key_path: Path, corpus: Path | None = None) -> dict[str, Any]:
    with key_path.open(encoding="utf-8") as handle:
        key = {row["pair_id"]: row for row in csv.DictReader(handle)}
    with ratings_path.open(encoding="utf-8") as handle:
        ratings = [row for row in csv.DictReader(handle) if row.get("preferred")]
    meetings = _meetings(corpus) if corpus else {}

    def winner(row: dict[str, str]) -> str:
        pick = row["preferred"].strip().upper()
        if pick == "TIE":
            return "tie"
        side = key[row["pair_id"]]["left" if pick == "L" else "right"]
        return "pipeline" if side == PIPELINE else "baseline"

    def rate(rows: list[dict[str, str]]) -> dict[str, Any]:
        outcomes = [winner(r) for r in rows]
        wins = outcomes.count("pipeline") + 0.5 * outcomes.count("tie")
        n = len(outcomes)
        low, high = wilson(wins, n)
        return {"n": n, "preference": (wins / n) if n else None, "ci95": [low, high]}

    groups: dict[str, dict[str, list[dict[str, str]]]] = {
        "type": defaultdict(list),
        "language": defaultdict(list),
    }
    for row in ratings:
        meeting = meetings.get(key[row["pair_id"]]["meeting_id"], {})
        groups["type"][
            meeting.get("recording_type") or meeting.get("meeting_type") or "unlabelled"
        ].append(row)
        groups["language"][meeting.get("language", "unknown")].append(row)

    # Inter-rater agreement: share of rater pairs that picked the same side.
    by_pair: dict[str, list[str]] = defaultdict(list)
    for row in ratings:
        by_pair[row["pair_id"]].append(winner(row))
    agree = total = 0
    for picks in by_pair.values():
        for x, y in combinations(picks, 2):
            total += 1
            agree += x == y

    def means(arm: str) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for field in SCORES:
            # Scores are for the note the rater PREFERRED; averaged per arm.
            values = [float(r[field]) for r in ratings if r.get(field) and winner(r) == arm]
            out[field] = (sum(values) / len(values)) if values else None
        return out

    def overview() -> dict[str, Any]:
        answers: dict[str, list[str]] = {"pipeline": [], "baseline": []}
        for row in ratings:
            for side in ("L", "R"):
                answer = (row.get(f"overview_{side}") or "").strip().casefold()
                if answer not in OVERVIEW_ANSWERS:
                    continue
                arm = key[row["pair_id"]]["left" if side == "L" else "right"]
                answers["pipeline" if arm == PIPELINE else "baseline"].append(answer)
        out: dict[str, Any] = {}
        for arm, given in answers.items():
            n = len(given)
            yes = given.count("yes")
            out[arm] = {
                "n": n,
                **{a: (given.count(a) / n) if n else None for a in OVERVIEW_ANSWERS},
                "ci95_yes": list(wilson(yes, n)),
            }
        ours = out["pipeline"]
        out["gate"] = OVERVIEW_GATE
        out["gate_met"] = None if not ours["n"] else ours["yes"] >= OVERVIEW_GATE
        return out

    return {
        "pairs": len(by_pair),
        "raters": len({r["rater"] for r in ratings}),
        "ratings": len(ratings),
        "overall": rate(ratings),
        "by_type": {k: rate(v) for k, v in sorted(groups["type"].items())},
        "by_language": {k: rate(v) for k, v in sorted(groups["language"].items())},
        "inter_rater_agreement": (agree / total) if total else None,
        "scores_when_preferred": {"pipeline": means("pipeline"), "baseline": means("baseline")},
        "overview": overview(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--a", type=Path, required=True, help="pipeline notes folder")
    b.add_argument("--b", type=Path, required=True, help="single-pass notes folder")
    b.add_argument("--corpus", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument(
        "--section",
        choices=["all", "topics"],
        default="all",
        help="rate whole notes, or topic bullets only (F2's readability round)",
    )
    s = sub.add_parser("score")
    s.add_argument("ratings", type=Path)
    s.add_argument("key", type=Path)
    s.add_argument("--corpus", type=Path, default=None)
    s.add_argument("--write", action="store_true", help="write docs/eval/notes-pairs-<date>.json")
    args = parser.parse_args(argv)
    if args.command == "build":
        return build(args.a, args.b, args.corpus, args.out, seed=args.seed, section=args.section)
    result = score(args.ratings, args.key, args.corpus)
    print(json.dumps(result, indent=2))
    if args.write:
        DOCS_EVAL.mkdir(parents=True, exist_ok=True)
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        path = DOCS_EVAL / f"notes-pairs-{date}.json"
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
