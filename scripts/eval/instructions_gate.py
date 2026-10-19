"""Note instructions gate (N2 T6): an instructed arm against the plain arm on the same corpus.

    instructions_gate.py <plain.json> <instructed.json> --profile <profile.json> --notes <dir>

Fails (exit 1) when the instructed arm's ``citation_precision`` or
``judge_unsupported_rate`` is worse by more than one point, or — for a profile that keeps
the standard length — ``key_fact_recall`` by more than five. A shorter note may recall
less; it may not be less true. Then checks the code dials on the instructed arm's saved
notes (``notes_eval.py --save-notes``; ``<id>.sections.json``), which must hold for every
meeting: summary sentences within the cap, bullets per section within range, no figure table
when tables are off, no section of a role the profile leaves out, no avoided word and no replaced term in a composed line.

Writes ``docs/eval/instructions-gate-<date>-<backend>-<label>.json``: numbers only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, write_report  # noqa: E402

ENGINE_SRC = REPO / "services" / "note-service" / "src"

POINT = 0.01
# metric -> (worse when, allowed worsening)
TRUTH = {
    "citation_precision": ("lower", 1 * POINT),
    "judge_unsupported_rate": ("higher", 1 * POINT),
}
RECALL = {"key_fact_recall": ("lower", 5 * POINT)}
SHOWN = (
    "key_fact_recall",
    "citation_precision",
    "judge_unsupported_rate",
    "summary_sentences_mean",
    "sections_mean",
    "words_per_minute",
)
COMPOSED_EXEMPT = ("quote", "heading")


def _summary(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report = json.loads(path.read_text("utf-8"))
    return report, report["runs"][-1]["summary"]


def _worse(
    metric: str, plain: float | None, instructed: float | None, rule: tuple[str, float]
) -> bool | None:
    if plain is None or instructed is None:
        return None
    direction, allowed = rule
    delta = instructed - plain if direction == "higher" else plain - instructed
    return delta > allowed + 1e-9


def _phrase(text: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(text)}(?!\w)", re.IGNORECASE)


def compliance(profile: Any, notes: Path) -> dict[str, dict[str, int]]:
    """``{dial: {"ok": n, "of": m}}`` over every saved note; a dial the profile leaves at
    its default is not listed."""
    from note_service.domain.meeting_doc import styling

    style = styling.from_profile(profile)
    scale = style.effective_scale(1.0)
    cap = style.summary_cap(scale)
    avoid = [_phrase(a) for a in profile.avoid]
    replaced = [_phrase(t.instead_of) for t in profile.terminology]
    out: dict[str, dict[str, int]] = {}

    def tally(dial: str, ok: bool) -> None:
        cell = out.setdefault(dial, {"ok": 0, "of": 0})
        cell["of"] += 1
        cell["ok"] += int(ok)

    for path in sorted(notes.glob("*.sections.json")):
        sections = json.loads(path.read_text("utf-8"))
        lines = [ln for s in sections for ln in s.get("lines") or []]
        composed = [ln["text"] for ln in lines if ln["kind"] not in COMPOSED_EXEMPT]
        if profile.summary_sentences is not None or style.scale is not None:
            tally("summary_sentences", sum(1 for ln in lines if ln["kind"] == "summary") <= cap)
        if profile.bullets_per_section:
            lo, hi = profile.bullets_per_section
            for s in sections:
                if s.get("role") != "topics":
                    continue
                top = [
                    ln for ln in s.get("lines") or []
                    if ln["kind"] in ("bullet", "key_point") and ln["text"].startswith("- ")
                ]  # fmt: skip
                tally("bullets_per_section", lo <= len(top) <= hi)
        if not profile.figure_tables:
            tally("figure_tables", not any(ln["kind"] == "figure" for ln in lines))
        for role in profile.sections_off:
            tally(f"sections_off:{role}", not any(s.get("role") == role for s in sections))
        if avoid:
            tally("avoid", not any(p.search(t) for p in avoid for t in composed))
        if replaced:
            tally("terminology", not any(p.search(t) for p in replaced for t in composed))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plain", type=Path)
    ap.add_argument("instructed", type=Path)
    ap.add_argument("--profile", type=Path, required=True)
    ap.add_argument(
        "--notes", type=Path, default=None, help="the instructed arm's --save-notes folder"
    )
    args = ap.parse_args()

    sys.path.insert(0, str(ENGINE_SRC))
    from note_service.domain import note_instructions

    profile = note_instructions.WritingProfile.model_validate_json(args.profile.read_text("utf-8"))
    plain_report, plain = _summary(args.plain)
    instructed_report, instructed = _summary(args.instructed)
    if plain_report.get("corpus") != instructed_report.get("corpus"):
        print("the two arms ran on different corpora", file=sys.stderr)
        return 2

    rules = dict(TRUTH)
    if profile.length == "standard":
        rules.update(RECALL)
    verdicts = {m: _worse(m, plain.get(m), instructed.get(m), r) for m, r in rules.items()}

    print(f"{'metric':<26}{'plain':>10}{'instructed':>12}{'delta':>10}  gate")
    for metric in SHOWN:
        a, b = plain.get(metric), instructed.get(metric)
        delta = round(b - a, 4) if a is not None and b is not None else None
        verdict = verdicts.get(metric)
        gate = (
            ""
            if metric not in rules
            else ("n/a" if verdict is None else ("FAIL" if verdict else "ok"))
        )
        print(f"{metric:<26}{_fmt(a):>10}{_fmt(b):>12}{_fmt(delta):>10}  {gate}")

    table = compliance(profile, args.notes) if args.notes is not None else {}
    if table:
        print(f"\n{'code dial':<30}{'compliant':>12}")
        for dial, cell in table.items():
            print(f"{dial:<30}{cell['ok']:>6}/{cell['of']:<5}")
    elif args.notes is not None:
        print(f"\nno saved notes in {args.notes}", file=sys.stderr)
    failed = any(v for v in verdicts.values()) or any(c["ok"] < c["of"] for c in table.values())

    path = write_report(
        "instructions-gate",
        str(instructed_report.get("backend")),
        {
            "plain": args.plain.name,
            "instructed": args.instructed.name,
            "corpus": instructed_report.get("corpus"),
            "prompt_version": instructed_report.get("prompt_version"),
            "instructions": instructed_report.get("instructions"),
            "metrics": {m: {"plain": plain.get(m), "instructed": instructed.get(m)} for m in SHOWN},
            "gates": {m: (None if v is None else not v) for m, v in verdicts.items()},
            "compliance": table,
            "passed": not failed,
        },
        suffix=f"-{instructed_report.get('label') or args.profile.stem}",
    )
    print(f"\n{'FAIL' if failed else 'PASS'}  wrote {path.relative_to(REPO)}")
    return 1 if failed else 0


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


if __name__ == "__main__":
    sys.exit(main())
