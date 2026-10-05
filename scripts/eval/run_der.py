"""Speaker-count accuracy + DER/JER of the batch diarizer on the speaker gold set,
through the production code path (not HTTP).

    make der-eval ENGINE=legacy SPLIT=test

Engines: ``legacy``, ``legacy:<json overrides>``, ``pyannote_c1``; any engine takes
``guard_speech_ms`` / ``guard_share`` and ``"hint": "oracle"``.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import REPO, write_report  # noqa: E402

MANIFEST = REPO / "eval" / "speakers" / "v1" / "manifest.json"
AUDIO_DIR = REPO / "eval" / "speakers" / "v1" / "audio"
SAMPLE_RATE = 16_000
# 2 under --dual: items carry int16 (n, 2) PCM.
DECODE_CHANNELS = 1


# ── Engine output ─────────────────────────────────────────────────────


@dataclass
class Hypothesis:
    """(start_s, end_s, label) turns; ``unknown_share`` if the engine knows it."""

    turns: list[tuple[float, float, str]]
    speakers: int
    unknown_share: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


Engine = Callable[[Any], Hypothesis]


# ── Legacy engine ─────────────────────────────────────────────────────


# Knobs every engine understands (the production seam):
#   guard_speech_ms / guard_share — roster guard floor (MDX_DIAR_MIN_SPEAKER_*)
#   hint: "oracle" — pass the gold speaker count as a person-stated count (E2)
HARNESS_KEYS = ("guard_speech_ms", "guard_share", "hint")


def seam_options(config: dict[str, Any]) -> tuple[Any, Any]:
    """(RosterGuardConfig | None, hint) from harness keys; hint is None,
    "oracle", or "max+K" (a calendar-style cap K above the gold count)."""
    from diarization import RosterGuardConfig

    hint = config.get("hint")
    if hint not in (None, "oracle") and not (
        isinstance(hint, str) and hint.startswith("max+") and hint[4:].isdigit()
    ):
        raise SystemExit('hint must be "oracle" or "max+K"')
    roster = None
    if "guard_speech_ms" in config or "guard_share" in config:
        roster = RosterGuardConfig(
            min_speaker_speech_ms=int(config.get("guard_speech_ms", 0)),
            min_speaker_share=float(config.get("guard_share", 0.0)),
        )
    return roster, hint


def hints_for(item: Any, hint: Any) -> Any:
    """The hint a person (oracle) or a calendar (max+K, Sprint 30 C2) would give."""
    from diarization import DiarizationHints

    n = int(item.entry["n_speakers"])
    if hint == "oracle":
        return DiarizationHints(num_speakers=n)
    if isinstance(hint, str) and hint.startswith("max+"):
        return DiarizationHints(max_speakers=min(8, n + int(hint[4:])))
    return DiarizationHints()


def legacy_configs(overrides: dict[str, Any]) -> tuple[Any, float | None]:
    """Split flat overrides into an ``OfflineDiarizationConfig`` + VAD threshold."""
    from diarization import OfflineClusteringConfig, OfflineDiarizationConfig

    overrides = dict(overrides)
    vad_threshold = overrides.pop("vad_threshold", None)
    for key in HARNESS_KEYS:
        overrides.pop(key, None)
    top = {f.name for f in fields(OfflineDiarizationConfig)}
    clustering = {f.name for f in fields(OfflineClusteringConfig)}
    unknown = set(overrides) - top - clustering
    if unknown:
        raise SystemExit(f"unknown legacy overrides: {sorted(unknown)}")
    cfg = OfflineDiarizationConfig(**{k: v for k, v in overrides.items() if k in top})
    cfg = replace(
        cfg,
        offline_clustering=replace(
            cfg.offline_clustering, **{k: v for k, v in overrides.items() if k in clustering}
        ),
    )
    return cfg, vad_threshold


class LegacyModels:
    """ECAPA + Silero loaded once; embeddings cached per (file, chunking, VAD)."""

    def __init__(self) -> None:
        from diarization import DiarizationEngine

        model_dir = os.environ.get(
            "MDX_DIAR_MODEL_DIR", str(Path.home() / ".cache" / "mdx-models" / "ecapa-voxceleb")
        )
        self._engine = DiarizationEngine(model_dir=model_dir)
        self._segmenters: dict[float | None, Any] = {}
        self._cache: dict[tuple[str, int, int, float | None], Any] = {}

    def embeddings(self, file_id: str, pcm: Any, cfg: Any, vad_threshold: float | None) -> Any:
        import asyncio

        from diarization import SileroSegmenter, embed_chunks

        key = (file_id, cfg.chunk_target_ms, cfg.chunk_min_ms, vad_threshold)
        if key not in self._cache:
            if not self._engine.loaded:
                asyncio.run(self._engine.ensure_loaded())
            segmenter = self._segmenters.setdefault(
                vad_threshold, SileroSegmenter(threshold=vad_threshold)
            )
            self._cache[key] = embed_chunks(
                pcm, embedder=self._engine.embedder, segmenter=segmenter, config=cfg
            )
        return self._cache[key]


def legacy_engine(overrides: dict[str, Any], models: LegacyModels | None = None) -> Engine:
    from diarization import UNKNOWN, diarize_embeddings

    cfg, vad_threshold = legacy_configs(overrides)
    roster, oracle = seam_options(overrides)
    shared = models or LegacyModels()

    def run(item: Any) -> Hypothesis:
        spans, embeddings = shared.embeddings(item.file_id, item.pcm, cfg, vad_threshold)
        diar = diarize_embeddings(
            spans,
            embeddings,
            duration_ms=len(item.pcm) * 1000 // SAMPLE_RATE,
            config=cfg,
            hints=hints_for(item, oracle),
            roster=roster,
        )
        evidence = diar.segments
        speech = sum(s.end_ms - s.start_ms for s in evidence)
        unknown = sum(s.end_ms - s.start_ms for s in evidence if s.label == UNKNOWN)
        return Hypothesis(
            turns=[(t.start_ms / 1000, t.end_ms / 1000, t.speaker) for t in diar.turns],
            speakers=len(diar.speakers),
            unknown_share=unknown / speech if speech else 0.0,
            extra={
                "clusters_raw": diar.stats.clusters_raw,
                "clusters_dropped": diar.stats.clusters_dropped,
                "count_confidence": diar.count_confidence,
            },
        )

    return run


def dual_engine(overrides: dict[str, Any]) -> Engine:
    """``--dual``: 2-channel files through ``diarize_dual`` plus the mono downmix through the
    ordinary path. Side accuracy needs ``rttm/<id>.sides.json``.
    """
    import asyncio

    import numpy as np

    from diarization import LegacyEcapaDiarizer, SileroSegmenter, diarize_dual

    cfg, _ = legacy_configs(overrides)
    roster, hint = seam_options(overrides)
    diarizer = LegacyEcapaDiarizer(
        model_dir=os.environ.get(
            "MDX_DIAR_MODEL_DIR", str(Path.home() / ".cache" / "mdx-models" / "ecapa-voxceleb")
        ),
        offline_config=cfg,
        roster=roster,
    )
    asyncio.run(diarizer.ensure_loaded())
    segmenter = SileroSegmenter()

    def run(item: Any) -> Hypothesis:
        mic, system = item.pcm[:, 0], item.pcm[:, 1]
        hints = hints_for(item, hint)
        diar = diarize_dual(mic, system, diarizer=diarizer, hints=hints, segmenter=segmenter)
        mono = diarizer.diarize(
            ((mic.astype(np.float32) + system.astype(np.float32)) / 65536.0).astype(np.float32),
            SAMPLE_RATE,
            hints=hints,
        )
        turns = [(t.start_ms / 1000, t.end_ms / 1000, t.speaker) for t in diar.turns]
        extra: dict[str, Any] = {
            "sides": diar.sides,
            "mono_speakers": len(mono.speakers),
            "mono_count_exact": len(mono.speakers) == item.entry["n_speakers"],
        }
        sides_ref = item.entry.get("_sides")
        if sides_ref and item.reference:
            extra.update(side_scores(item.reference, turns, sides_ref, diar.sides))
        return Hypothesis(turns=turns, speakers=len(diar.speakers), extra=extra)

    return run


def side_scores(
    reference: list[tuple[float, float, str]],
    hypothesis: list[tuple[float, float, str]],
    ref_sides: dict[str, str],
    hyp_sides: dict[str, str],
) -> dict[str, Any]:
    """Side accuracy on 20 ms frames where exactly one reference speaker
    talks (double-talk excluded, as the acceptance criterion says), plus
    whether any remote frame carries a local label."""
    step = 0.02
    end = max([e for _, e, _ in reference] + [0.0])
    right = total = crossed = 0
    t = 0.0
    while t < end:
        refs = [lab for a, b, lab in reference if a <= t < b]
        hyps = [lab for a, b, lab in hypothesis if a <= t < b]
        if len(refs) == 1 and hyps:
            truth = ref_sides.get(refs[0])
            guess = hyp_sides.get(hyps[0])
            if truth and guess:
                total += 1
                right += truth == guess
                crossed += truth == "remote" and guess == "local"
        t += step
    return {
        "side_accuracy": round(right / total, 4) if total else None,
        "remote_frames_labelled_local": crossed,
    }


def build_engine(spec: str) -> tuple[str, Engine, dict[str, Any]]:
    """``legacy`` | ``legacy:{json}`` | ``pyannote_c1[:{json}]`` → (name, run, config)."""
    name, _, raw = spec.partition(":")
    config = json.loads(raw) if raw else {}
    if name == "legacy":
        return ("legacy" if not config else "legacy_custom"), legacy_engine(config), config
    if name == "pyannote_c1":
        from engines import pyannote_c1

        return name, pyannote_c1.engine(config), config
    raise SystemExit(f"unknown engine {name!r}")


# ── Data ──────────────────────────────────────────────────────────────


@dataclass
class Item:
    file_id: str
    entry: dict[str, Any]
    pcm: Any
    reference: list[tuple[float, float, str]] | None


def decode(path: Path, channels: int = 1) -> Any:
    """Same ffmpeg arguments as ``asr_worker.audio_io.decode_to_pcm``
    (``channels=2``: int16 ``(n, 2)``, ch0 mic / ch1 call audio)."""
    import numpy as np

    out = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ac",
            str(channels),
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "f32le" if channels == 1 else "s16le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    if channels == 2:
        stereo = np.frombuffer(out.stdout, dtype=np.int16)
        return stereo[: len(stereo) // 2 * 2].reshape(-1, 2).copy()
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def read_rttm(path: Path) -> list[tuple[float, float, str]]:
    turns = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0] == "SPEAKER":
            start, dur = float(parts[3]), float(parts[4])
            turns.append((start, start + dur, parts[7]))
    return turns


def audio_path(entry: dict[str, Any], audio_dir: Path) -> Path:
    suffix = Path(entry["audio_uri"]).suffix or ".flac"
    return audio_dir / f"{entry['id']}{suffix}"


def load_entries(manifest: Path, split: str) -> list[dict[str, Any]]:
    data = json.loads(manifest.read_text())
    return [e for e in data["files"] if split == "all" or e["split"] == split]


def load_asr_corpus(corpus: Path, split: str) -> list[dict[str, Any]]:
    """The ASR gold set's recordings as DER entries (``<corpus>/<id>/reference.rttm``), language kept."""
    data = json.loads((corpus / "manifest.json").read_text())
    out: list[dict[str, Any]] = []
    for row in data["recordings"]:
        if split != "all" and row["split"] != split:
            continue
        folder = corpus / row["id"]
        audio = sorted(folder.glob("audio.*"))
        out.append(
            {
                "id": row["id"],
                "split": row["split"],
                "n_speakers": row["speakers"],
                "condition": f"asr-{row['language']}",
                "language": row["language"],
                "_audio": str(audio[0]) if audio else str(folder / "audio.missing"),
                "_rttm": str(folder / "reference.rttm"),
            }
        )
    return out


