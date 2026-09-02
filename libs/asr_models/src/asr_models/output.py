"""The transcript JSON schema.

Persisted as encrypted JSON in the transcripts bucket. The worker writes
it; the API returns a pre-signed URL to it; sprint 05's NLP postprocessor
consumes it. Stable by contract — additions are fine, breaking changes
need a wire-version bump and a migration story.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt


class WordTiming(BaseModel):
    text: str
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    probability: float = Field(ge=0.0, le=1.0)


class Segment(BaseModel):
    text: str
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    words: list[WordTiming] = Field(default_factory=list)
    avg_confidence: float = Field(ge=0.0, le=1.0)
    # Ambient Capture v1: neutral diarization label ("SPEAKER_1".."SPEAKER_N").
    # None when the job was not diarized, or when the diarizer could not
    # attribute this segment with confidence (never a guess).
    speaker: str | None = None


class TranscriptionMetadata(BaseModel):
    model: str
    vad_seconds_speech: NonNegativeFloat
    infer_seconds: NonNegativeFloat
    gpu_seconds: NonNegativeFloat = 0.0
    peak_gpu_mem_mb: NonNegativeInt = 0
    beam_size: int = Field(ge=1)


class TranscriptionOutput(BaseModel):
    # The union of what any ASR surface supports. `de` arrived with
    # streaming dictation; the batch edge (asr-service) keeps its own,
    # narrower `^(uk|en)$` form gate until German batch is piloted.
    language: str = Field(pattern=r"^(uk|en|de)$")
    segments: list[Segment]
    metadata: TranscriptionMetadata
    # Distinct speaker labels in first-appearance order; empty when the
    # job was not diarized (additive — older stored transcripts decode
    # with an empty list).
    speakers: list[str] = Field(default_factory=list)
    schema_version: int = 1


# ── Result view (API-facing, sprint-05 NLP enrichment) ──────────────


class ConfidenceSpanView(BaseModel):
    """A character range in an enriched segment's ``text`` flagged by the
    NLP confidence stage (low word-probability regions, risky numbers,
    …)."""

    start_char: NonNegativeInt
    end_char: NonNegativeInt
    level: str  # "high_concern" | "moderate"


class EnrichedSegment(BaseModel):
    """One segment as served by ``GET /asr/jobs/{id}/result``.

    ``text`` is the NLP post-processed rendering (dictated punctuation
    applied, numbers/dates normalized) when the view's ``nlp_applied``
    is true; otherwise it equals ``raw_text``. ``words`` always carry
    the raw Whisper timings.
    """

    text: str
    raw_text: str
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    words: list[WordTiming] = Field(default_factory=list)
    avg_confidence: float = Field(ge=0.0, le=1.0)
    confidence_spans: list[ConfidenceSpanView] = Field(default_factory=list)
    # Carried through from the stored transcript for diarized jobs.
    speaker: str | None = None


class TranscriptResultView(BaseModel):
    """Plaintext transcript response for a COMPLETE job (proxy-decrypt).

    The stored artifact stays :class:`TranscriptionOutput` (raw ASR);
    NLP enrichment is applied at read time and degrades gracefully —
    ``nlp_applied=False`` means the segments are the raw transcript.
    """

    job_id: UUID
    language: str = Field(pattern=r"^(uk|en|de)$")
    segments: list[EnrichedSegment]
    metadata: TranscriptionMetadata
    # Distinct speaker labels in first-appearance order (diarized jobs).
    speakers: list[str] = Field(default_factory=list)
    nlp_applied: bool = False
    nlp_pipeline_version: str | None = None
    schema_version: int = 1
