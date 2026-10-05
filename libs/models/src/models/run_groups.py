"""Sprint TQ2 T1 — planned speech runs as HTTP request groups.

An HTTP backend is sent the worker's speech runs, not the recording: runs
of one language are concatenated, in time order, into groups of at most
``group_seconds``, with ``JOIN_MS`` of silence between runs. One request per
group keeps the request count low (an HF scale-to-zero endpoint's cold
start dominates small requests), and the silence the decoder never sees
cannot be transcribed as "Vielen Dank.".

``Group.to_recording`` maps a time in the group's audio back to the
recording. A time inside the joining silence belongs to the run before it;
a time past the group's audio (whisper.cpp stamps its last segment up to
the next 30 s boundary) is clamped to the last run's end.
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
            # A run can end past the decoded samples by rounding; pad so the
            # offset table stays exact.
            want = (run.end_ms - run.start_ms) * SAMPLES_PER_MS
            if chunk.shape[0] < want:
                chunk = np.concatenate([chunk, np.zeros(want - chunk.shape[0], dtype=np.float32)])
            parts.append(chunk.astype(np.float32, copy=False))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def to_recording(self, t_ms: int) -> int:
        """A time inside a joining silence snaps to the nearer run edge: an
        engine with 80 ms frames (Parakeet) stamps a word a few frames
        before the run it belongs to, and putting it at the end of the run
        before would move its sentence ahead of everything said between."""
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
    """Runs → request groups: one open group per language, filled in time
    order, closed when the next run would pass ``group_seconds``. A run
    longer than the limit is a group of its own."""
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
    """A group's transcript on the recording's clock. ``label`` is the
    segment language to stamp (``None`` = the recording's)."""
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
