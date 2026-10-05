#!/usr/bin/env python3
"""The coverage report (numbers only) from ``coverage_eval.py``'s JSON, applying the
shipping rule: highest coverage within 0.5 point of word change and 1.2x today's time.

    uv run python scripts/eval/coverage_report.py <report.json> > <report.md>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from typing import Any

MAX_WORD_CHANGE = 0.005
MAX_INFERENCE = 1.2


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f} %"


LOCAL = Path(__file__).resolve().parent / "local"


def _words(config: str, name: str) -> list[str] | None:
    """A configuration's transcript of one file, as saved locally by the
    eval (gitignored) — words only, timestamps and labels off."""
    import re

    path = LOCAL / f"coverage-{config}" / f"{name}.txt"
    if not path.is_file():
        return None
    text = re.sub(r"^\[\s*\d+s\](?: \[[a-z]{2,3}\])?", "", path.read_text("utf-8"), flags=re.M)
    return [w.casefold() for w in re.findall(r"[^\W_]+", text)]


def step_change(names: list[str], files: list[str]) -> dict[str, float | None]:
    """Word change of each configuration against the one before it — what
    each single change did, rather than all of them against today."""
    from coverage_eval import _edit_distance

    out: dict[str, float | None] = {names[0]: 0.0}
    for prev, cur in zip(names, names[1:], strict=False):
        changed = base = 0
        for name in files:
            a, b = _words(prev, name), _words(cur, name)
            if a is None or b is None:
                out[cur] = None
                break
            changed += _edit_distance(a, b)
            base += len(a)
        else:
            out[cur] = changed / base if base else 0.0
    return out


def edits(a_config: str, b_config: str, files: list[str]) -> dict[str, float] | None:
    """Words inserted, deleted and substituted going from one configuration
    to another, as shares of the first one's words."""
    import difflib

    ops = {"insert": 0, "delete": 0, "replace": 0}
    base = 0
    for name in files:
        a, b = _words(a_config, name), _words(b_config, name)
        if a is None or b is None:
            return None
        base += len(a)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op == "insert":
                ops["insert"] += j2 - j1
            elif op == "delete":
                ops["delete"] += i2 - i1
            elif op == "replace":
                ops["replace"] += max(i2 - i1, j2 - j1)
    return {k: v / base for k, v in ops.items()} if base else None


