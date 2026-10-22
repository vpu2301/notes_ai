"""Medians of two conditions side by side, with the Sprint A §4 threshold checks.

    uv run python tools/asr_bench/compare.py --a A/baseline-cpu --b B2/metal-large-v3 \
        [--mixed-recording mix-de-en-3m --mixed-switches 4] [--long-recording en-15m]

Reads ``runs.csv`` (and ``quality.csv`` when present) under ``asr-perf-sprints/evidence/``.
Excluded rows never count. Every threshold is printed for every comparison; which ones a
sprint must pass is the sprint's gate, not this script's.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402

GiB = 1024**3
SPEED = (
    "asr_primary_rtf", "asr_primary_wall_seconds", "lid_call_count", "lid_total_seconds",
    "time_to_asr_start_seconds", "audio_prep_seconds", "diarization_infer_seconds",
    "pipeline_wall_seconds", "rss_peak_bytes", "swap_delta_bytes", "telemetry_overhead_seconds",
    "audio_duration_seconds",
)  # fmt: skip
QUALITY = (
    "wer", "cer", "ts_median_ms", "ts_p90_ms", "speaker_agreement", "hallucinated_segments",
    "switch_long_recall", "switch_short_recall",
)  # fmt: skip

Medians = dict[tuple[str, str], dict[str, float]]


def medians(condition: str) -> Medians:
    """``(recording, temp) → metric → median`` over included rows; quality under temp ``q``."""
    base = bench.EVIDENCE / condition
    groups: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in bench.read_csv(base / "runs.csv"):
        if row["excluded"]:
            continue
        for k in SPEED:
            if (v := bench.num(row.get(k))) is not None:
                groups[(row["recording"], row["temp"])][k].append(v)
    for row in bench.read_csv(base / "quality.csv"):
        for k in QUALITY:
            if (v := bench.num(row.get(k))) is not None:
                groups[(row["recording"], "q")][k].append(v)
    out: Medians = {}
    for key, metrics in groups.items():
        out[key] = {k: mmm[0] for k, vs in metrics.items() if (mmm := bench.median_min_max(vs))}
    return out


Check = Callable[[float | None, float], bool | None]


def checks(args: argparse.Namespace) -> list[tuple[str, str, str, Check]]:
    """``(name, temp, metric, f(a, b))``; ``f`` sees baseline ``a`` and candidate ``b``."""

    def both(f: Callable[[float, float], bool]) -> Check:
        return lambda a, b: None if a is None else f(a, b)

    return [
        (
            "WER ≤ base+1.0pt and ≤ base×1.10",
            "q",
            "wer",
            both(lambda a, b: b <= a + 0.01 and b <= a * 1.10),
        ),
        (
            "switch recall ≥3 s ≥ 90 % and ≥ base",
            "q",
            "switch_long_recall",
            both(lambda a, b: b >= 0.90 and b >= a),
        ),
        ("short passages ≥ base", "q", "switch_short_recall", both(lambda a, b: b >= a)),
        (
            "timestamp median ≤ 80 ms and ≤ base+20",
            "q",
            "ts_median_ms",
            both(lambda a, b: b <= 80 and b <= a + 20),
        ),
        ("timestamp p90 ≤ 250 ms", "q", "ts_p90_ms", lambda a, b: b <= 250),
        (
            "speaker agreement ≥ 95 % and ≥ base−1pt",
            "q",
            "speaker_agreement",
            both(lambda a, b: b >= 0.95 and b >= a - 0.01),
        ),
        ("hallucinated segments ≤ base", "q", "hallucinated_segments", both(lambda a, b: b <= a)),
        ("P1 warm asr rtf ≤ 0.35", "warm", "asr_primary_rtf", lambda a, b: b <= 0.35),
        ("P1 cold asr rtf ≤ 0.6", "cold", "asr_primary_rtf", lambda a, b: b <= 0.6),
        ("P1 RSS ≤ base+2 GB", "warm", "rss_peak_bytes", both(lambda a, b: b <= a + 2 * GiB)),
        ("P1 swap delta ≤ 0.5 GB", "warm", "swap_delta_bytes", lambda a, b: b <= 0.5 * GiB),
    ]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--a", required=True, help="baseline, e.g. A/baseline-cpu")
    p.add_argument("--b", required=True, help="candidate")
    p.add_argument("--mixed-recording", default="mix-de-en-3m")
    p.add_argument("--mixed-switches", type=int, help="real language switches in the mixed file")
    p.add_argument("--long-recording", default="en-15m")
    args = p.parse_args()
    ma, mb = medians(args.a), medians(args.b)

    print(f"| recording | temp | metric | {args.a} | {args.b} | Δ |\n|---|---|---|---|---|---|")
    for key in sorted(set(ma) | set(mb)):
        for k in sorted(set(ma.get(key, {})) | set(mb.get(key, {}))):
            a, b = ma.get(key, {}).get(k), mb.get(key, {}).get(k)
            delta = f"{b - a:+.3f}" if a is not None and b is not None else "—"
            fa = f"{a:.3f}" if a is not None else "—"
            fb = f"{b:.3f}" if b is not None else "—"
            print(f"| {key[0]} | {key[1]} | {k} | {fa} | {fb} | {delta} |")

    print("\n| threshold | recording | result |\n|---|---|---|")

    def verdict(ok: bool | None) -> str:
        return "n/a" if ok is None else ("PASS" if ok else "FAIL")

    for recording in sorted({r for r, _ in mb}):
        for name, temp, metric, f in checks(args):
            b = mb.get((recording, temp), {}).get(metric)
            if b is None:
                continue
            print(
                f"| {name} | {recording} | {verdict(f(ma.get((recording, temp), {}).get(metric), b))} |"
            )
        w = mb.get((recording, "warm"), {})
        audio = w.get("audio_duration_seconds")
        if audio and (lid := w.get("lid_total_seconds")) is not None:
            ok = lid <= 0.03 * audio and (recording != args.long_recording or lid <= 10)
            print(
                f"| P2 LID total ≤ 3 % of audio (≤ 10 s on {args.long_recording}) | {recording} | {verdict(ok)} |"
            )
        if (calls := w.get("lid_call_count")) is not None:
            if recording == args.mixed_recording:
                limit = None if args.mixed_switches is None else 1 + 2 * args.mixed_switches
            else:
                limit = 3
            ok = None if limit is None else calls <= limit
            print(
                f"| P2 LID calls ≤ {limit if limit is not None else '?'} | {recording} | {verdict(ok)} |"
            )
        start, prep = w.get("time_to_asr_start_seconds"), w.get("audio_prep_seconds")
        if start is not None and prep is not None:
            print(
                f"| P2 ASR start ≤ audio prep + 10 s | {recording} | {verdict(start <= prep + 10)} |"
            )
        if recording == args.long_recording and audio and (wall := w.get("pipeline_wall_seconds")):
            print(
                f"| D pipeline wall / audio ≤ 0.6 | {recording} | {verdict(wall / audio <= 0.6)} |"
            )
        if wall_ := w.get("pipeline_wall_seconds"):
            over = w.get("telemetry_overhead_seconds")
            ok = None if over is None else over / wall_ < 0.01
            print(f"| telemetry overhead < 1 % | {recording} | {verdict(ok)} |")


if __name__ == "__main__":
    main()
