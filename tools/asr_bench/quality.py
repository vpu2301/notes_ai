"""Transcript quality of one run against a reference (numbers only).

    # Freeze a run's transcript as the pseudo-reference (written outside the repo):
    uv run python tools/asr_bench/quality.py ref --run-id <run> --out ~/asr-perf-audio/refs/en-2m.json
    # Score a run against it:
    uv run python tools/asr_bench/quality.py score --run-id <run> \
        --reference ~/asr-perf-audio/refs/en-2m.json [--switches ~/asr-perf-audio/mix-de-en-3m.switches.json] \
        --sprint A --condition baseline-cpu --recording en-2m

The set has no hand-corrected references (owner decision, GATE A): the reference is a
``baseline-cpu`` transcript, so WER here is drift from the baseline, not error vs truth.
Switch passages for the mixed file are the owner's noted timestamps:
``[{"start_s": 12.0, "end_s": 18.5, "lang": "en"}, ...]``.

Metrics: WER and CER (normalised as in ``scripts/eval/asr_scoring.py``), word-timestamp
error over aligned words (median, p90), speaker agreement after the best label mapping,
hallucinated segments (no reference word in their span), and language-switch recall: a
passage is preserved when >= 80 % of the hypothesis words inside it come from segments in
the passage's language (translated or dropped = not preserved).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))
import asr_scoring  # noqa: E402
import bench  # noqa: E402

PRESERVED_SHARE = 0.80
SHORT_PASSAGE_S = 3.0
QUALITY_FIELDS = (
    "run_id", "recording", "condition", "ref_words", "wer", "cer", "ts_median_ms", "ts_p90_ms",
    "ts_matched", "speaker_agreement", "hallucinated_segments", "switch_long", "switch_long_kept",
    "switch_long_recall", "switch_short", "switch_short_kept", "switch_short_recall",
)  # fmt: skip


def hyp_view(result: dict[str, Any]) -> SimpleNamespace:
    """The duck-typed transcript ``asr_scoring`` reads, from the job result JSON."""
    segs = [
        SimpleNamespace(
            text=s.get("text") or "",
            start_ms=s["start_ms"],
            end_ms=s["end_ms"],
            speaker=s.get("speaker"),
            language=s.get("language"),
            words=[
                SimpleNamespace(text=w["text"], start_ms=w["start_ms"], end_ms=w["end_ms"])
                for w in s.get("words") or []
            ],
        )
        for s in result["segments"]
    ]
    return SimpleNamespace(language=result.get("language"), segments=segs)


def _timed_tokens(hyp: SimpleNamespace) -> list[tuple[str, int, int, str | None]]:
    """``(token, start_ms, end_ms, speaker)`` — each normalised token keeps its word's times."""
    out = []
    for seg in hyp.segments:
        lang = seg.language or hyp.language
        words = seg.words or [
            SimpleNamespace(text=seg.text, start_ms=seg.start_ms, end_ms=seg.end_ms)
        ]
        for w in words:
            for t in asr_scoring.tokens(w.text, lang):
                out.append((t, w.start_ms, w.end_ms, seg.speaker))
    return out