def shipped(configs: dict[str, dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """(the configuration to ship, why each other one is not)."""
    verdicts: dict[str, str] = {}
    eligible: list[tuple[float, str]] = []
    for name, c in configs.items():
        # Inserted words closed a gap and cannot raise the error rate; deleted
        # and substituted words bound it.
        ops = c.get("_ops")
        risky = (ops["delete"] + ops["replace"]) if ops else c["word_change_vs_today"]
        if risky > MAX_WORD_CHANGE:
            verdicts[name] = f"deleted + substituted {_pct(risky)} > 0.5 pt"
        elif c["inference_vs_today"] > MAX_INFERENCE:
            verdicts[name] = f"inference {c['inference_vs_today']:.2f}× > 1.2×"
        else:
            eligible.append((c["coverage_share"] or 0.0, name))
            verdicts[name] = "eligible"
    # Highest coverage; on a tie the later (more complete) configuration.
    order = list(configs)
    best = max(eligible, key=lambda t: (t[0], order.index(t[1])))[1] if eligible else "today"
    return best, verdicts


def render(report: dict[str, Any]) -> str:
    configs = report["configs"]
    names = list(configs)
    files = list(configs["today"]["files"])
    steps = step_change(names, files)
    for n in names:
        configs[n]["_step"] = steps.get(n)
        configs[n]["_ops"] = edits("today", n, files) if n != "today" else None
    best, verdicts = shipped(configs)
    out = [
        "# Sprint F1 T3 — speech coverage, measured before shipping",
        "",
        f"**Report:** `{report.get('_path', 'asr-coverage.json')}` "
        f"(`scripts/eval/coverage_eval.py`, git `{report.get('git', '?')}`). **Engine:** in-process "
        f"`{report['model']}`, {report['compute_type']}, {report['device']}. **Files:** "
        + ", ".join(
            f"{n} ({r['audio_seconds']:.0f} s)" for n, r in configs["today"]["files"].items()
        )
        + ".",
        "",
        "## Configurations",
        "",
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    rows = [
        ("Coverage share (VAD speech transcribed)", lambda c: _pct(c["coverage_share"])),
        ("Reference speech covered (RTTM, speakers files)", lambda c: _pct(c["rttm_coverage"])),
        ("Word change vs today (WER bound)", lambda c: _pct(c["word_change_vs_today"])),
        ("Word change vs the configuration before", lambda c: _pct(c.get("_step"))),
        (
            "vs today: inserted / deleted / substituted",
            lambda c: (
                " / ".join(_pct(c["_ops"][k]) for k in ("insert", "delete", "replace"))
                if c.get("_ops")
                else "—"
            ),
        ),
        (
            "Second-pass chunks per audio hour",
            lambda c: f"{c['second_pass_chunks_per_audio_hour']:.1f}",
        ),
        ("Inference seconds per audio hour", lambda c: f"{c['seconds_per_audio_hour']:.0f}"),
        ("Inference vs today", lambda c: f"{c['inference_vs_today']:.2f}×"),
        ("Verdict", lambda c: ""),
    ]
    for label, fn in rows:
        if label == "Verdict":
            cells = [("**shipped**" if n == best else verdicts[n]) for n in names]
        else:
            cells = [fn(configs[n]) for n in names]
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    out += [
        "",
        f"**Shipped: `{best}`.** Rule: highest coverage whose deleted + substituted words "
        "against today are ≤ 0.5 pt (the WER bound; inserted words are speech a gap had "
        "swallowed) and inference ≤ 1.2× today. Inference seconds are wall time on a shared "
        "machine: runs that overlapped another eval read slower than they are.",
        "",
        f"**WER: {report['wer_note']}.** **DER: {report['der_note']}.**",
        "",
        "## Per file",
        "",
        "| File | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for name in configs["today"]["files"]:
        cells = []
        for n in names:
            r = configs[n]["files"][name]
            gaps = ", ".join(
                f"{g['start_s']:.0f}–{g['end_s']:.0f} s {g['cause']}" for g in r["gaps"]
            )
            cells.append(f"{_pct(r['coverage_share'])}" + (f" ({gaps})" if gaps else ""))
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    incident = {n: configs[n]["files"].get("incident") for n in names}
    if any(incident.values()):
        out += ["", "## The Pardo recording (r02)", ""]
        before = report.get("incident_before_fix")
        if before:
            gaps = ", ".join(
                f"{g['start_s']:.0f}–{g['end_s']:.0f} s ({g['cause']})" for g in before["gaps"]
            )
            out.append(
                f"- **Stored transcript, before the fix:** coverage {_pct(before['coverage_share'])}, "
                f"first speech {before['first_speech_s']} s, first segment {before['first_segment_s']} s; "
                f"gaps {gaps or 'none'}; r02 {before['r02']}. The stored artifact predates diagnostics "
                f"(has diagnostics: {before['has_diagnostics']}), so code cannot name the cause; "
                "the I3 evidence note does: the old whole-segment prompt-echo drop (`prompt_echo`)."
            )
        for n, r in incident.items():
            if r:
                out.append(
                    f"- **{n}:** coverage {_pct(r['coverage_share'])}, first segment "
                    f"{r['first_segment_s']} s, second pass {r['second_pass']['chunks']} chunk(s) / "
                    f"{r['second_pass']['recovered_words']} words; r02 {r.get('r02')}."
                )
    return "\n".join(out) + "\n"


def merged(paths: list[Path]) -> dict[str, Any]:
    """The first report, plus every configuration a later report added.
    A later report's timing ratio is against its OWN `today` run — wall
    time from different sittings of a shared machine does not compare."""
    data = json.loads(paths[0].read_text("utf-8"))
    data["_path"] = ", ".join(p.name for p in paths)
    for path in paths[1:]:
        more = json.loads(path.read_text("utf-8"))
        for name, config in more["configs"].items():
            if name != "today":
                data["configs"][name] = config
    return data


if __name__ == "__main__":
    sys.stdout.write(render(merged([Path(a) for a in sys.argv[1:]])))