# ── Metrics ───────────────────────────────────────────────────────────


def count_metrics(pred: int, true: int) -> dict[str, Any]:
    return {
        "count_pred": pred,
        "count_true": true,
        "count_exact": pred == true,
        "count_abs_err": abs(pred - true),
        "overcount": pred > true,
        "undercount": pred < true,
    }


def extra_speaker_share(turns: list[tuple[float, float, str]], true: int) -> list[float]:
    """Speech share of each label beyond the true count (smallest first)."""
    talk: dict[str, float] = defaultdict(float)
    for start, end, label in turns:
        talk[label] += end - start
    total = sum(talk.values())
    if len(talk) <= true or not total:
        return []
    shares = sorted(v / total for v in talk.values())
    return [round(s, 4) for s in shares[: len(talk) - true]]


def _annotation(turns: list[tuple[float, float, str]]) -> Any:
    from pyannote.core import Annotation, Segment

    ann = Annotation()
    for i, (start, end, label) in enumerate(turns):
        if end > start:
            ann[Segment(start, end), i] = label
    return ann


def der_metrics(
    reference: list[tuple[float, float, str]], hypothesis: list[tuple[float, float, str]]
) -> dict[str, Any]:
    """DER collar 0 / overlap scored (headline), DER collar 0.25 / no overlap, JER."""
    from pyannote.metrics.diarization import DiarizationErrorRate, JaccardErrorRate

    ref, hyp = _annotation(reference), _annotation(hypothesis)
    strict = DiarizationErrorRate(collar=0.0, skip_overlap=False)(ref, hyp, detailed=True)
    lenient = DiarizationErrorRate(collar=0.25, skip_overlap=True)(ref, hyp)
    jer = JaccardErrorRate(collar=0.0, skip_overlap=False)(ref, hyp)
    total = strict["total"] or 1.0
    return {
        "der": round(strict["diarization error rate"], 4),
        "der_collar025_nooverlap": round(lenient, 4),
        "jer": round(jer, 4),
        "missed_share": round(strict["missed detection"] / total, 4),
        "scored_seconds": round(strict["total"], 2),
        "der_error_seconds": round(
            strict["missed detection"] + strict["false alarm"] + strict["confusion"], 2
        ),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"files": 0}
    n = len(rows)
    scored = [r for r in rows if "der" in r]
    total = sum(r["scored_seconds"] for r in scored)
    out: dict[str, Any] = {
        "files": n,
        "count_exact": round(sum(r["count_exact"] for r in rows) / n, 4),
        "count_within_1": round(sum(r["count_abs_err"] <= 1 for r in rows) / n, 4),
        "count_abs_err": round(sum(r["count_abs_err"] for r in rows) / n, 4),
        "overcount": round(sum(r["overcount"] for r in rows) / n, 4),
        "undercount": round(sum(r["undercount"] for r in rows) / n, 4),
        "rtf": round(sum(r["rtf"] for r in rows) / n, 4),
    }
    unknown = [r["unknown_share"] for r in rows if r.get("unknown_share") is not None]
    if unknown:
        out["unknown_share"] = round(sum(unknown) / len(unknown), 4)
    if scored and total:
        out["der"] = round(sum(r["der_error_seconds"] for r in scored) / total, 4)
        out["jer"] = round(sum(r["jer"] for r in scored) / len(scored), 4)
        out["der_files"] = len(scored)
    return out


