"""Telemetry schema v1 (telemetry-sprints/design/SCHEMA_v1.md, telemetry_v1.schema.json).

Missing is not zero: a measurement that was not taken is ``None`` and its reason sits in
``null_reasons`` (entities) or ``attributes["_reasons"]`` (spans). A value and a reason for the
same field is a contradiction and fails validation.

Timing glossary (canonical):
- ``processing_wall_seconds``: submission (server accepted the job) → final backend result stored.
- ``user_wait_seconds``: recording stop / import submission on the client → final result displayed on the client.
- ``time_to_transcript_seconds``: submission → transcript displayed.
- ``time_to_speaker_labels_seconds``: submission → speaker labels displayed.
- ``time_to_notes_seconds``: submission → notes displayed.
- ``rtf``: ``processing_wall_seconds / audio_duration_seconds`` (lower is better).
- ``speedup``: ``audio_duration_seconds / processing_wall_seconds`` (higher is better).
- ``asr_audio_processed_seconds``: Σ audio seconds actually fed to ASR across primary + recovery
  calls (this one *is* a sum, and is labelled as such).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1

Reason = Literal["unavailable", "not_supported", "not_measured", "error", "not_applicable"]
REASONS: frozenset[str] = frozenset(
    ["unavailable", "not_supported", "not_measured", "error", "not_applicable"]
)
ErrorCategory = Literal[
    "input", "upload", "queue", "model_load", "asr", "diarization",
    "postprocess", "llm", "storage", "client", "unknown",
]  # fmt: skip
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "partial"]
SpanStatus = Literal["ok", "error", "cancelled", "skipped", "partial", "started"]
ExecutionMode = Literal["native", "container", "remote"]
Stage = Literal[
    "capture_input", "upload", "queue", "model_init", "audio_prep", "vad", "language_detection",
    "asr_primary", "asr_recovery", "diarization_load", "diarization_infer", "postprocess_align",
    "postprocess_attribute", "postprocess_cleanup", "persist", "llm_call", "ui_delivery", "other",
]  # fmt: skip
STAGES: tuple[str, ...] = Stage.__args__  # type: ignore[attr-defined]

# Required attribute keys per stage (SCHEMA_v1.md); each may be None with a reason.
STAGE_KEYS: dict[str, tuple[str, ...]] = {
    "capture_input": ("audio_duration_seconds", "format", "sample_rate_hz", "channels",
                      "file_size_bytes", "capture_mode"),
    "upload": ("bytes", "chunks", "retries", "resumed"),
    "queue": ("enqueued_at", "started_at", "queue_wait_seconds", "queue_name",
              "queue_depth_at_enqueue"),
    "model_init": ("model_kind", "model_name", "model_revision", "quantization", "compute_type",
                   "device", "state", "load_seconds", "warmup_seconds"),
    "audio_prep": ("retrieve_seconds", "decrypt_seconds", "decode_seconds", "resample_seconds",
                   "source_sample_rate_hz", "target_sample_rate_hz"),
    "vad": ("backend", "duration_seconds", "speech_seconds", "run_count", "run_lengths_seconds",
            "threshold"),
    "language_detection": ("model", "call_count", "duration_seconds", "detected",
                           "decided_language"),
    "asr_primary": ("backend", "model", "device", "compute_type", "beam_size", "wall_seconds",
                    "audio_processed_seconds", "chunk_count", "chunk_seconds", "word_count",
                    "segment_count"),
    "asr_recovery": ("trigger_reason", "attempt", "audio_reprocessed_seconds", "wall_seconds",
                     "recovered_words", "backend", "model", "device"),
    "diarization_load": ("backend", "model", "device", "load_seconds", "speakers_detected",
                         "unknown_speaker_share", "audio_seconds"),
    "diarization_infer": ("backend", "model", "device", "infer_seconds", "speakers_detected",
                          "unknown_speaker_share", "audio_seconds"),
    "postprocess_align": ("duration_seconds", "items"),
    "postprocess_attribute": ("duration_seconds", "items"),
    "postprocess_cleanup": ("duration_seconds", "items"),
    "persist": ("duration_seconds", "items"),
    "ui_delivery": ("client", "event", "seconds_since_submission"),
}  # fmt: skip

# Stage → the error category a failure inside it gets.
STAGE_ERROR_CATEGORY: dict[str, ErrorCategory] = {
    "capture_input": "input", "upload": "upload", "queue": "queue", "model_init": "model_load",
    "audio_prep": "input", "vad": "asr", "language_detection": "asr", "asr_primary": "asr",
    "asr_recovery": "asr", "diarization_load": "model_load", "diarization_infer": "diarization",
    "postprocess_align": "postprocess", "postprocess_attribute": "postprocess",
    "postprocess_cleanup": "postprocess", "persist": "storage", "llm_call": "llm",
    "ui_delivery": "client", "other": "unknown",
}  # fmt: skip


class Device(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: str
    observation: Literal["observed", "configured"]


def check_reasons(values: dict[str, Any], fields: tuple[str, ...], reasons: dict[str, Any]) -> None:
    """``None`` ⇔ a reason. Raises ``ValueError`` naming the first broken field."""
    for name, reason in reasons.items():
        if reason not in REASONS:
            raise ValueError(f"{name}: unknown reason {reason!r}")
    for name in fields:
        value = values.get(name)
        if value is None and name not in reasons:
            raise ValueError(f"{name} is null without a reason")
        if value is not None and name in reasons:
            raise ValueError(f"{name} has a value and a reason ({value!r}, {reasons[name]})")


class _Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Nullable measurements of the entity; each None needs a null_reasons entry.
    MEASUREMENTS: ClassVar[tuple[str, ...]] = ()
    null_reasons: dict[str, Reason] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _missing_is_not_zero(self) -> _Entity:
        check_reasons(self.__dict__, self.MEASUREMENTS, self.null_reasons)
        return self


class ModelActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["asr", "diarization", "llm"]
    backend: str
    run_id: UUID | None = None
    overlap_seconds: float | None = None


class ProcessingRun(_Entity):
    MEASUREMENTS: ClassVar[tuple[str, ...]] = (
        "processing_wall_seconds", "user_wait_seconds",
        "time_to_transcript_seconds", "time_to_speaker_labels_seconds", "time_to_notes_seconds",
        "rtf", "speedup", "audio_duration_seconds", "asr_audio_processed_seconds",
        "concurrent_runs_at_start", "telemetry_overhead_seconds", "telemetry_buffer_peak_bytes",
    )  # fmt: skip
    processing_run_id: UUID
    tenant_id: UUID
    recording_id: UUID
    note_id: UUID | None = None
    note_generation_id: UUID | None = None
    kind: Literal["initial", "reprocess"]
    reprocess_scope: Literal["diarization", "notes"] | None = None
    trigger: Literal["auto", "user", "retry", "migration"]
    telemetry_schema_version: int = SCHEMA_VERSION
    # Worker pickups; a queue redelivery reuses the run and adds one.
    attempts: int = Field(default=0, ge=0)
    status: RunStatus
    error_category: ErrorCategory | None = None
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    processing_wall_seconds: float | None = None
    user_wait_seconds: float | None = None
    # user_wait_seconds measured from two devices' events (server-corrected clocks).
    user_wait_cross_device: bool | None = None
    time_to_transcript_seconds: float | None = None
    time_to_speaker_labels_seconds: float | None = None
    time_to_notes_seconds: float | None = None
    rtf: float | None = None
    speedup: float | None = None
    audio_duration_seconds: float | None = None
    asr_audio_processed_seconds: float | None = None
    created_by: UUID | None = None
    concurrent_runs_at_start: int | None = None
    other_model_activity: list[ModelActivity] = Field(default_factory=list)
    telemetry_overhead_seconds: float | None = None
    # RSS proxy: the largest serialised size this run's records reached in the write buffer.
    telemetry_buffer_peak_bytes: int | None = None
    retention_until: datetime
    trace_id: str | None = None


class RunContext(_Entity):
    MEASUREMENTS: ClassVar[tuple[str, ...]] = (
        "app_commit", "app_build", "os_name", "os_version", "arch", "chip_model",
        "memory_total_bytes", "device_asr", "device_diarization", "device_llm",
        "memory_pressure_start", "memory_pressure_end", "process_rss_start", "process_rss_end",
        "swap_used_start", "swap_used_end", "container_mem_limit",
    )  # fmt: skip
    processing_run_id: UUID
    tenant_id: UUID
    telemetry_schema_version: int = SCHEMA_VERSION
    app_commit: str | None = None
    app_build: str | None = None
    os_name: str | None = None
    os_version: str | None = None
    arch: str | None = None
    chip_model: str | None = None
    memory_total_bytes: int | None = None
    execution_mode: ExecutionMode
    effective_config: dict[str, Any] = Field(default_factory=dict)
    device_asr: Device | None = None
    device_diarization: Device | None = None
    device_llm: Device | None = None
    memory_pressure_start: str | None = None
    memory_pressure_end: str | None = None
    process_rss_start: int | None = None
    process_rss_end: int | None = None
    swap_used_start: int | None = None
    swap_used_end: int | None = None
    container_mem_limit: int | None = None


class SpanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    span_id: UUID
    processing_run_id: UUID
    tenant_id: UUID
    parent_span_id: UUID | None = None
    stage: Stage
    name: str = Field(max_length=128)
    attempt: int = Field(default=1, ge=1)
    status: SpanStatus
    error_category: ErrorCategory | None = None
    error_class: str | None = Field(default=None, max_length=128)
    start_monotonic_ns: int | None = None
    end_monotonic_ns: int | None = None
    start_wall_utc: datetime | None = None
    end_wall_utc: datetime | None = None
    clock_source: Literal["monotonic", "wall", "client_wall"] = "monotonic"
    process_id: int
    host: str = Field(max_length=128)
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_parallel_with: list[UUID] | None = None

    @model_validator(mode="after")
    def _stage_keys(self) -> SpanRecord:
        if self.status == "started":  # the begin row of a long span carries no results yet
            return self
        reasons = self.attributes.get("_reasons", {})
        attrs = {k: v for k, v in self.attributes.items() if not k.startswith("_")}
        keys = STAGE_KEYS.get(self.stage, ())
        missing = [k for k in keys if k not in attrs]
        if missing:
            raise ValueError(f"{self.stage}: missing attribute keys {missing}")
        check_reasons(attrs, keys, reasons)
        return self


class LlmCall(_Entity):
    MEASUREMENTS: ClassVar[tuple[str, ...]] = (
        "model", "queue_wait_seconds", "model_load_seconds", "time_to_first_token_seconds",
        "total_latency_seconds", "input_tokens", "output_tokens", "cached_input_tokens",
        "reasoning_tokens", "generation_tokens_per_second", "prompt_chars", "completion_chars",
    )  # fmt: skip
    llm_call_id: UUID
    span_id: UUID
    processing_run_id: UUID
    tenant_id: UUID
    purpose: Literal[
        "note_write", "note_merge", "note_check", "note_ask", "provider_probe", "inline_completion"
    ]
    provider: str
    model: str | None = None
    backend: str
    execution_mode: ExecutionMode
    streaming: bool = False
    attempt: int = Field(default=1, ge=1)
    status: SpanStatus
    queue_wait_seconds: float | None = None
    model_load_seconds: float | None = None
    time_to_first_token_seconds: float | None = None
    total_latency_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    token_source: Literal["provider", "estimated"]
    token_accounting_note: str | None = Field(default=None, max_length=256)
    generation_tokens_per_second: float | None = None
    prompt_chars: int | None = None
    completion_chars: int | None = None
    error_category: ErrorCategory | None = None


class ClientEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    processing_run_id: UUID | None = None
    recording_id: UUID
    tenant_id: UUID
    client: Literal["web", "macos", "ios"]
    client_version: str = Field(max_length=64)
    event: Literal[
        "recording_stopped", "import_submitted", "upload_started", "upload_finished",
        "transcript_displayed", "speaker_labels_displayed", "notes_displayed", "error_shown",
    ]  # fmt: skip
    client_wall_utc: datetime
    client_monotonic_ns: int | None = None
    server_received_utc: datetime
    estimated_clock_offset_ms: int
    attributes: dict[str, Any] = Field(default_factory=dict)


class RunExport(BaseModel):
    """One run as the read API and the report see it."""

    model_config = ConfigDict(extra="forbid")
    telemetry_schema_version: int = SCHEMA_VERSION
    processing_run: ProcessingRun
    run_context: RunContext | None = None
    spans: list[SpanRecord] = Field(default_factory=list)
    llm_calls: list[LlmCall] = Field(default_factory=list)
    client_events: list[ClientEvent] = Field(default_factory=list)
