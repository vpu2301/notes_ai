"""Sprint TQ2 T1: runs → HTTP request groups and back to the recording."""

from __future__ import annotations

import numpy as np

from asr_models import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from models import SpeechRun
from models.run_groups import JOIN_MS, plan_groups, remap


def test_groups_are_per_language_in_time_order_and_capped() -> None:
    runs = [
        SpeechRun(0, 100_000, "de"),
        SpeechRun(101_000, 110_000, "en", True),
        SpeechRun(111_000, 211_000, "de"),
        SpeechRun(212_000, 312_000, "de"),
    ]
    groups = plan_groups(runs, group_seconds=250)
    assert [(g.language, [r.start_ms for r in g.runs]) for g in groups] == [
        ("de", [0, 111_000]),
        ("en", [101_000]),
        ("de", [212_000]),
    ]
    assert groups[0].length_ms == 100_000 + JOIN_MS + 100_000


def test_times_map_back_through_the_joining_silence() -> None:
    (g,) = plan_groups([SpeechRun(1000, 3000, "de"), SpeechRun(10_000, 12_000, "de")], 300)
    assert g.to_recording(0) == 1000
    assert g.to_recording(1999) == 2999
    assert g.to_recording(2100) == 3000, "early in the join: the end of the run before"
    assert g.to_recording(2250) == 10_000, "late in the join: the start of the run after"
    assert g.to_recording(2300) == 10_000
    assert g.to_recording(4300) == 12_000
    assert g.to_recording(30_000) == 12_000, "whisper.cpp's past-the-end stamp is clamped"
    audio = g.audio(np.ones(16_000 * 13, dtype=np.float32))
    assert audio.shape[0] == (2000 + JOIN_MS + 2000) * 16
    assert audio[2000 * 16 : 2300 * 16].max() == 0.0


def test_remap_puts_words_and_segments_on_the_recording_clock() -> None:
    (g,) = plan_groups([SpeechRun(5000, 7000, "en"), SpeechRun(20_000, 21_000, "en")], 300)
    out = TranscriptionOutput(
        language="en",
        segments=[
            Segment(
                text="respond with force",
                start_ms=2300,
                end_ms=3200,
                avg_confidence=0.9,
                words=[WordTiming(text="respond", start_ms=2300, end_ms=2700, probability=0.9)],
            )
        ],
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
    )
    (seg,) = remap(out, g, label="en").segments
    assert (seg.start_ms, seg.end_ms, seg.language) == (20_000, 20_900, "en")
    assert (seg.words[0].start_ms, seg.words[0].end_ms) == (20_000, 20_400)