def _speaker_agreement(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    refs = sorted({r for r, _ in pairs})
    hyps = sorted({h for _, h in pairs})
    m = np.zeros((len(refs), len(hyps)))
    for r, h in pairs:
        m[refs.index(r), hyps.index(h)] += 1
    rows, cols = linear_sum_assignment(m, maximize=True)
    return float(m[rows, cols].sum() / len(pairs))


def _switches(hyp: SimpleNamespace, passages: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, keep in (
        ("long", lambda d: d >= SHORT_PASSAGE_S),
        ("short", lambda d: d < SHORT_PASSAGE_S),
    ):
        chosen = [p for p in passages if keep(p["end_s"] - p["start_s"])]
        kept = 0
        for p in chosen:
            a, b = p["start_s"] * 1000, p["end_s"] * 1000
            langs = [
                seg.language or hyp.language
                for seg in hyp.segments
                for w in (seg.words or [seg])
                if a <= (w.start_ms + w.end_ms) / 2 < b
            ]
            if langs and sum(lang == p["lang"] for lang in langs) / len(langs) >= PRESERVED_SHARE:
                kept += 1
        out[f"switch_{label}"] = len(chosen)
        out[f"switch_{label}_kept"] = kept
        out[f"switch_{label}_recall"] = kept / len(chosen) if chosen else None
    return out


def score(
    reference: dict[str, Any], result: dict[str, Any], passages: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    import jiwer

    ref, hyp = hyp_view(reference), hyp_view(result)
    # Word text on both sides: asr_scoring reads the hypothesis by words, and a segment's
    # text is post-processed, so segment text here would differ from the same transcript.
    ref_segments = [
        {
            "text": " ".join(w.text for w in s.words) if s.words else s.text,
            "language": s.language or ref.language,
            "start_ms": s.start_ms,
            "end_ms": s.end_ms,
        }
        for s in ref.segments
    ]
    counts = asr_scoring.wer_counts(ref_segments, hyp, [])
    r_toks, h_toks = _timed_tokens(ref), _timed_tokens(hyp)
    out: dict[str, Any] = {"ref_words": counts["ref_words"], "wer": asr_scoring.wer_of(counts)}
    out["cer"] = (
        jiwer.cer(" ".join(t[0] for t in r_toks), " ".join(t[0] for t in h_toks) or " ")
        if r_toks
        else None
    )

    deltas: list[int] = []
    speakers: list[tuple[str, str]] = []
    if r_toks and h_toks:
        aligned = jiwer.process_words(
            " ".join(t[0] for t in r_toks), " ".join(t[0] for t in h_toks)
        )
        for chunk in aligned.alignments[0]:
            if chunk.type != "equal":
                continue
            for i, j in zip(
                range(chunk.ref_start_idx, chunk.ref_end_idx),
                range(chunk.hyp_start_idx, chunk.hyp_end_idx),
                strict=True,
            ):
                deltas.append(abs(h_toks[j][1] - r_toks[i][1]))
                if r_toks[i][3] and h_toks[j][3]:
                    speakers.append((r_toks[i][3], h_toks[j][3]))
    out["ts_matched"] = len(deltas)
    out["ts_median_ms"] = statistics.median(deltas) if deltas else None
    out["ts_p90_ms"] = statistics.quantiles(deltas, n=10)[-1] if len(deltas) >= 2 else None
    out["speaker_agreement"] = _speaker_agreement(speakers)

    ref_spans = [(t[1], t[2]) for t in r_toks]
    out["hallucinated_segments"] = sum(
        1
        for s in hyp.segments
        if s.text.strip() and not any(a < s.end_ms and s.start_ms < b for a, b in ref_spans)
    )
    out.update(_switches(hyp, passages or []))
    return out


def _result(note: Any, asr: Any, run_id: str) -> dict[str, Any]:
    run = note.get(f"/v1/telemetry/runs/{run_id}").raise_for_status().json()["processing_run"]
    return asr.get(f"/asr/jobs/{run['recording_id']}/result").raise_for_status().json()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("ref", help="freeze a run's transcript as the reference (outside the repo)")
    r.add_argument("--run-id", required=True)
    r.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score", help="score a run against a reference")
    s.add_argument("--run-id", required=True)
    s.add_argument("--reference", type=Path, required=True)
    s.add_argument("--switches", type=Path)
    s.add_argument("--sprint")
    s.add_argument("--condition")
    s.add_argument("--recording")
    a = p.parse_args()

    asr, note = bench.clients(bench.login())
    result = _result(note, asr, a.run_id)
    if a.cmd == "ref":
        out = a.out.expanduser().resolve()
        if out.is_relative_to(bench.REPO):
            raise SystemExit("references hold transcript text: keep them outside the repo")
        out.parent.mkdir(parents=True, exist_ok=True)
        keep = ("text", "start_ms", "end_ms", "speaker", "language", "words")
        segments = [{k: seg.get(k) for k in keep} for seg in result["segments"]]
        out.write_text(json.dumps({"language": result.get("language"), "segments": segments}))
        print(f"reference written: {out}")
        return
    reference = json.loads(a.reference.expanduser().read_text())
    passages = json.loads(a.switches.expanduser().read_text()) if a.switches else []
    row = {"run_id": a.run_id, "recording": a.recording, "condition": a.condition}
    row.update(score(reference, result, passages))
    print(json.dumps(row))
    if a.sprint and a.condition:
        bench.append_csv(
            bench.EVIDENCE / a.sprint / a.condition / "quality.csv", row, QUALITY_FIELDS
        )


if __name__ == "__main__":
    main()
