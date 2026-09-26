#!/usr/bin/env python3
"""Sprint F1 T3 — the coverage report, from ``coverage_eval.py``'s JSON.

    uv run python scripts/eval/coverage_report.py docs/eval/asr-coverage-2026-10.json \\
        > docs/eval/asr-coverage-2026-10.md

Numbers only. Applies the work order's shipping rule: the configuration with
the highest coverage whose word change against ``today`` is within 0.5 point
(the WER bound — see coverage_eval.py) and whose inference time is at most
1.2× today's.
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


def shipped(configs: dict[str, dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """(the configuration to ship, why each other one is not)."""
    verdicts: dict[str, str] = {}
    eligible: list[tuple[float, str]] = []
    for name, c in configs.items():
        if c["word_change_vs_today"] > MAX_WORD_CHANGE:
            verdicts[name] = f"word change {_pct(c['word_change_vs_today'])} > 0.5 pt"
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
    best, verdicts = shipped(configs)
    names = list(configs)
    steps = step_change(names, list(configs["today"]["files"]))
    for n in names:
        configs[n]["_step"] = steps.get(n)
    out = [
        "# Sprint F1 T3 — speech coverage, measured before shipping",
        "",
        f"**Report:** `{Path(report.get('_path', 'asr-coverage.json')).name}` "
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
        f"**Shipped: `{best}`.** Rule: highest coverage with word change ≤ 0.5 pt and "
        "inference ≤ 1.2× today.",
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


if __name__ == "__main__":
    path = Path(sys.argv[1])
    data = json.loads(path.read_text("utf-8"))
    data["_path"] = str(path)
    sys.stdout.write(render(data))
