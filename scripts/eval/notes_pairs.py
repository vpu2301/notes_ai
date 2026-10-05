#!/usr/bin/env python3
"""Blind pairwise rating of our engine against the one-prompt baseline, plus the
document standard's blind rubric (``rubric-build`` / ``rubric-score``).

    python scripts/eval/notes_pairs.py build --a <notes-pipeline> --b <notes-single> --corpus <dir> --out <pairs-dir>
    python scripts/eval/notes_pairs.py score <pairs-dir>/ratings.csv <pairs-dir>/key.csv --corpus <dir>

Sheets and notes stay under ``scripts/eval/local/``; reports carry numbers only.
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
# One question on the overview alone, asked of both notes of a pair.
# Gate: "yes" for our notes on >= 90 % of answers on v2.
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
    """Topic bullets only: ours under non-role headings (sub-points included), the baseline's
    first paragraph as bullets.
    """
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
        facts = "\n".join(
            f"- {f['text'] if isinstance(f, dict) else f}"
            for f in meeting.get("gold", {}).get("key_facts", [])
        )
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


# ── The blind rubric ────────────

RUBRIC: tuple[tuple[str, str, str], ...] = (
    ("q1", "Orientation", "From the first block alone: what is this, who speaks, what does it "
     "cover? 2 all three · 1 two · 0 fewer"),
    ("q2", "Structure", "Do the headings alone tell the story in order? 2 yes · 1 partly · 0 no"),
    ("q3", "Specificity", "Share of bullets with a name, number, date or term: "
     "2 ≥ 90 % · 1 60–89 % · 0 < 60 %"),
    ("q4", "Faithfulness", "Check the five lines listed below against the transcript. Claims "
     "not supported: 2 none · 1 one · 0 two or more"),
    ("q5", "Exactness", "Numbers, units, qualifiers as spoken: 2 all · 1 one miss · 0 more"),
    ("q6", "Subjects and roles", "Pronouns or labels as subjects; wrong presenter, guest or "
     "type: 2 none · 1 one · 0 more"),
    ("q7", "Volume", "Body words within the band shown below: 2 yes · 1 within 25 % · 0 worse"),
    ("q8", "Form", "Copies, description, redundancy, rendering defects: 2 none · 1 one · 0 more"),
)  # fmt: skip
# Asked beside the rubric, not scored in it: does the title describe the whole recording?
TITLE_QUESTION = ("title_whole", "Does the title describe the whole recording, not only its "
                  "beginning? yes · no")  # fmt: skip
RUBRIC_MAX = 2 * len(RUBRIC)
RUBRIC_GATE_MEAN = 13.0
RUBRIC_GATE_FAITHFUL = 0.95  # share of notes with Q4 = 2
FAITHFULNESS_LINES = 5


def _speech_minutes(meeting: dict[str, Any]) -> float:
    spans = sorted((t["t_start_ms"], t["t_end_ms"]) for t in meeting.get("transcript", []))
    total, end = 0, 0
    for start, stop in spans:
        start = max(start, end)
        if stop > start:
            total += stop - start
            end = stop
    return total / 60_000


def rubric_build(arms: dict[str, Path], corpus: Path, out: Path, *, seed: int = 0) -> int:
    """One file per (meeting, arm) note, in a random order under a neutral
    id; ``rubric.csv`` for the raters, ``rubric_key.csv`` kept apart. Each
    file lists the five lines the rater checks for Q4 and the word band for
    Q7."""
    out = _local(out)
    out.mkdir(parents=True, exist_ok=True)
    meetings = _meetings(corpus)
    rng = random.Random(seed)
    notes = [
        (meeting_id, arm, folder / f"{meeting_id}.md")
        for meeting_id in sorted(meetings)
        for arm, folder in arms.items()
        if (folder / f"{meeting_id}.md").is_file()
    ]
    rng.shuffle(notes)
    sheet: list[list[str]] = [["note_id", "rater", *(q for q, _n, _t in RUBRIC), TITLE_QUESTION[0]]]
    key: list[list[str]] = [["note_id", "meeting_id", "arm"]]
    for n, (meeting_id, arm, path) in enumerate(notes, 1):
        note_id = f"n{n:03d}"
        meeting = meetings[meeting_id]
        text = path.read_text("utf-8")
        body = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        checked = rng.sample(body, min(FAITHFULNESS_LINES, len(body)))
        minutes = _speech_minutes(meeting)
        transcript = "\n".join(
            f"[{t['t_start_ms'] // 60000:02d}:{t['t_start_ms'] // 1000 % 60:02d}] "
            f"{t['speaker']}: {t['text']}"
            for t in meeting["transcript"]
        )
        questions = "\n".join(f"- **{q.upper()} {name}** — {text}" for q, name, text in RUBRIC)
        questions += f"\n- **Title** — {TITLE_QUESTION[1]}"
        (out / f"{note_id}.md").write_text(
            f"# Note {note_id}\n\n## Questions (0–2 each)\n\n{questions}\n\n"
            f"**Q4 lines to check:**\n\n" + "\n".join(f"- {ln}" for ln in checked) + "\n\n"
            f"**Q7 band:** {round(8 * minutes)}–{round(18 * minutes)} words "
            f"({minutes:.1f} minutes of speech)\n\n"
            f"## The note\n\n{text}\n\n## Transcript\n\n{transcript}\n",
            encoding="utf-8",
        )
        sheet.append([note_id, "", *([""] * len(RUBRIC)), ""])
        key.append([note_id, meeting_id, arm])
    for name, rows in (("rubric.csv", sheet), ("rubric_key.csv", key)):
        with (out / name).open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
    print(f"{len(notes)} notes in {out}")
    return 0


def rubric_score(ratings_path: Path, key_path: Path) -> dict[str, Any]:
    """Per arm: mean total (of 16), mean per question, the share of notes
    with Q4 = 2, the notes with Q1 = 0 — each note's score is the median of
    its raters — and the release gate for the pipeline (§8)."""
    import statistics

    with key_path.open(encoding="utf-8") as handle:
        key = {row["note_id"]: row for row in csv.DictReader(handle)}
    with ratings_path.open(encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if all(r.get(q) for q, _n, _t in RUBRIC)]
    by_note: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_note[row["note_id"]].append(row)
    arms: dict[str, list[dict[str, float]]] = defaultdict(list)
    title_votes: dict[str, list[bool]] = defaultdict(list)
    for note_id, ratings in by_note.items():
        scores = {q: float(statistics.median(int(r[q]) for r in ratings)) for q, _n, _t in RUBRIC}
        arms[key[note_id]["arm"]].append(scores)
        # The majority of the raters who answered the title question.
        said = [r.get(TITLE_QUESTION[0], "").strip().casefold() for r in ratings]
        said = [s for s in said if s in ("yes", "no")]
        if said:
            title_votes[key[note_id]["arm"]].append(said.count("yes") * 2 > len(said))
    out: dict[str, Any] = {"raters": len({r["rater"] for r in rows}), "arms": {}}
    for arm, notes in sorted(arms.items()):
        totals = [sum(n.values()) for n in notes]
        out["arms"][arm] = {
            "notes": len(notes),
            "mean_total": sum(totals) / len(totals),
            "max_total": RUBRIC_MAX,
            "per_question": {q: sum(n[q] for n in notes) / len(notes) for q, _name, _t in RUBRIC},
            "faithful_share": sum(1 for n in notes if n["q4"] == 2) / len(notes),
            "orientation_zero": sum(1 for n in notes if n["q1"] == 0),
            "title_whole_share": (
                sum(title_votes[arm]) / len(title_votes[arm]) if title_votes[arm] else None
            ),
        }
    ours = out["arms"].get(PIPELINE)
    out["release_gate"] = (
        None
        if ours is None
        else {
            "mean_total": ours["mean_total"] >= RUBRIC_GATE_MEAN,
            "faithful_share": ours["faithful_share"] >= RUBRIC_GATE_FAITHFUL,
            "no_orientation_zero": ours["orientation_zero"] == 0,
        }
    )
    return out


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
    rb = sub.add_parser("rubric-build", help="the document standard's blind rubric (§8)")
    rb.add_argument(
        "--arm",
        action="append",
        required=True,
        metavar="NAME=DIR",
        help="notes folder per arm, e.g. pipeline=scripts/eval/local/notes-pipeline",
    )
    rb.add_argument("--corpus", type=Path, required=True)
    rb.add_argument("--out", type=Path, required=True)
    rb.add_argument("--seed", type=int, default=0)
    rs = sub.add_parser("rubric-score")
    rs.add_argument("ratings", type=Path)
    rs.add_argument("key", type=Path)
    rs.add_argument("--write", action="store_true", help="write docs/eval/notes-rubric-<date>.json")
    args = parser.parse_args(argv)
    if args.command == "rubric-build":
        arms = dict(item.split("=", 1) for item in args.arm)
        return rubric_build(
            {k: Path(v) for k, v in arms.items()}, args.corpus, args.out, seed=args.seed
        )
    if args.command == "rubric-score":
        scored = rubric_score(args.ratings, args.key)
        print(json.dumps(scored, indent=2))
        if args.write:
            DOCS_EVAL.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y-%m-%d")
            target = DOCS_EVAL / f"notes-rubric-{stamp}.json"
            target.write_text(json.dumps(scored, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {target}")
        return 0
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
