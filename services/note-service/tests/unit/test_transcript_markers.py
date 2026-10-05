"""The ASR result's non-speech markers reach the note as
listed passages — music and noise, never silence, unknown kinds as noise."""

from __future__ import annotations

from note_service.domain.meeting_doc.pipeline import transcript_markers


def test_music_and_noise_are_listed_silence_is_not() -> None:
    result = {
        "noise": [
            {"start_ms": 16_830, "end_ms": 28_830, "kind": "music"},
            {"start_ms": 28_830, "end_ms": 43_726, "kind": "silence"},
            {"start_ms": 50_000, "end_ms": 56_000, "kind": "applause"},
            {"start_ms": 60_000, "end_ms": 60_000, "kind": "music"},
            {"start_ms": "x"},
        ]
    }
    got = [(e.start_ms, e.end_ms, e.reason) for e in transcript_markers(result)]
    assert got == [(16_830, 28_830, "music"), (50_000, 56_000, "noise")]


def test_a_result_from_before_tq2_has_no_markers() -> None:
    assert transcript_markers({"segments": []}) == []
