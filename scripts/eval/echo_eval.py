#!/usr/bin/env python3
"""Sprint I2 T7 — measure the prompt-echo guard and other-language decoding
before shipping.

    MD_ASR_DEVICE=cpu MD_ASR_COMPUTE_TYPE=int8 uv run --project services/asr-worker \\
        python scripts/eval/echo_eval.py --audio a.wav --audio b.flac \\
        --mixed mixed_en_uk.wav --incident-job <uuid> --out docs/eval/asr-echo-<date>.json

Four configurations of the in-process engine on the same files, one model
load: ``today`` (conditioning on, guard measured but not applied), ``guard``
(the lexical guard applied), ``guard_nocond`` (+ `condition_on_previous_text`
off, the proposed default) and ``guard_nocond_hotwords`` (vocabulary as
faster-whisper `hotwords` instead of `initial_prompt`).

Reports, per file and configuration: audio seconds, words, words the guard
removes (per audio hour), segments it drops, other-language chunks, and for
the mixed-language fixture precision/recall of the `uk` label against the
known spans; for the incident recording whether any of the seven glossary
names survive. WER is **not** computed — no reference transcripts are in
the repo; the report says so. Transcript text goes only to
``scripts/eval/local/echo-<config>/`` (gitignored) for the PR diff; the JSON
report carries counts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

os.environ.setdefault("MD_ASR_DEVICE", "cpu")
os.environ.setdefault("MD_ASR_COMPUTE_TYPE", "int8")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("TESTING", "true")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "asr-worker" / "src"))
sys.path.insert(0, str(REPO / "scripts" / "eval"))

from _common import git_sha, host_info  # noqa: E402

LOCAL = REPO / "scripts" / "eval" / "local"

CONFIGS: dict[str, dict[str, Any]] = {
    "today": {"guard": False, "condition_prev": True, "mode": "prompt"},
    "guard": {"guard": True, "condition_prev": True, "mode": "prompt"},
    "guard_nocond": {"guard": True, "condition_prev": False, "mode": "prompt"},
    "guard_nocond_hotwords": {"guard": True, "condition_prev": False, "mode": "hotwords"},
}

# A 40-term vocabulary of the kind a busy workspace carries: names, products,
# a few role labels from before the I2 rule. Nothing here is in any recording.
FORTY_TERMS = (
    "Gregor Gysi, Moderator, Moderator II, moderatorin, narrator, speaker, speaker background, "
    "Springbrook Marine, Williams Jet Tender, Pardo, IPS 1350, Volvo Penta, Mitchell, "
    "Quorvex, Blandimar, Zeltrovane, Pellucidor, Anneke Vos, Tobias Renner, Halvard Lie, "
    "Lantern Edition, Quillhaven, Ferrytale, Northwind Logistics, Kestrel Bay, Orrin Sable, "
    "Delphine Marchetti, Yusuf Demir, Priya Natarajan, Marek Zielinski, Solvei Hagen, "
    "Bramwell Court, Ostrova Capital, Kaleido Labs, Tern Harbour, Vireo Systems, "
    "Cobalt Reach, Halden Rowe, Ines Okafor, Rafael Quintero"
)
INCIDENT_NAMES = ("gysi", "moderator", "narrator", "speaker background", "moderatorin")

# The mixed fixture's Ukrainian spans (ms), from how it was built.
MIXED_UK_SPANS = [(19_900, 30_310), (43_580, 48_960)]


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _uk_quality(segments: list[Any]) -> dict[str, float]:
    """Precision/recall of the `uk` label by time: labelled time inside the
    known Ukrainian spans over labelled time (precision) and over the spans'
    total (recall)."""
    labelled = [(s.start_ms, s.end_ms) for s in segments if s.language == "uk"]
    labelled_ms = sum(e - b for b, e in labelled)
    hit = sum(_overlap(span, ref) for span in labelled for ref in MIXED_UK_SPANS)
    total = sum(e - b for b, e in MIXED_UK_SPANS)
    return {
        "precision": round(hit / labelled_ms, 3) if labelled_ms else 0.0,
        "recall": round(hit / total, 3),
        "labelled_segments": len(labelled),
    }


async def _incident_audio(job_id: UUID) -> bytes:
    """The incident recording, decrypted through the worker's own store."""
    from asr_worker import main_deps
    from asr_worker.config import settings as worker_settings

    dsn = "postgresql://{u}:{u}@localhost:5432/notes"
    worker_settings.db_app_role_dsn = dsn.format(u="app_role")
    worker_settings.db_audit_writer_dsn = dsn.format(u="audit_writer")
    worker_settings.db_crypto_writer_dsn = dsn.format(u="crypto_writer")
    worker_settings.redis_url = "redis://localhost:6379/0"
    worker_settings.s3_endpoint = "http://localhost:9000"
    worker_settings.master_key_path = str(REPO / "infra" / "dev" / "master.key")
    main_deps.build_asr = lambda _name: _NullEngine()  # type: ignore[assignment]
    state = await main_deps.build_state()
    try:
        # The job row is behind RLS; the dev superuser reads it (this script
        # runs on the dev stack only). The audio is still decrypted through
        # the worker's own store, tenant-bound.
        import asyncpg

        su = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/notes")
        try:
            row = await su.fetchrow(
                "SELECT tenant_id, audio_id FROM transcription_jobs WHERE id = $1", job_id
            )
        finally:
            await su.close()
        if row is None:
            raise SystemExit(f"job {job_id} not found")
        key = f"{row['tenant_id']}/{row['audio_id']}.enc"
        return await state.audio_store.get(
            key=key, tenant_id=row["tenant_id"], aad=row["audio_id"].bytes
        )
    finally:
        await main_deps.teardown_state(state)