def evaluate(
    run: Engine, entries: list[dict[str, Any]], audio_dir: Path, *, log: bool = True
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for entry in entries:
        path = Path(entry["_audio"]) if "_audio" in entry else audio_path(entry, audio_dir)
        if not path.exists():
            missing.append(entry["id"])
            continue
        rttm = entry.get("rttm")
        reference = read_rttm(REPO / "eval" / "speakers" / "v1" / rttm) if rttm else None
        if "_rttm" in entry:
            rttm = None  # the ASR corpus has no stereo sides files
            reference = read_rttm(Path(entry["_rttm"])) if Path(entry["_rttm"]).exists() else None
        if rttm and DECODE_CHANNELS == 2:
            sides = (REPO / "eval" / "speakers" / "v1" / rttm).with_suffix(".sides.json")
            if sides.is_file():
                entry = {**entry, "_sides": json.loads(sides.read_text())}
        item = Item(entry["id"], entry, decode(path, DECODE_CHANNELS), reference)
        duration = len(item.pcm) / SAMPLE_RATE
        t0 = time.monotonic()
        hyp = run(item)
        wall = time.monotonic() - t0
        row: dict[str, Any] = {
            "id": entry["id"],
            "n_speakers": entry["n_speakers"],
            "condition": entry["condition"],
            "duration_s": round(duration, 2),
            **count_metrics(hyp.speakers, entry["n_speakers"]),
            "extra_speaker_share": extra_speaker_share(hyp.turns, entry["n_speakers"]),
            "wall_seconds": round(wall, 3),
            "rtf": round(wall / duration, 4) if duration else 0.0,
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1)
            if sys.platform == "darwin"
            else round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            **hyp.extra,
        }
        if reference is not None:
            row.update(der_metrics(reference, hyp.turns))
        row["unknown_share"] = (
            round(hyp.unknown_share, 4)
            if hyp.unknown_share is not None
            else row.get("missed_share")
        )
        rows.append(row)
        if log:
            print(
                f"  {entry['id']}: {hyp.speakers}/{entry['n_speakers']} speakers"
                + (f", DER {row['der']:.3f}" if "der" in row else "")
                + f", RTF {row['rtf']:.3f}",
                file=sys.stderr,
            )
    return rows, missing


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_n: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_cond: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_n[str(r["n_speakers"])].append(r)
        by_cond[r["condition"]].append(r)
    return {
        "overall": aggregate(rows),
        "by_n_speakers": {k: aggregate(v) for k, v in sorted(by_n.items())},
        "by_condition": {k: aggregate(v) for k, v in sorted(by_cond.items())},
    }


