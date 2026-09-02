"""Language contract after auto-detect (migration 0015).

A job may be *requested* as ``auto``; a stored transcript is always in a
concrete language — whatever Whisper heard, which need not be one of the
NLP post-processor's languages.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from asr_models import (
    AUTO_LANGUAGE,
    JobEnqueuePayload,
    JobStatus,
    TranscriptionJobView,
    TranscriptionMetadata,
    TranscriptionOutput,
    TranscriptResultView,
)


def _metadata() -> TranscriptionMetadata:
    return TranscriptionMetadata(
        model="large-v3", vad_seconds_speech=1.0, infer_seconds=0.1, beam_size=5
    )


def _payload(language: str) -> JobEnqueuePayload:
    return JobEnqueuePayload(
        job_id=uuid4(),
        tenant_id=uuid4(),
        audio_id=uuid4(),
        language=language,
        requester_sub=uuid4(),
    )


def test_job_may_be_requested_as_auto() -> None:
    assert _payload(AUTO_LANGUAGE).language == "auto"
    assert _payload("uk").language == "uk"


def test_job_request_rejects_arbitrary_codes() -> None:
    # The pin list is the surfaces we have prompts and NLP for; anything
    # else goes through `auto`.
    with pytest.raises(ValidationError):
        _payload("pl")


@pytest.mark.parametrize("code", ["uk", "en", "de", "pl", "fr", "yue"])
def test_output_accepts_any_detected_language(code: str) -> None:
    out = TranscriptionOutput(
        language=code,
        language_detected=True,
        language_probability=0.93,
        segments=[],
        metadata=_metadata(),
    )
    assert out.language == code
    assert out.language_detected is True


def test_output_never_stores_the_literal_auto() -> None:
    with pytest.raises(ValidationError):
        TranscriptionOutput(language="auto", segments=[], metadata=_metadata())


def test_old_stored_transcript_still_decodes() -> None:
    # Pre-0015 worker wrote no detection fields.
    raw = (
        '{"language":"uk","segments":[],"metadata":{"model":"large-v3",'
        '"vad_seconds_speech":1.0,"infer_seconds":0.1,"beam_size":5}}'
    )
    out = TranscriptionOutput.model_validate_json(raw)
    assert out.language_detected is False
    assert out.language_probability is None


def test_result_view_carries_detection_and_view_carries_detected_language() -> None:
    view = TranscriptResultView(
        job_id=uuid4(),
        language="pl",
        language_detected=True,
        language_probability=0.8,
        segments=[],
        metadata=_metadata(),
    )
    assert view.model_dump()["language_detected"] is True

    job = TranscriptionJobView(
        id=uuid4(),
        tenant_id=uuid4(),
        audio_id=uuid4(),
        requester_sub=uuid4(),
        language="auto",
        model="large-v3",
        status=JobStatus.QUEUED,
        queued_at="2026-09-02T00:00:00Z",
    )
    assert job.detected_language is None
