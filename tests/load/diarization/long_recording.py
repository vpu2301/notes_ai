"""A 2-hour, 8-speaker recording (two AMI meetings looped) through the production legacy
path; prints speakers found, wall time, wall / audio and peak RSS.

    uv run --project libs/diarization python tests/load/diarization/long_recording.py
"""

from __future__ import annotations

import asyncio
import resource
import subprocess
import time
from pathlib import Path

import numpy as np

from diarization import DiarizationHints, LegacyEcapaDiarizer, RosterGuardConfig

AUDIO = Path("eval/speakers/v1/audio")
MEETINGS = ("ami-ES2004a-mix-headset.wav", "ami-IS1009a-mix-headset.wav")
SECONDS = 7200
RATE = 16_000


def _decode(path: Path) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE)]
        + ["-f", "f32le", "pipe:1"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


def _peak_gb() -> float:
    # macOS reports ru_maxrss in bytes (Linux: KiB — multiply by 1024 there).
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2)


def main() -> None:
    one = np.concatenate([_decode(AUDIO / name) for name in MEETINGS])
    pcm = np.tile(one, int(np.ceil(SECONDS * RATE / len(one))))[: SECONDS * RATE].copy()
    del one
    print("audio_min", round(len(pcm) / RATE / 60, 1), "base_rss_GB", _peak_gb(), flush=True)
    engine = LegacyEcapaDiarizer(
        model_dir=str(Path.home() / ".cache" / "mdx-models" / "ecapa-voxceleb"),
        roster=RosterGuardConfig(),
    )
    asyncio.run(engine.ensure_loaded())
    t0 = time.monotonic()
    diar = engine.diarize(pcm, RATE, hints=DiarizationHints())
    wall = time.monotonic() - t0
    print(
        f"speakers {len(diar.speakers)} wall_s {wall:.1f} ratio {wall / SECONDS:.4f} "
        f"peak_rss_GB {_peak_gb()}",
        flush=True,
    )


if __name__ == "__main__":
    main()
