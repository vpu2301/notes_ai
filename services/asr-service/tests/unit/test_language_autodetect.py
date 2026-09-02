"""Batch edge after auto-detect: ``language=auto`` is a valid submit, and
a transcript in a language nlp-service cannot post-process is served raw
rather than bounced off nlp-service."""

from __future__ import annotations

from uuid import uuid4

from asr_models import (
    JobStatus,
    Segment,
    TranscriptionJobView,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from asr_service.routers import jobs
from asr_service.routers.jobs import NLP_LANGUAGES, _enriched_result_view


class _NlpSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def process_segments(self, **_kw):  # type: ignore[no-untyped-def]
        self.calls += 1
        return None


def _output(language: str) -> TranscriptionOutput:
    return TranscriptionOutput(
        language=language,
        language_detected=True,
        language_probability=0.9,
        segments=[
            Segment(
                text="dzień dobry",
                start_ms=0,
                end_ms=900,
                words=[WordTiming(text="dzień", start_ms=0, end_ms=400, probability=0.9)],
                avg_confidence=0.9,
            )
        ],
        metadata=TranscriptionMetadata(
            model="large-v3", vad_seconds_speech=0.9, infer_seconds=0.1, beam_size=5
        ),
    )


async def test_unsupported_language_is_served_raw_without_calling_nlp(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(jobs.settings, "nlp_enrich_enabled", True)
    spy = _NlpSpy()
    state = type("S", (), {"nlp_client": spy})()
    view = await _enriched_result_view(
        state, job_id=uuid4(), output=_output("pl"), authorization=None
    )
    assert spy.calls == 0
    assert view.nlp_applied is False
    assert view.language == "pl"
    assert view.language_detected is True
    assert view.segments[0].text == "dzień dobry"


async def test_supported_language_still_goes_through_nlp(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(jobs.settings, "nlp_enrich_enabled", True)
    spy = _NlpSpy()
    state = type("S", (), {"nlp_client": spy})()
    assert "uk" in NLP_LANGUAGES
    await _enriched_result_view(state, job_id=uuid4(), output=_output("uk"), authorization=None)
    assert spy.calls == 1


def test_job_view_defaults_detected_language_to_none() -> None:
    view = TranscriptionJobView(
        id=uuid4(),
        tenant_id=uuid4(),
        audio_id=uuid4(),
        requester_sub=uuid4(),
        language="auto",
        model="large-v3",
        status=JobStatus.QUEUED,
        queued_at="2026-09-02T00:00:00Z",
    )
    assert view.detected_language is None
