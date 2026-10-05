"""The admin dashboard's per-job summary (migration 0067): numbers and
codes only — no word, name or spelling from the transcript reaches it."""

from __future__ import annotations

import json

from asr_models import (
    Coverage,
    CoverageGap,
    Diagnostics,
    DiarizationStats,
    DroppedSegment,
    NoiseRegion,
    Segment,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from asr_worker import quality

MARKERS = ("Handala", "Welchering", "Geheimprojekt", "Zebrastreifen")


def _output() -> TranscriptionOutput:
    def seg(text: str, start: int, prob: float, lang: str | None = None) -> Segment:
        words = [
            WordTiming(
                text=w, start_ms=start + k * 400, end_ms=start + k * 400 + 300, probability=prob
            )
            for k, w in enumerate(text.split())
        ]
        return Segment(
            text=text,
            start_ms=start,
            end_ms=start + len(words) * 400,
            words=words,
            avg_confidence=prob,
            speaker="SPEAKER_1",
            language=lang,
        )

    return TranscriptionOutput(
        language="de",
        language_detected=True,
        language_probability=0.98,
        segments=[
            seg("Handala spricht über das Geheimprojekt", 0, 0.9),
            seg("Welchering am Zebrastreifen", 4000, 0.3, "en"),
        ],
        metadata=TranscriptionMetadata(
            model="/opt/models/whisper-large-v3/snapshots/abc",
            vad_seconds_speech=7.5,
            infer_seconds=3.0,
            beam_size=1,
            coverage_share=0.9,
            diarization=DiarizationStats(
                engine="e",
                engine_version="1",
                chunks=1,
                clusters_raw=2,
                clusters_after_merge=1,
                clusters_dropped=0,
                speakers=1,
                speech_seconds=7.0,
                unknown_share=0.1,
                seconds=1.0,
            ),
        ),
        speakers=["SPEAKER_1"],
        diagnostics=Diagnostics(
            coverage=Coverage(
                speech_ms=8000,
                transcribed_ms=7200,
                gaps=[CoverageGap(start_ms=100, end_ms=900, cause="unknown")],
            ),
            dropped_segments=[
                DroppedSegment(start_ms=0, end_ms=10, reason="loop"),
                DroppedSegment(start_ms=0, end_ms=10, reason="artefact", dry_run=True),
            ],
        ),
        noise=[NoiseRegion(start_ms=9000, end_ms=12000, kind="music")],
    )


def test_summary_carries_no_transcript_content() -> None:
    dumped = json.dumps(quality.summarize(_output(), audio_seconds=12.0))
    for marker in MARKERS:
        assert marker not in dumped, marker
    assert "SPEAKER_1" not in dumped


def test_summary_numbers() -> None:
    q = quality.summarize(_output(), audio_seconds=12.0)
    assert q["v"] == quality.QUALITY_VERSION
    assert (q["segments"], q["words"], q["speakers"]) == (2, 8, 1)
    assert q["rtf"] == 0.25
    assert q["coverage_share"] == 0.9
    assert q["language_share"] == {"de": 0.625, "en": 0.375}
    assert q["low_confidence_word_share"] == 0.375  # 3 of 8 words below 0.5
    assert q["dropped"] == {"loop": 1} and q["dropped_dry_run"] == 1
    assert q["gaps"] == {"unknown": 1}
    assert q["noise_s"] == {"music": 3.0}
    assert q["diarization_unknown_share"] == 0.1
    assert q["shadow"] is None


def test_every_value_is_a_number_code_or_container_of_them() -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                assert isinstance(k, str) and len(k) <= 40
                walk(v)
        elif isinstance(value, str):
            # model ids, backends, language codes, enum reasons — short identifiers
            assert len(value) <= 120 and " " not in value, value
        else:
            assert value is None or isinstance(value, (int, float, bool)), value

    walk(quality.summarize(_output(), audio_seconds=12.0))


def test_speaker_numbers_is_what_a_rerun_overwrites() -> None:
    assert quality.speaker_numbers(_output()) == {
        "speakers": 1,
        "diarization_unknown_share": 0.1,
        "diarization_overlap_share": None,
    }


def test_empty_transcript() -> None:
    empty = _output().model_copy(update={"segments": [], "speakers": []})
    q = quality.summarize(empty, audio_seconds=0.0)
    assert q["words"] == 0 and q["avg_confidence"] is None and q["rtf"] is None
