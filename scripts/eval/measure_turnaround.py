#!/usr/bin/env python3
"""DEP-S0 ASR turnaround: wall-clock ÷ audio length for one fixture on one backend.

    make measure-turnaround FIXTURE=10min_de BACKEND=dev_mac_asr
    make measure-turnaround FIXTURE=10min_de BACKEND=inproc_cpu_asr   # faster-whisper on this CPU
    ENV=staging make measure-turnaround FIXTURE=60min_de BACKEND=hf_eu_asr

Fixtures live in tests/fixtures/eval/audio/<name>.wav (16 kHz mono 16-bit).
They are generated, not committed — `scripts/eval/make_tts_fixture.sh` builds
synthetic German/English speech with macOS TTS so the number is reproducible
on any Mac. Output: docs/eval/turnaround-<date>-<backend>-<fixture>.json with
`turnaround_ratio` (the A2 gate quantity: ≤ 0.08× meeting length), word
count, words-with-timings share and the backend/model that produced it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from _common import REPO, load_registry, write_report

AUDIO = REPO / "tests" / "fixtures" / "eval" / "audio"


class _CpuEngineFactory:
    """Build asr-worker's WhisperEngine for the inproc backend (dev Mac only)."""

    @staticmethod
    def build(model: str, compute_type: str) -> Any:
        os.environ.setdefault("MD_ASR_DEVICE", "cpu")
        os.environ.setdefault("MD_ASR_MODEL", model)
        os.environ.setdefault("MD_ASR_COMPUTE_TYPE", compute_type)
        os.environ.setdefault("TESTING", "true")
        sys.path.insert(0, str(REPO / "services" / "asr-worker" / "src"))
        from asr_worker.inference import WhisperEngine  # noqa: PLC0415

        return WhisperEngine()


async def run(
    fixture: str, backend_name: str, language: str, cpu_model: str, cpu_compute: str
) -> int:
    from models import build_asr_provider
    from models.audio import wav_file_to_pcm

    path = AUDIO / f"{fixture}.wav"
    if not path.is_file():
        print(
            f"fixture missing: {path}\n  build it: scripts/eval/make_tts_fixture.sh {fixture}",
            file=sys.stderr,
        )
        return 2
    pcm = wav_file_to_pcm(path)
    audio_seconds = len(pcm) / 16_000

    registry = load_registry()
    resolved = registry.backend(backend_name, expect_kind="asr")
    engine = (
        _CpuEngineFactory.build(cpu_model, cpu_compute) if resolved.kind == "asr_inproc" else None
    )
    provider = build_asr_provider(resolved, inproc_engine=engine)
    print(
        f"backend={resolved.name} model={provider.model_name if engine is None else cpu_model} fixture={fixture} audio={audio_seconds / 60:.1f} min"
    )

    t0 = time.monotonic()
    await provider.warm_up()
    warm = time.monotonic() - t0
    print(f"warm-up {warm:.1f}s")

    t1 = time.monotonic()
    out = await provider.transcribe(pcm, language=language, prompt=None)
    wall = time.monotonic() - t1
    await provider.aclose()

    words = [w for s in out.segments for w in s.words]
    timed = sum(1 for w in words if w.end_ms > w.start_ms)
    ratio = wall / audio_seconds if audio_seconds else None
    payload = {
        "fixture": fixture,
        "language_requested": language,
        "language_out": out.language,
        "audio_seconds": round(audio_seconds, 1),
        "wall_seconds": round(wall, 1),
        "warmup_seconds": round(warm, 1),
        "turnaround_ratio": round(ratio, 4) if ratio else None,
        "segments": len(out.segments),
        "words": len(words),
        "words_with_timings_share": round(timed / len(words), 3) if words else 0.0,
        "model_id": out.metadata.model,
        "backend_kind": resolved.kind,
        "processor": resolved.processor.model_dump() if resolved.processor else None,
        "a2_gate_pass": bool(ratio is not None and ratio <= 0.08),
    }
    report = write_report("turnaround", backend_name, payload, suffix=f"-{fixture}")
    print(
        f"turnaround {ratio:.3f}× ({wall:.0f}s for {audio_seconds:.0f}s audio); {len(words)} words, {payload['words_with_timings_share']:.0%} timed; A2 (≤0.08×): {'pass' if payload['a2_gate_pass'] else 'FAIL'}; report → {report.relative_to(REPO)}"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--fixture", required=True, help="name under tests/fixtures/eval/audio/, e.g. 10min_de"
    )
    ap.add_argument("--backend", required=True, help="asr backend from config/models.yaml")
    ap.add_argument(
        "--language", default=None, help="ISO code; default from the fixture name suffix (_de → de)"
    )
    ap.add_argument(
        "--cpu-model",
        default="tiny",
        help="faster-whisper model for inproc_cpu_asr (tiny|base|small|large-v3)",
    )
    ap.add_argument("--cpu-compute", default="int8")
    args = ap.parse_args()
    language = args.language or (args.fixture.rsplit("_", 1)[-1] if "_" in args.fixture else "auto")
    return asyncio.run(run(args.fixture, args.backend, language, args.cpu_model, args.cpu_compute))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
