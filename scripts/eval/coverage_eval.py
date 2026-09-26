#!/usr/bin/env python3
"""Sprint F1 T3 — measure the VAD pad, the floor pass and the second pass
before shipping.

    MD_ASR_DEVICE=cpu MD_ASR_COMPUTE_TYPE=int8 uv run --project services/asr-worker \\
        python scripts/eval/coverage_eval.py --speakers vc-afjiv --speakers vc-ampme \\
        --incident-job <uuid> --out docs/eval/asr-coverage-<date>.json

Four configurations of the in-process engine, one model load, the same files:
``today`` (no pad, no floor, no second pass), ``pad`` (+ 300 ms leading pad),
``pad_floor`` (+ the floor pass) and ``pad_floor_second`` (+ the second pass).
A configuration that cannot change a file's first decode reuses the previous
one's (the floor pass on a file where its condition does not hold), so the
seconds reported are the ones each configuration really costs.

Per file and configuration: audio and inference seconds, words, coverage
share (VAD speech the transcript covers), gaps by cause, second-pass chunks
and recovered words; for speakers-corpus files the share of the RTTM
reference speech within reach of a word (independent of our VAD) and the
word change against ``today``. For the incident recording: the r02
checklist (``tests/fixtures/eval/asr/assertions/``) and the coverage of the
transcript stored before the fix.

**WER is not computable** — the speakers corpus carries RTTM only. The word
change against ``today`` (word edit distance / ``today``'s words) is an upper
bound on how far any configuration's WER can have moved: by the triangle
inequality, |WER(x) − WER(today)| ≤ d(x, today) / |reference|, and the
reference is about as long as ``today``. **DER is not re-measured**: none of
the three changes touches the diarizer's input or labels.

Transcript text goes only to ``scripts/eval/local/coverage-<config>/``
(gitignored); the JSON report carries numbers and check names.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
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

import coverage_assert  # noqa: E402
from _common import git_sha, host_info  # noqa: E402
from echo_eval import FORTY_TERMS, _NullEngine  # noqa: E402

LOCAL = REPO / "scripts" / "eval" / "local"
SPEAKERS = REPO / "eval" / "speakers" / "v1"

CONFIGS: dict[str, dict[str, Any]] = {
    "today": {"pad_ms": 0, "floor": False, "second_pass": False},
    "pad": {"pad_ms": 300, "floor": False, "second_pass": False},
    "pad_floor": {"pad_ms": 300, "floor": True, "second_pass": False},
    "pad_floor_second": {"pad_ms": 300, "floor": True, "second_pass": True},
}
# The incident workspace's vocabulary at the time: role labels, no names
# anyone said (a hint with "Mitchell" in it would make the check pointless).
ROLE_LABELS = "Gysi, Moderator, Moderator II, moderatorin, narrator, speaker, speaker background"

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(segments: list[Any]) -> list[str]:
    return [t.casefold() for s in segments for t in _TOKEN.findall(s.text)]


def _edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _rttm_speech(name: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for line in (SPEAKERS / "rttm" / f"{name}.rttm").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "SPEAKER":
            start = int(float(parts[3]) * 1000)
            spans.append((start, start + int(float(parts[4]) * 1000)))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


async def _incident(job_id: UUID) -> tuple[bytes, bytes | None]:
    """The recording and the transcript stored before the fix, decrypted
    through the worker's own stores (dev stack only)."""
    import asyncpg

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
        su = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/notes")
        try:
            row = await su.fetchrow(
                "SELECT tenant_id, audio_id, result_storage_uri FROM transcription_jobs WHERE id = $1",
                job_id,
            )
        finally:
            await su.close()
        if row is None:
            raise SystemExit(f"job {job_id} not found")
        audio = await state.audio_store.get(
            key=f"{row['tenant_id']}/{row['audio_id']}.enc",
            tenant_id=row["tenant_id"],
            aad=row["audio_id"].bytes,
        )
        stored = None
        if row["result_storage_uri"]:
            # The first artifact, not a re-labelling: `<job>.json.enc`.
            stored = await state.transcript_store.get(
                key=f"{row['tenant_id']}/{job_id}.json.enc",
                tenant_id=row["tenant_id"],
                aad=job_id.bytes,
            )
        return audio, stored
    finally:
        await main_deps.teardown_state(state)


