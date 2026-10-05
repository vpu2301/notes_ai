#!/usr/bin/env python3
"""The local bake-off report (numbers only) from the day's manifest entries under
``scripts/eval/local/bakeoff-<date>/``.

    uv run --project services/note-service python scripts/eval/local_bakeoff_report.py --date 2026-09-27
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
LOCAL = REPO / "scripts" / "eval" / "local"
DOCS_EVAL = REPO / "docs" / "eval"

DROP_KEYS = (
    "facts_dropped_quote",
    "facts_dropped_noise",
    "facts_dropped_example",
    "facts_dropped_paraphrase",
)


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{100 * value:.0f} %"


def _num(value: Any, digits: int = 0) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def _host() -> dict[str, str]:
    info: dict[str, str] = {"platform": platform.platform()}
    if platform.system() == "Darwin":
        try:
            mem = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            info["memory_gib"] = f"{int(mem.stdout.strip()) / 2**30:.0f}"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        docker = subprocess.run(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if docker.returncode == 0 and docker.stdout.strip().isdigit():
            info["docker_limit_gib"] = f"{int(docker.stdout.strip()) / 2**30:.1f}"
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def load_entries(folder: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime):
        entry = json.loads(path.read_text("utf-8"))
        report_path = entry.get("report")
        entry["_report"] = None
        if report_path:
            candidate = Path(report_path)
            if not candidate.is_absolute():
                candidate = REPO / candidate
            if candidate.is_file():
                entry["_report"] = json.loads(candidate.read_text("utf-8"))
        entries.append(entry)
    return entries


def funnel(run: dict[str, Any]) -> tuple[int, int, int]:
    proposed = verified = rendered = 0
    for meeting in run.get("meetings", []):
        if meeting.get("failed"):
            continue
        stats = meeting.get("stats") or {}
        kept = int(stats.get("facts_kept") or 0)
        verified += kept
        proposed += kept + sum(int(stats.get(k) or 0) for k in DROP_KEYS)
        rendered += int(meeting.get("lines") or 0)
    return proposed, verified, rendered


def row_for(entry: dict[str, Any]) -> dict[str, Any]:
    label = f"`{entry['tag']}`" + ("" if entry.get("profile", True) else " (profile off)")
    report = entry.get("_report")
    api = bool(entry.get("api")) or (report or {}).get("backend", "").startswith("mistral")
    if api and report:
        label = f"API `{report.get('backend')}` · `{report.get('model_id')}`"
    row: dict[str, Any] = {"model": label, "status": entry.get("status", ""), "api": api}
    if not report or not report.get("runs"):
        return row
    run = report["runs"][-1]
    summary = run["summary"]
    proposed, verified, rendered = funnel(run)
    row.update(
        {
            "unsupported": _pct(summary.get("unsupported_rate")),
            "invented": _num(summary.get("invented_claims")),
            "recall": _pct(summary.get("key_fact_recall")),
            "funnel": f"{proposed} → {verified} → {rendered}",
            "lint": _pct(summary.get("lint_first_pass")),
            "seconds": _num(summary.get("seconds_per_meeting_hour"), 0),
            "cost": (
                "0 (local)"
                if report.get("backend", "").startswith("dev_mac")
                else _num(summary.get("cost_cents_per_meeting_hour"), 2)
            ),
            "peak": (
                f"{entry['peak_gb']} GB, {entry.get('processor') or '?'}"
                if entry.get("peak_gb")
                else ("n/a (API)" if api else "–")
            ),
            "checks": (
                f"{entry['checks'][0]}/{entry['checks'][1]}" if entry.get("checks") else "–"
            ),
            "failed": _num(summary.get("meetings_failed")),
            "sections_in_band": _pct(summary.get("sections_in_band")),
            "specific": _pct(summary.get("bullets_specific_share")),
            "ladder": json.dumps(summary.get("summary_ladder") or {}, sort_keys=True),
            "context": report.get("context_window"),
            "meetings": [
                {
                    "id": m.get("meeting"),
                    "sections": m.get("sections"),
                    "bullets": m.get("bullets"),
                    "invented": m.get("invented_claims"),
                    "unsupported": m.get("unsupported"),
                    "seconds": m.get("seconds"),
                    "failed": m.get("failed"),
                }
                for m in run.get("meetings", [])
            ],
        }
    )
    return row


HEAD = (
    "| Model | Unsupported | Invented | Key-fact recall | Funnel proposed → verified → rendered "
    "| Linter first pass | Rubric r01–r03 | s / meeting-hour | ¢ / meeting-hour | Peak (`ollama ps`) | Checklists | Sections in band | Specific bullets |"
)
RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def table(rows: list[dict[str, Any]]) -> list[str]:
    out = [HEAD, RULE]
    api_rows = 0
    for row in rows:
        if "recall" not in row:
            out.append(f"| {row['model']} | {row['status']} |" + " – |" * 11)
            continue
        if row.get("api"):
            api_rows += 1
        out.append(
            f"| {row['model']} | {row['unsupported']} | {row['invented']} | {row['recall']} | {row['funnel']} "
            f"| {row['lint']} | pending | {row['seconds']} | {row['cost']} | {row['peak']} | {row['checks']} "
            f"| {row['sections_in_band']} | {row['specific']} |"
        )
    if not api_rows:
        out.append(
            "| API model (L2, `mistral_eu`) | API row pending: no MISTRAL_API_KEY on this machine |"
            + " – |" * 11
        )
    return out


def per_meeting(rows: list[dict[str, Any]]) -> list[str]:
    """Sections and bullets per meeting — the Done-when 3 numbers."""
    ids: list[str] = []
    for row in rows:
        for m in row.get("meetings", []):
            if m["id"] not in ids:
                ids.append(m["id"])
    if not ids:
        return []
    out = ["| Model | " + " | ".join(f"{i} sections / bullets / invented" for i in ids) + " |"]
    out.append("|---|" + "---|" * len(ids))
    for row in rows:
        if "meetings" not in row:
            continue
        by_id = {m["id"]: m for m in row["meetings"]}
        cells = []
        for i in ids:
            m = by_id.get(i)
            if m is None:
                cells.append("–")
            elif m.get("failed"):
                cells.append("failed")
            else:
                cells.append(
                    f"{_num(m.get('sections'))} / {_num(m.get('bullets'))} / {_num(m.get('invented'))}"
                )
        out.append(f"| {row['model']} | " + " | ".join(cells) + " |")
    return out


def main(date: str, out: Path | None) -> int:
    folder = LOCAL / f"bakeoff-{date}"
    if not folder.is_dir():
        print(f"no manifest folder {folder}", file=sys.stderr)
        return 3
    entries = load_entries(folder)
    if not entries:
        print(f"no entries in {folder}", file=sys.stderr)
        return 3
    host = _host()
    lines = [
        f"# Local bake-off — {date} (Sprint L1 T3)",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='minutes')} by `scripts/eval/local_bakeoff_report.py` "
        f"from `scripts/eval/local/bakeoff-{date}/`. Pipeline arm, `dev_mac` through Ollama, "
        "`infra/models/dev-mac/Modelfile` (num_ctx 16384, temperature 0), the small-model profile ON "
        "unless a row says otherwise.",
        "",
        f"Host: {host.get('platform', '?')}, {host.get('memory_gib', '?')} GiB unified memory, "
        f"Docker limit at report time {host.get('docker_limit_gib', '?')} GiB. "
        "Budget rule: total − Docker limit − 3 GiB; a row `skipped: over budget` did not fit that "
        "(weights at Q4 + q8_0 KV at 16K).",
        "",
        "Numbers only. `Funnel` is facts the model proposed → facts verification kept → lines rendered "
        "(M1's counters are not merged; proposed = kept + the drop counters). `Rubric` waits for raters. "
        "`Checklists` is `make eval-notes-assert` passes/total on the meetings of this corpus that have one.",
    ]
    by_corpus: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_corpus.setdefault(entry.get("corpus", "?"), []).append(entry)
    for corpus, group in by_corpus.items():
        rows = [row_for(e) for e in group]
        lines += ["", f"## Corpus `{corpus}`", ""]
        lines += table(rows)
        pm = per_meeting(rows)
        if pm:
            lines += ["", "Per meeting (sections / rendered bullets / invented claims):", ""] + pm
        ladders = [f"{r['model']}: {r['ladder']}" for r in rows if r.get("ladder")]
        if ladders:
            lines += ["", "Summary ladder per model: " + "; ".join(ladders) + "."]
    lines += [
        "",
        "## Reports",
        "",
        *[
            f"- {e['tag']}{'' if e.get('profile', True) else ' (profile off)'} on `{e.get('corpus')}`: "
            f"`{Path(e['report']).name if e.get('report') else '—'}` — {e.get('status')}"
            for e in entries
        ],
        "",
    ]
    target = out or (DOCS_EVAL / f"notes-local-bakeoff-{date}.md")
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    sys.exit(main(args.date, args.out))