def markdown(summary: dict[str, Any]) -> str:
    cols = (
        "files",
        "count_exact",
        "count_within_1",
        "overcount",
        "undercount",
        "der",
        "jer",
        "unknown_share",
        "rtf",
    )
    lines = ["| group | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]

    def row(name: str, agg: dict[str, Any]) -> str:
        return f"| {name} | " + " | ".join(str(agg.get(c, "—")) for c in cols) + " |"

    lines.append(row("**overall**", summary["overall"]))
    lines += [row(f"{k} spk", v) for k, v in summary["by_n_speakers"].items()]
    lines += [row(k, v) for k, v in summary["by_condition"].items()]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", default="legacy")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="an ASR gold corpus (eval/asr/v1) instead of the speaker manifest",
    )
    parser.add_argument("--split", default="test", choices=("dev", "test", "all"))
    parser.add_argument("--audio-dir", type=Path, default=AUDIO_DIR)
    parser.add_argument("--only", default="", help="file id prefix filter (e.g. vc-)")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument(
        "--label", default="", help="report name instead of the engine name (e.g. legacy-guard)"
    )
    parser.add_argument(
        "--dual",
        action="store_true",
        help="Sprint 31: 2-channel files through diarize_dual (+ mono A/B); legacy engine only",
    )
    args = parser.parse_args()

    if args.dual:
        eng, _, raw = args.engine.partition(":")
        if eng != "legacy":
            raise SystemExit("--dual supports the legacy engine only for now")
        config = json.loads(raw) if raw else {}
        name, run = "dual-legacy", dual_engine(config)
        global DECODE_CHANNELS
        DECODE_CHANNELS = 2
    else:
        name, run, config = build_engine(args.engine)
    loaded = (
        load_asr_corpus(args.corpus, args.split)
        if args.corpus
        else load_entries(args.manifest, args.split)
    )
    entries = [e for e in loaded if e["id"].startswith(args.only)]
    rows, missing = evaluate(run, entries, args.audio_dir)
    if missing:
        print(
            f"missing audio for {len(missing)} file(s) — run fetch_speaker_corpus.py",
            file=sys.stderr,
        )
    if not rows:
        print("no files evaluated", file=sys.stderr)
        return 1
    summary = summarise(rows)
    print(markdown(summary))
    if not args.no_report:
        path = write_report(
            "der",
            args.label or name,
            {
                "engine": name,
                "config": config,
                "split": args.split,
                "missing": missing,
                **summary,
                "files": rows,
            },
            suffix=f"-{args.split}"
            + (f"-{args.only.strip('-')}" if args.only else "")
            + ("-asr-v1" if args.corpus else ""),
        )
        print(f"\nreport: {path.relative_to(REPO)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
