"""Diarized batch result shape (Ambient Capture v1) — additive contract.

Two promises: an OLD stored transcript (no speaker fields) still decodes,
and a diarized one round-trips ``speaker``/``speakers`` through JSON.
"""

from __future__ import annotations

from uuid import uuid4

from asr_models import (
    JobEnqueuePayload,
    Segment,
    TranscriptionMetadata,
    TranscriptionOutput,
    TranscriptResultView,
)


def _metadata() -> TranscriptionMetadata:
    return TranscriptionMetadata(
        model="large-v3",
        vad_seconds_speech=3.5,
        infer_seconds=0.4,
        beam_size=5,
    )


def test_undiarized_transcript_decodes_with_no_speakers() -> None:
    # The shape an old worker stored, before the fields existed.
    output = TranscriptionOutput.model_validate(
        {
            "language": "en",
            "segments": [{"text": "hello", "start_ms": 0, "end_ms": 900, "avg_confidence": 0.9}],
            "metadata": _metadata().model_dump(),
        }
    )
    assert output.speakers == []
    assert output.segments[0].speaker is None


def test_diarized_transcript_round_trips_speaker_fields() -> None:
    output = TranscriptionOutput(
        language="en",
        segments=[
            Segment(text="hi", start_ms=0, end_ms=900, avg_confidence=0.9, speaker="SPEAKER_1"),
            Segment(text="hey", start_ms=1000, end_ms=1900, avg_confidence=0.9, speaker=None),
            Segment(text="so", start_ms=2000, end_ms=2900, avg_confidence=0.9, speaker="SPEAKER_2"),
        ],
        metadata=_metadata(),
        speakers=["SPEAKER_1", "SPEAKER_2"],
    )
    again = TranscriptionOutput.model_validate_json(output.model_dump_json())
    assert again.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert [s.speaker for s in again.segments] == ["SPEAKER_1", None, "SPEAKER_2"]


def test_result_view_carries_speakers() -> None:
    view = TranscriptResultView(
        job_id=uuid4(),
        language="en",
        segments=[],
        metadata=_metadata(),
        speakers=["SPEAKER_1"],
    )
    assert view.model_dump()["speakers"] == ["SPEAKER_1"]
    # Default stays empty for non-diarized jobs.
    assert (
        TranscriptResultView(
            job_id=uuid4(), language="en", segments=[], metadata=_metadata()
        ).speakers
        == []
    )


def test_enqueue_payload_diarize_defaults_false_and_survives_the_wire() -> None:
    payload = JobEnqueuePayload(
        job_id=uuid4(),
        tenant_id=uuid4(),
        audio_id=uuid4(),
        language="en",
        requester_sub=uuid4(),
    )
    assert payload.diarize is False
    flagged = JobEnqueuePayload.model_validate_json(
        payload.model_copy(update={"diarize": True}).model_dump_json()
    )
    assert flagged.diarize is True