class _Provider:
    """What the processor's second pass calls: the same engine."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def transcribe(self, pcm: Any, **kw: Any) -> Any:
        return await self.engine.transcribe(pcm, **kw)


def _gaps(coverage: Any) -> list[dict[str, Any]]:
    return [
        {
            "start_s": round(g.start_ms / 1000, 1),
            "end_s": round(g.end_ms / 1000, 1),
            "cause": g.cause,
        }
        for g in (coverage.gaps if coverage else [])
    ]


async def main(args: argparse.Namespace) -> int:
    from asr_models import TranscriptionOutput
    from asr_worker import coverage as cov
    from asr_worker import inference, processor, vad
    from asr_worker.audio_io import decode_to_pcm
    from asr_worker.config import settings

    files: list[dict[str, Any]] = []
    for name in args.speakers:
        data = (SPEAKERS / "audio" / f"{name}.wav").read_bytes()
        files.append({"name": name, "kind": "speakers", "bytes": data, "prompt": FORTY_TERMS})
    for path in args.audio:
        files.append(
            {
                "name": Path(path).stem,
                "kind": "corpus",
                "bytes": Path(path).read_bytes(),
                "prompt": FORTY_TERMS,
            }
        )
    stored_before: bytes | None = None
    if args.incident_job:
        audio, stored_before = await _incident(UUID(args.incident_job))
        files.append(
            {"name": "incident", "kind": "incident", "bytes": audio, "prompt": ROLE_LABELS}
        )
    if not files:
        print("nothing to measure", file=sys.stderr)
        return 2
    for f in files:
        f["pcm"] = await decode_to_pcm(f["bytes"])

    engine = inference.WhisperEngine()
    t0 = time.monotonic()
    engine.load()
    print(f"model {settings.asr_model} loaded in {time.monotonic() - t0:.0f}s", flush=True)
    state = type("S", (), {"engine": _Provider(engine)})()

    report: dict[str, Any] = {
        "model": settings.asr_model,
        "device": settings.asr_device,
        "compute_type": settings.asr_compute_type,
        "wer": None,
        "wer_note": "the speakers corpus carries RTTM only; word change vs today bounds the WER delta",
        "der": None,
        "der_note": "none of the changes touches the diarizer's input or labels; not re-measured",
        "configs": {},
    }
    first_pass: dict[tuple[str, str], tuple[Any, float]] = {}
    today_tokens: dict[str, list[str]] = {}
    for config, opts in CONFIGS.items():
        rows: dict[str, Any] = {}
        out_dir = LOCAL / f"coverage-{config}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            name, pcm, prompt = f["name"], f["pcm"], f["prompt"]
            settings.asr_vad_pad_ms = opts["pad_ms"]
            settings.asr_vad_floor_enabled = opts["floor"]
            reuse: str | None = None
            if config == "pad_floor":
                ordinary = vad.speech_runs(pcm).runs
                if not vad.floor_applies(
                    pcm, ordinary, 16_000, max_speech_share=settings.asr_vad_floor_max_speech_share
                ):
                    reuse = "pad"
            elif config == "pad_floor_second":
                reuse = "pad_floor"
            if reuse is not None:
                output, first_seconds = first_pass[(reuse, name)]
                if config == "pad_floor":
                    first_pass[(config, name)] = (output, first_seconds)
            else:
                started = time.monotonic()
                output = await engine.transcribe(pcm, language="auto", prompt=prompt)
                first_seconds = time.monotonic() - started
                first_pass[(config, name)] = (output, first_seconds)
            output = TranscriptionOutput.model_validate(output.model_dump())
            # Coverage is measured the same way in every configuration (floor
            # on for the measurement); only the last one decodes again.
            settings.asr_vad_floor_enabled = True
            settings.asr_second_pass_enabled = opts["second_pass"]
            started = time.monotonic()
            guarded = processor._guarded(output, prompt, job_id=UUID(int=0))
            final = await processor._covered(
                state,
                guarded,
                pcm=pcm,
                stereo=None,
                prompt=prompt,
                first_frame_offset_ms=None,
                deadline=time.monotonic() + 3600,
                should_cancel=None,
                job_id=UUID(int=0),
            )
            second_seconds = time.monotonic() - started
            audio_s = len(pcm) / 16_000
            c = final.diagnostics.coverage
            tokens = _tokens(final.segments)
            if config == "today":
                today_tokens[name] = tokens
            base = today_tokens[name]
            row: dict[str, Any] = {
                "kind": f["kind"],
                "audio_seconds": round(audio_s, 1),
                "seconds": round(first_seconds + second_seconds, 1),
                "first_pass_reused_from": reuse,
                "words": len(tokens),
                "coverage_share": round(c.share, 4) if c else None,
                "speech_ms": c.speech_ms if c else None,
                "transcribed_ms": c.transcribed_ms if c else None,
                "first_speech_s": round(c.first_speech_ms / 1000, 1)
                if c and c.first_speech_ms is not None
                else None,
                "first_segment_s": round(c.first_segment_ms / 1000, 1)
                if c and c.first_segment_ms is not None
                else None,
                "gaps": _gaps(c),
                "second_pass": final.diagnostics.second_pass.model_dump(),
                "word_changes_vs_today": _edit_distance(base, tokens),
                "today_words": len(base),
            }
            if f["kind"] == "speakers":
                ref = _rttm_speech(name)
                ref_ms = sum(e - s for s, e in ref)
                covered = sum(
                    cov.covered_ms(vad.SpeechSegment(s, e), final.segments) for s, e in ref
                )
                row["rttm_speech_ms"] = ref_ms
                row["rttm_coverage"] = round(covered / ref_ms, 4) if ref_ms else None
            if f["kind"] == "incident":
                checks = coverage_assert.check(
                    coverage_assert.load("r02_en_pardo_65gt")["assertions"], final
                )
                row["r02"] = {n: ("PASS" if ok else "FAIL") for n, ok in checks}
            rows[name] = row
            (out_dir / f"{name}.txt").write_text(
                "\n".join(
                    f"[{s.start_ms // 1000:>4}s]{' [' + s.language + ']' if s.language else ''} {s.text}"
                    for s in final.segments
                )
                + "\n",
                encoding="utf-8",
            )
            print(
                f"  {config:<17} {name:<14} {row['seconds']:7.0f}s  cov={row['coverage_share']}"
                f"  gaps={len(row['gaps'])}  sp={row['second_pass']['chunks']}"
                f"  Δwords={row['word_changes_vs_today']}"
                + (f"  rttm={row.get('rttm_coverage')}" if "rttm_coverage" in row else "")
                + (f"  r02={row['r02']}" if "r02" in row else ""),
                flush=True,
            )
        audio_h = sum(r["audio_seconds"] for r in rows.values()) / 3600
        speech = sum(r["speech_ms"] or 0 for r in rows.values())
        spk = [r for r in rows.values() if r["kind"] == "speakers"]
        report["configs"][config] = {
            **opts,
            "files": rows,
            "coverage_share": round(
                sum(r["transcribed_ms"] or 0 for r in rows.values()) / speech, 4
            )
            if speech
            else None,
            "rttm_coverage": round(
                sum(r["rttm_coverage"] * r["rttm_speech_ms"] for r in spk)
                / sum(r["rttm_speech_ms"] for r in spk),
                4,
            )
            if spk
            else None,
            "word_change_vs_today": round(
                sum(r["word_changes_vs_today"] for r in rows.values())
                / max(1, sum(r["today_words"] for r in rows.values())),
                4,
            ),
            "second_pass_chunks_per_audio_hour": round(
                sum(r["second_pass"]["chunks"] for r in rows.values()) / audio_h, 1
            ),
            "seconds_per_audio_hour": round(sum(r["seconds"] for r in rows.values()) / audio_h, 0),
        }
    today_cost = report["configs"]["today"]["seconds_per_audio_hour"]
    for config in CONFIGS:
        report["configs"][config]["inference_vs_today"] = round(
            report["configs"][config]["seconds_per_audio_hour"] / today_cost, 3
        )
    if stored_before is not None:
        before = TranscriptionOutput.model_validate_json(stored_before)
        pcm = next(f["pcm"] for f in files if f["kind"] == "incident")
        runs = vad.speech_runs(pcm, floor=True).runs
        c = cov.measure(runs, before.segments, {}, first_frame_offset_ms=None)
        report["incident_before_fix"] = {
            "coverage_share": round(c.share, 4),
            "first_speech_s": round((c.first_speech_ms or 0) / 1000, 1),
            "first_segment_s": round((c.first_segment_ms or 0) / 1000, 1),
            "gaps": _gaps(c),
            "has_diagnostics": bool(before.diagnostics.prompt_echo)
            or before.diagnostics.coverage is not None,
            "r02": {
                n: ("PASS" if ok else "FAIL")
                for n, ok in coverage_assert.check(
                    coverage_assert.load("r02_en_pardo_65gt")["assertions"],
                    before.model_copy(
                        update={
                            "diagnostics": before.diagnostics.model_copy(update={"coverage": c})
                        }
                    ),
                )
            },
        }
    payload = {
        "kind": "asr-coverage",
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
    ap.add_argument("--speakers", action="append", default=[], help="speakers-corpus file stem")
    ap.add_argument("--audio", action="append", default=[], help="any other file (wav/flac)")
    ap.add_argument("--incident-job", help="job id whose stored audio to re-run (dev stack)")
    ap.add_argument("--out", type=Path, required=True)
    sys.exit(asyncio.run(main(ap.parse_args())))
