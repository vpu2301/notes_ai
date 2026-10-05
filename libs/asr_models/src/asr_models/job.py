"""Job-level types: the queue payload and the API view."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from .errors import spec_for


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


LANGUAGE_REQUEST_PATTERN = r"^(auto|uk|en|de)$"
# ISO 639-1, plus Whisper's one three-letter code (``yue``).
LANGUAGE_CODE_PATTERN = r"^[a-z]{2,3}$"
AUTO_LANGUAGE = "auto"


class JobEnqueuePayload(BaseModel):
    """Wire payload the API enqueues onto Redis Streams.

    The worker validates this on read; any field mismatch indicates a
    cross-version skew (asr-service deployed before asr-worker).
    """

    job_id: UUID
    tenant_id: UUID
    audio_id: UUID
    # Whisper initial_prompt hint; queue message only, not persisted on the job row.
    vocabulary_hint: str | None = None
    # ``auto`` = the worker detects; the result's ``language`` then carries the detected code.
    language: str = Field(pattern=LANGUAGE_REQUEST_PATTERN)
    model: str = "large-v3"
    # Queue message only (no DB column); the stored result's ``speakers`` is the durable record.
    diarize: bool = False
    # Queue-only; the worker records what it used in ``DiarizationStats.hint_*``.
    num_speakers: int | None = Field(default=None, ge=1, le=8)
    max_speakers: int | None = Field(default=None, ge=1, le=8)
    # ``rediarize`` relabels from stored audio + words, no ASR pass. An OLD worker reads it as a
    # transcribe of a complete job and acks it: deploy asr-worker before asr-service.
    task: Literal["transcribe", "rediarize"] = "transcribe"
    target_rev: int | None = Field(default=None, ge=1)
    # The row's diarization_request_id; the worker claims/swaps/fails only on a match.
    rediarize_id: UUID | None = None
    # ch0 = microphone, ch1 = call audio; an old worker downmixes. The local name is content: never logged.
    channel_layout: Literal["mono", "mic_system"] = "mono"
    local_speaker_name: str | None = Field(default=None, max_length=80)
    # Record press → first frame; reported as a ``no_audio`` gap. None from older clients.
    first_frame_offset_ms: int | None = Field(default=None, ge=0, le=600_000)
    requester_sub: UUID
    schema_version: int = 1


class TranscriptionJobView(BaseModel):
    """Public view of a transcription job. Returned by the GET endpoints."""

    id: UUID
    tenant_id: UUID
    audio_id: UUID
    requester_sub: UUID
    # As requested at submit: ``uk``/``en``/``de`` or ``auto``.
    language: str
    # ISO 639-1, set at completion; None while running; echoes ``language`` for a pinned job.
    detected_language: str | None = None
    model: str
    status: JobStatus
    # Echoed on the POST response only (no DB column); views read back later default to False.
    diarize: bool = False
    # `JobErrorKind`, typed `str` so a kind from a newer worker still deserializes.
    error_kind: str | None = None
    error_detail: str | None = None
    # Tenant data; served to the job's own tenant only.
    vocabulary_hint: str | None = None
    record_pressed_at: datetime | None = None
    first_frame_offset_ms: int | None = None
    coverage_share: float | None = None

    result_url: str | None = None  # populated only when status == complete
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempts: int = 0

    # Cancel asked for on a running job; the worker acts on it at its next checkpoint.
    cancel_requested: bool = False

    # label → display name, via ``PUT /asr/jobs/{id}/speakers``.
    speaker_names: dict[str, str] = Field(default_factory=dict)
    # Diarization run that speaker edits apply to (a re-run bumps it).
    diarization_rev: int = 1
    # None until the first re-run; ``status`` stays ``complete`` while labels are recomputed.
    diarization_status: Literal["queued", "running", "complete", "failed"] | None = None
    diarization_error: str | None = None
    diarization_runs: int = 0
    can_undo_rediarize: bool = False
    # Submit response only: False = hint sent but ignored (diarize=false), None = none sent.
    hints_applied: bool | None = None

    # Derived from `error_kind`. Computed, not stored: `model_copy(update=...)` skips
    # validators and callers copy these views, so stored fields would desync.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_stage(self) -> str | None:
        """Where the job died — ``decode``, ``inference``, ``lifecycle``, …"""
        spec = spec_for(self.error_kind)
        return str(spec.stage) if spec else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_retryable(self) -> bool | None:
        """Whether re-running this same job could plausibly have succeeded."""
        spec = spec_for(self.error_kind)
        return spec.retryable if spec else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_message(self) -> str | None:
        """Explanation safe to show — carries no sensitive content.

        Built from the kind alone. ``error_detail`` is assembled from an
        exception that may quote the audio it choked on, and is not
        (ADR-0031).
        """
        spec = spec_for(self.error_kind)
        return spec.message if spec else None
