"""Bake-off adapter: pyannote ``speaker-diarization-community-1`` (eval-only).

    uv run --with 'pyannote.audio>=4.0,<4.1' --with 'pyannote.metrics>=4,<5' \
        python scripts/eval/run_der.py --engine 'pyannote_c1:{"max_speakers": 8}'

The model is fetched once (gated repo, CC-BY-4.0) into ``PYANNOTE_C1_DIR``
and loaded from that local directory with the hub offline. Telemetry is
forced off before pyannote is imported (4.x ships it enabled).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

MODEL_DIR = Path(
    os.environ.get(
        "PYANNOTE_C1_DIR",
        str(Path.home() / ".cache" / "mdx-models" / "speaker-diarization-community-1"),
    )
)
HINTS = ("num_speakers", "min_speakers", "max_speakers")


def engine(config: dict[str, Any]) -> Any:
    import torch
    from pyannote.audio import Pipeline
    from run_der import HARNESS_KEYS, Hypothesis, hints_for, seam_options

    from diarization import DiarizationHints, OfflineDiarizationConfig
    from diarization.pyannote_engine import extract, to_diarization

    unknown = set(config) - set(HINTS) - {"device"} - set(HARNESS_KEYS)
    if unknown:
        raise SystemExit(f"unknown pyannote_c1 options: {sorted(unknown)}")
    roster, oracle = seam_options(config)
    if not MODEL_DIR.is_dir():
        raise SystemExit(
            f"{MODEL_DIR} missing — fetch the gated model once (see docs/eval/README.md)"
        )
    pipeline = Pipeline.from_pretrained(str(MODEL_DIR))
    device = config.get("device") or ("mps" if torch.backends.mps.is_available() else "cpu")
    pipeline.to(torch.device(device))
    hints = {k: v for k, v in config.items() if k in HINTS}

    def run(item: Any) -> Hypothesis:
        # The production mapping (libs/diarization.pyannote_engine): exclusive
        # timeline, overlap marked, roster guard — what the worker would store.
        seam_hints = hints_for(item, oracle) if oracle else DiarizationHints(**hints)
        call = {
            k: v
            for k, v in (
                ("num_speakers", seam_hints.num_speakers),
                ("min_speakers", seam_hints.min_speakers),
                ("max_speakers", seam_hints.max_speakers),
            )
            if v is not None
        }
        waveform = torch.from_numpy(item.pcm).unsqueeze(0)
        out = pipeline({"waveform": waveform, "sample_rate": 16_000}, **call)
        diar = to_diarization(
            extract(out),
            duration_ms=len(item.pcm) * 1000 // 16_000,
            hints=seam_hints,
            roster=roster,
            config=OfflineDiarizationConfig(),
            engine_version="eval",
        )
        turns = [(t.start_ms / 1000, t.end_ms / 1000, t.speaker) for t in diar.turns]
        return Hypothesis(
            turns=turns,
            speakers=len(diar.speakers),
            extra={"device": device, "count_confidence": diar.count_confidence},
        )

    return run
