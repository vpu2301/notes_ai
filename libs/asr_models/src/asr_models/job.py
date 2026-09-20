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


# Languages a caller may pin a job to, plus ``auto`` (detect from the audio).
LANGUAGE_REQUEST_PATTERN = r"^(auto|uk|en|de)$"
# Whisper reports ISO 639-1 codes (``yue`` is its one three-letter code).
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
    # Optional free-text vocabulary hint fed to Whisper's initial_prompt
    # (product terms, names, jargon). Travels on the queue message only —
    # it is not persisted on the job row.
    vocabulary_hint: str | None = None
    # The language the caller asked for. ``auto`` means "listen and decide":
    # the worker runs Whisper's language identification on the recording
    # and transcribes in whatever it hears; the result's ``language`` then
    # carries the detected code, never the literal ``auto``.
    language: str = Field(pattern=LANGUAGE_REQUEST_PATTERN)
    model: str = "large-v3"
    # Ambient Capture v1: run offline speaker diarization after
    # transcription. Travels on the queue message only — no DB column;
    # the diarized output is visible in the stored result's `speaker`/
    # `speakers` fields.
    diarize: bool = False
    # Sprint 29 speaker-count hints (1..8), from a person at capture or on
    # a re-run. Queue-only; the worker records what it used in
    # ``DiarizationStats.hint_*``.
    num_speakers: int | None = Field(default=None, ge=1, le=8)
    max_speakers: int | None = Field(default=None, ge=1, le=8)
    # ``rediarize`` recomputes speaker labels from the stored audio and the
    # stored words — no ASR pass. ``target_rev`` is the diarization_rev the
    # new labelling becomes. Every new field has a default, and the model
    # ignores unknown fields: an OLD worker reads a rediarize message as a
    # transcribe of a complete job and acks it without doing anything —
    # deploy asr-worker before asr-service (the reaper catches stragglers).
    task: Literal["transcribe", "rediarize"] = "transcribe"
    target_rev: int | None = Field(default=None, ge=1)
    # Which re-run request this message carries (the row's
    # diarization_request_id). A message for an older request must not act
    # for a newer one: the worker claims, swaps and fails only on a match.
    rediarize_id: UUID | None = None
    # Sprint 31: a macOS capture with ch0 = microphone, ch1 = call audio.
    # An old worker ignores both fields and downmixes (safe; deploy the
    # worker first anyway). The local name is content: never logged.
    channel_layout: Literal["mono", "mic_system"] = "mono"
    local_speaker_name: str | None = Field(default=None, max_length=80)
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
    # What the recording turned out to be in (ISO 639-1). Set by the worker
    # when the job completes; ``None`` while it is still running. For a
    # fixed-language job it simply echoes ``language``.
    detected_language: str | None = None
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

    # Names people gave the diarized speakers of this job (label →
    # display name), set via ``PUT /asr/jobs/{id}/speakers``. Empty
    # until someone names one; the result view merges these into its
    # ``speaker_names``/``turns``.
    speaker_names: dict[str, str] = Field(default_factory=dict)
    # Diarization run that speaker edits apply to (a re-run bumps it).
    diarization_rev: int = 1
    # Speaker re-labelling (Sprint 29, ``POST …/rediarize``). ``None`` until
    # the first re-run: the initial diarization rides ``status``. The job's
    # ``status`` stays ``complete`` throughout — the transcript is readable
    # while labels are recomputed.
    diarization_status: Literal["queued", "running", "complete", "failed"] | None = None
    diarization_error: str | None = None
    diarization_runs: int = 0
    # A previous labelling exists that ``POST …/rediarize/undo`` restores.
    can_undo_rediarize: bool = False
    # Submit response only: True = the speaker-count hint was forwarded,
    # False = it was sent but ignored (diarize=false), None = none sent.
    hints_applied: bool | None = None

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
