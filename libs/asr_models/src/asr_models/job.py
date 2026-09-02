"""Job-level types: the queue payload and the API view."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from .errors import spec_for


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobEnqueuePayload(BaseModel):
    """Wire payload the API enqueues onto Redis Streams.

    The worker validates this on read; any field mismatch indicates a
    cross-version skew (asr-service deployed before asr-worker).
    """

    job_id: UUID
    tenant_id: UUID
    audio_id: UUID
    # Optional free-text vocabulary hint fed to Whisper's initial_prompt
    # (product terms, names, jargon). Travels on the queue message only —
    # it is not persisted on the job row.
    vocabulary_hint: str | None = None
    language: str = Field(pattern=r"^(uk|en|de)$")
    model: str = "large-v3"
    # Ambient Capture v1: run offline speaker diarization after
    # transcription. Travels on the queue message only — no DB column;
    # the diarized output is visible in the stored result's `speaker`/
    # `speakers` fields.
    diarize: bool = False
    requester_sub: UUID
    schema_version: int = 1


class TranscriptionJobView(BaseModel):
    """Public view of a transcription job. Returned by the GET endpoints."""

    id: UUID
    tenant_id: UUID
    audio_id: UUID
    requester_sub: UUID
    language: str
    model: str
    status: JobStatus
    # Whether offline diarization was requested at submit. Echoed on the
    # POST /asr/jobs response; `diarize` rides the queue payload only (no
    # DB column), so views read back later default to False — the stored
    # result's `speakers` field is the durable record.
    diarize: bool = False
    # One of `JobErrorKind` — typed as `str` on the wire so a job failed by
    # a newer worker than this reader still deserializes instead of 500ing
    # the list endpoint. `spec_for` maps anything unrecognised to UNKNOWN.
    error_kind: str | None = None
    error_detail: str | None = None

    result_url: str | None = None  # populated only when status == complete
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempts: int = 0

    # A cancel that has been ASKED FOR but not yet acted on. DELETE on a
    # queued job cancels it outright; on a running one it can only set this
    # flag, and the worker acts on it at its next checkpoint. Without it on
    # the wire a client had no way to tell "still running" from "stopping",
    # so the Cancel button looked broken: pressed, acknowledged, nothing
    # visibly changed.
    cancel_requested: bool = False

    # ── Derived from `error_kind`; never stored, never settable ──────
    # A client should not have to carry a copy of the failure vocabulary to
    # know whether "try again" is honest advice. These three read straight
    # off the spec table, so the SPA, the runbooks, and the dashboards all
    # follow one source.
    #
    # Computed rather than validated-in: `model_copy(update=...)` skips
    # validators, and callers copy these views (e.g. to attach a result
    # URL). Stored fields would silently desync there — a job whose
    # `error_kind` says one thing and whose `error_stage` says nothing
    # at all.

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
