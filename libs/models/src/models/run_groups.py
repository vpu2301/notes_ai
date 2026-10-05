"""Planned speech runs as HTTP request groups: same-language runs joined with ``JOIN_MS`` of silence, at most
``group_seconds`` each. ``Group.to_recording`` maps group time back to the recording (clamped to the last run's end).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from asr_models import Segment, SegmentDiagnostics, TranscriptionOutput, WordTiming

from .protocols import SpeechRun

SAMPLES_PER_MS = 16
JOIN_MS = 300


@dataclass
class Group:
    language: str
    runs: list[SpeechRun] = field(default_factory=list)
    # (start in the group's audio, start in the recording, length), per run.
    pieces: list[tuple[int, int, int]] = field(default_factory=list)
    length_ms: int = 0

    def add(self, run: SpeechRun) -> None:
        if self.runs:
            self.length_ms += JOIN_MS
        length = max(0, run.end_ms - run.start_ms)
        self.pieces.append((self.length_ms, run.start_ms, length))
        self.runs.append(run)
        self.length_ms += length

    def audio(self, pcm: np.ndarray) -> np.ndarray:
        gap = np.zeros(JOIN_MS * SAMPLES_PER_MS, dtype=np.float32)
        parts: list[np.ndarray] = []
        for k, run in enumerate(self.runs):
            if k:
                parts.append(gap)
            chunk = pcm[run.start_ms * SAMPLES_PER_MS : run.end_ms * SAMPLES_PER_MS]
            # Pad a run that ends past the samples by rounding so the offset table stays exact.
            want = (run.end_ms - run.start_ms) * SAMPLES_PER_MS
            if chunk.shape[0] < want:
                chunk = np.concatenate([chunk, np.zeros(want - chunk.shape[0], dtype=np.float32)])
            parts.append(chunk.astype(np.float32, copy=False))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def to_recording(self, t_ms: int) -> int:
        """A time inside a joining silence snaps to the nearer run edge (80 ms-frame engines stamp words early)."""
        starts = [p[0] for p in self.pieces]
        k = max(0, bisect_right(starts, t_ms) - 1)
        g0, r0, length = self.pieces[k]
        if t_ms > g0 + length and k + 1 < len(self.pieces):
            next_g0, next_r0, _ = self.pieces[k + 1]
            if next_g0 - t_ms < t_ms - (g0 + length):
                return next_r0
        return r0 + min(max(0, t_ms - g0), length)

    @property
    def start_ms(self) -> int:
        return self.runs[0].start_ms

    @property
    def end_ms(self) -> int:
        return self.runs[-1].end_ms


def plan_groups(runs: Sequence[SpeechRun], group_seconds: float) -> list[Group]:
    """Runs → request groups per language, closed at ``group_seconds``; an over-long run is a group of its own."""
    limit = max(1, int(group_seconds * 1000))
    open_: dict[str, Group] = {}
    done: list[Group] = []
    for run in sorted(runs, key=lambda r: r.start_ms):
        if run.end_ms <= run.start_ms:
            continue
        g = open_.get(run.language)
        length = run.end_ms - run.start_ms
        if g is not None and g.runs and g.length_ms + JOIN_MS + length > limit:
            done.append(g)
            g = None
        if g is None:
            g = Group(language=run.language)
            open_[run.language] = g
        g.add(run)
    done.extend(g for g in open_.values() if g.runs)
    return sorted(done, key=lambda g: g.start_ms)


def remap(output: TranscriptionOutput, group: Group, *, label: str | None) -> TranscriptionOutput:
    """A group's transcript on the recording's clock; ``label`` is the segment language (``None`` = the recording's)."""
    segments: list[Segment] = []
    for seg in output.segments:
        words = [
            WordTiming(
                text=w.text,
                start_ms=group.to_recording(w.start_ms),
                end_ms=max(group.to_recording(w.end_ms), group.to_recording(w.start_ms)),
                probability=w.probability,
            )
            for w in seg.words
        ]
        start = group.to_recording(seg.start_ms)
        end = max(start, group.to_recording(seg.end_ms))
        segments.append(
            seg.model_copy(
                update={"start_ms": start, "end_ms": end, "words": words, "language": label}
            )
        )
    diags: list[SegmentDiagnostics] = []
    for d in output.diagnostics.segments:
        start = group.to_recording(d.start_ms)
        diags.append(
            d.model_copy(
                update={
                    "start_ms": start,
                    "end_ms": max(start, group.to_recording(d.end_ms)),
                    "language": group.language if group.language != "auto" else d.language,
                }
            )
        )
    return output.model_copy(
        update={
            "segments": segments,
            "diagnostics": output.diagnostics.model_copy(update={"segments": diags}),
        }
    )
