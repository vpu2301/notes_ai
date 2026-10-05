"""No-audio regression for the offline clusterer's roster behaviour.

Runs the production ``cluster_embeddings_with_stats`` (default config) on
synthetic 192-d embeddings of a TWO-speaker, 400-chunk (~10 min)
recording, 40 seeds per scenario. Shows mechanism, not magnitude:

    S0  isotropic chunk noise only (same-voice cosine 0.60 / 0.50 / 0.42)
    S1  + chunks straddling turn boundaries
    S2  + speaker B has a second acoustic condition (30 % of B's turns,
          centroid cosine 0.55 — ASSUMED)
    S3  + 3 % non-speech events that pass VAD (ASSUMED tight cluster)
    S4  all of the above (+ raised floor, + raised floor and merge 0.50)

    uv run python scripts/eval/sim_cluster_overcount.py [--assert]

``--assert`` fails unless S0/S1 stay 100 % exactly-two-speakers: the
roster logic must never turn random noise into a speaker.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import replace

import numpy as np

from diarization import UNKNOWN, OfflineClusteringConfig, cluster_embeddings_with_stats

DIM = 192
CHUNKS = 400
SEEDS = 40
CHUNK_MS = 1200


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def _near(rng: np.random.Generator, base: np.ndarray, cosine: float) -> np.ndarray:
    """A unit vector at the given cosine to ``base``."""
    ortho = rng.standard_normal(DIM)
    ortho = _unit(ortho - ortho @ base * base)
    return cosine * base + np.sqrt(1 - cosine**2) * ortho


def _chunk(rng: np.random.Generator, centre: np.ndarray, same_voice: float) -> np.ndarray:
    # x = c + σn with n ~ N(0, I/d): E[cos(x_i, x_j)] ≈ 1 / (1 + σ²).
    sigma = np.sqrt(1 / same_voice - 1)
    return centre + sigma * rng.standard_normal(DIM) / np.sqrt(DIM)


def recording(
    seed: int,
    *,
    same_voice: float = 0.5,
    straddle: bool = False,
    condition_split: bool = False,
    events: bool = False,
) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    a = _unit(rng.standard_normal(DIM))
    b = _near(rng, a, 0.2)
    b_alt = _near(rng, b, 0.55)
    event = _unit(rng.standard_normal(DIM))

    owners: list[str] = []
    speaker = "A"
    while len(owners) < CHUNKS:
        turn = int(rng.integers(3, 16))
        alt = speaker == "B" and condition_split and rng.random() < 0.3
        owners += [("B'" if alt else speaker)] * turn
        speaker = "B" if speaker == "A" else "A"
    owners = owners[:CHUNKS]
    centres = {"A": a, "B": b, "B'": b_alt}

    vectors = [_chunk(rng, centres[o], same_voice) for o in owners]
    if straddle:
        for i in range(1, CHUNKS):
            if owners[i][0] != owners[i - 1][0]:
                mix = _unit(centres[owners[i]] + centres[owners[i - 1]])
                vectors[i] = _chunk(rng, mix, same_voice)
    if events:
        for i in rng.choice(CHUNKS, size=int(CHUNKS * 0.03), replace=False):
            vectors[int(i)] = _chunk(rng, event, 0.8)
    return vectors


def speakers(vectors: list[np.ndarray], cfg: OfflineClusteringConfig) -> tuple[int, float]:
    labels, _, _ = cluster_embeddings_with_stats(
        vectors, cfg, durations_ms=[CHUNK_MS] * len(vectors)
    )
    return len(set(labels) - {UNKNOWN}), labels.count(UNKNOWN) / len(labels)


def scenarios() -> list[tuple[str, dict[str, object], OfflineClusteringConfig]]:
    base = OfflineClusteringConfig()
    floor = replace(base, min_speaker_chunks=8, min_speaker_share=0.05)
    everything = {"straddle": True, "condition_split": True, "events": True}
    return [
        ("S0 cos 0.60", {"same_voice": 0.60}, base),
        ("S0 cos 0.50", {"same_voice": 0.50}, base),
        ("S0 cos 0.42", {"same_voice": 0.42}, base),
        ("S1 straddle", {"straddle": True}, base),
        ("S2 condition split", {"condition_split": True}, base),
        ("S3 non-speech events", {"events": True}, base),
        ("S4 all", everything, base),
        ("S4 floor 8 chunks / 5 %", everything, floor),
        ("S4 floor + merge 0.50", everything, replace(floor, centroid_merge_threshold=0.50)),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert", dest="check", action="store_true")
    parser.add_argument("--seeds", type=int, default=SEEDS)
    args = parser.parse_args()

    print("| scenario | exactly 2 | distribution | unknown |\n|---|---|---|---|")
    exact: dict[str, float] = {}
    for name, kwargs, cfg in scenarios():
        counts: Counter[int] = Counter()
        unknown = 0.0
        for seed in range(args.seeds):
            n, unk = speakers(recording(seed, **kwargs), cfg)  # type: ignore[arg-type]
            counts[n] += 1
            unknown += unk
        exact[name] = counts[2] / args.seeds
        dist = ", ".join(f"{k} spk: {v}" for k, v in sorted(counts.items()))
        print(f"| {name} | {exact[name]:.0%} | {dist} | {unknown / args.seeds:.1%} |")

    if args.check:
        failing = [n for n, v in exact.items() if n.startswith(("S0", "S1")) and v < 1.0]
        if failing:
            print(f"FAIL: roster regression in {failing}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