class _NullEngine:
    backend = "null"
    model_name = "null"
    is_loaded = True
    warmup_seconds = 0.0

    async def warm_up(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


async def main(args: argparse.Namespace) -> int:
    from asr_worker import inference
    from asr_worker.audio_io import decode_to_pcm
    from asr_worker.config import settings
    from asr_worker.echo import guard_segments

    files: list[tuple[str, bytes, str]] = []  # (name, bytes, kind)
    for path in args.audio:
        files.append((Path(path).stem, Path(path).read_bytes(), "corpus"))
    if args.mixed:
        files.append((Path(args.mixed).stem, Path(args.mixed).read_bytes(), "mixed"))
    if args.incident_job:
        files.append(("incident", await _incident_audio(UUID(args.incident_job)), "incident"))
    if not files:
        print("nothing to measure", file=sys.stderr)
        return 2

    pcms = {name: await decode_to_pcm(data) for name, data, _kind in files}
    kinds = {name: kind for name, _data, kind in files}
    engine = inference.WhisperEngine()
    t0 = time.monotonic()
    engine.load()
    print(f"model {settings.asr_model} loaded in {time.monotonic() - t0:.0f}s")

    prompt = args.prompt or FORTY_TERMS
    report: dict[str, Any] = {
        "model": settings.asr_model,
        "device": settings.asr_device,
        "compute_type": settings.asr_compute_type,
        "prompt_terms": sum(1 for p in prompt.split(",") if p.strip()),
        "wer": None,
        "wer_note": "no reference transcripts in the repo; not computable",
        "configs": {},
    }
    for config, opts in CONFIGS.items():
        settings.asr_condition_prev = opts["condition_prev"]
        settings.asr_vocabulary_mode = opts["mode"]
        rows: dict[str, Any] = {}
        out_dir = LOCAL / f"echo-{config}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, pcm in pcms.items():
            started = time.monotonic()
            output = await engine.transcribe(pcm, language="auto", prompt=prompt)
            elapsed = time.monotonic() - started
            audio_s = len(pcm) / 16_000
            kept, spans, dropped = guard_segments(output.segments, prompt)
            shipped = kept if opts["guard"] else output.segments
            echo_words = sum(s.words for s in spans)
            row: dict[str, Any] = {
                "kind": kinds[name],
                "audio_seconds": round(audio_s, 1),
                "language": output.language,
                "seconds": round(elapsed, 1),
                "segments": len(output.segments),
                "words": sum(len(s.text.split()) for s in shipped),
                "echo_words_found": echo_words,
                "echo_words_per_hour": round(echo_words / (audio_s / 3600), 1),
                "echo_segments_dropped": dropped,
                "echo_applied": opts["guard"],
                "other_language_chunks": output.diagnostics.other_language_chunks,
            }
            if kinds[name] == "mixed":
                row["uk"] = _uk_quality(output.segments)
                # No English sentence may stand where Ukrainian was spoken.
                row["english_over_uk_spans"] = sum(
                    1
                    for s in shipped
                    if s.language is None
                    and any(_overlap((s.start_ms, s.end_ms), r) > 1_500 for r in MIXED_UK_SPANS)
                )
            if kinds[name] == "incident":
                text = " ".join(s.text for s in shipped).casefold()
                row["incident_names_present"] = sorted(n for n in INCIDENT_NAMES if n in text)
            rows[name] = row
            (out_dir / f"{name}.txt").write_text(
                "\n".join(
                    f"[{s.start_ms // 1000:>4}s]{' [' + s.language + ']' if s.language else ''} {s.text}"
                    for s in shipped
                )
                + "\n",
                encoding="utf-8",
            )
            print(
                f"  {config:<22} {name:<16} {elapsed:6.0f}s  "
                + json.dumps(
                    {
                        k: row[k]
                        for k in (
                            "echo_words_per_hour",
                            "echo_segments_dropped",
                            "other_language_chunks",
                        )
                    }
                )
            )
        hours = sum(r["audio_seconds"] for r in rows.values()) / 3600
        report["configs"][config] = {
            **opts,
            "files": rows,
            "echo_words_per_hour": round(
                sum(r["echo_words_found"] for r in rows.values()) / hours, 1
            ),
        }
    payload = {
        "kind": "asr-echo",
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_sha(),
        "host": host_info(),
        **report,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--audio", action="append", default=[], help="corpus file (wav/flac)")
    ap.add_argument("--mixed", help="the mixed en/uk fixture")
    ap.add_argument("--incident-job", help="job id whose stored audio to re-run (dev stack)")
    ap.add_argument("--prompt", help="vocabulary hint (default: the 40-term list)")
    ap.add_argument("--out", type=Path, required=True)
    sys.exit(asyncio.run(main(ap.parse_args())))
