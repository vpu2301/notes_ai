"""asr-worker configuration."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from secret import Secret

# pydantic-settings treats the generic Secret[str] as complex and json.loads() the raw
# env value; NoDecode hands it straight to Secret's validator. Every env Secret uses this.
SecretStrEnv = Annotated[Secret[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "asr-worker"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    testing: bool = Field(default=False, alias="TESTING")

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_sdk_disabled: bool = Field(default=False, alias="OTEL_SDK_DISABLED")

    # ── Whisper / device ────────────────────────────────────────────────
    asr_device: str = Field(default="cuda", alias="MD_ASR_DEVICE")  # cuda | cpu
    asr_model: str = Field(default="large-v3", alias="MD_ASR_MODEL")
    asr_compute_type: str = Field(default="float16", alias="MD_ASR_COMPUTE_TYPE")
    asr_beam_size: int = Field(default=5, alias="MD_ASR_BEAM_SIZE")
    # Conditioning on previous text amplifies prompt-echo cascades but turning it off
    # yields lower-case run-ons; stays ON. In-process engine only (HTTP backends reset
    # context per run group).
    asr_condition_prev: bool = Field(default=True, alias="MDX_ASR_CONDITION_PREV")
    # How the vocabulary reaches the decoder: `initial_prompt` or faster-whisper `hotwords`.
    asr_vocabulary_mode: str = Field(default="prompt", alias="MDX_ASR_VOCABULARY_MODE")
    # Language identification per VAD chunk, for every backend (chunks.py).
    asr_chunk_language_id: bool = Field(default=True, alias="MDX_ASR_CHUNK_LANGUAGE_ID")

    # ── Coverage ────────────────────────────────────────────────────────
    # Each VAD speech run starts this much earlier (clamped to the previous run's end).
    # OFF by default: 300 ms measured worse than floor + second pass alone.
    asr_vad_pad_ms: int = Field(default=0, ge=0, le=2000, alias="MD_ASR_VAD_PAD_MS")
    # Floor pass: speech share < MAX_SPEECH_SHARE while the rest is louder than -45 dBFS
    # → VAD again at a lower threshold (per channel), union of runs.
    asr_vad_floor_enabled: bool = Field(default=True, alias="MD_ASR_VAD_FLOOR_ENABLED")
    asr_vad_floor_threshold: float = Field(
        default=0.35, gt=0.0, lt=1.0, alias="MD_ASR_VAD_FLOOR_THRESHOLD"
    )
    asr_vad_floor_max_speech_share: float = Field(
        default=0.2, ge=0.0, le=1.0, alias="MD_ASR_VAD_FLOOR_MAX_SPEECH_SHARE"
    )
    # Runs left empty, mostly uncovered or mostly echo are decoded again without the prompt.
    asr_second_pass_enabled: bool = Field(default=True, alias="MD_ASR_SECOND_PASS_ENABLED")

    # ── Run planning and segment gates ──────────────────────────────────
    # HTTP backends: one request per group of same-language runs, at most this long.
    asr_http_group_seconds: float = Field(default=300.0, alias="MDX_ASR_HTTP_GROUP_SECONDS", gt=0)
    # Local LID model for HTTP backends; faster-whisper name or path.
    asr_lid_model: str = Field(default="tiny", alias="MDX_ASR_LID_MODEL")
    # Off = nothing dropped, diagnostics still record what would have been (``dry_run``).
    asr_gates_enabled: bool = Field(default=True, alias="MDX_ASR_GATES_ENABLED")
    # G1 silence text: no_speech ≥ this, avg_logprob below the next, VAD share below the share.
    asr_gate_no_speech: float = Field(default=0.6, alias="MDX_ASR_GATE_NO_SPEECH")
    asr_gate_logprob: float = Field(default=-1.0, alias="MDX_ASR_GATE_LOGPROB")
    asr_gate_speech_share: float = Field(default=0.3, alias="MDX_ASR_GATE_SPEECH_SHARE")
    # G2 loop: compression ratio above this, or a 2–6-gram repeated this many times.
    asr_gate_compression: float = Field(default=2.4, alias="MDX_ASR_GATE_COMPRESSION")
    asr_gate_loop_repeats: int = Field(default=4, alias="MDX_ASR_GATE_LOOP_REPEATS", ge=3)
    # G3 low confidence: mean word probability below this on a segment shorter than the next.
    asr_gate_low_confidence: float = Field(default=0.25, alias="MDX_ASR_GATE_LOW_CONFIDENCE")
    asr_gate_low_confidence_max_ms: int = Field(
        default=1500, alias="MDX_ASR_GATE_LOW_CONFIDENCE_MAX_MS"
    )
    # Known artefact phrase dropped when no_speech ≥ this (or VAD share below the G1 share).
    asr_gate_artefact_no_speech: float = Field(default=0.5, alias="MDX_ASR_GATE_ARTEFACT_NO_SPEECH")

    # ── Shadow ASR engine ───────────────────────────────────────────────
    # Backend name from config/models.yaml; empty = off. Only numeric differences are kept.
    asr_shadow_backend: str = Field(default="", alias="MDX_ASR_SHADOW_BACKEND")
    asr_shadow_rate: float = Field(default=0.2, alias="MDX_ASR_SHADOW_RATE", ge=0.0, le=1.0)
    # Audio hours a day, all workers together.
    asr_shadow_budget_hours: float = Field(default=4.0, alias="MDX_ASR_SHADOW_BUDGET_HOURS", ge=0.0)
    # The shadow may hold a job back at most this long beyond the primary.
    asr_shadow_max_wait_seconds: float = Field(
        default=120.0, alias="MDX_ASR_SHADOW_MAX_WAIT_SECONDS", gt=0
    )

    # ── Streaming-window hallucination guard ────────────────────────────
    # Silero VAD in front of the decoder drops silence-only windows that Whisper would
    # hallucinate on; timestamps map back onto the unfiltered window. Streaming path only.
    asr_streaming_vad_filter: bool = Field(default=True, alias="MD_ASR_STREAMING_VAD_FILTER")
    # Below the committer's 500 ms silence-smoothing threshold.
    asr_streaming_vad_min_silence_ms: int = Field(
        default=300, alias="MD_ASR_STREAMING_VAD_MIN_SILENCE_MS"
    )

    # ── Model sourcing / pinning ────────────────────────────────────────
    # Build-time provenance; `asr_model` still selects the weights.
    asr_engine: str = Field(default="faster_whisper", alias="MD_ASR_ENGINE")
    asr_model_repo: str = Field(
        default="Systran/faster-whisper-large-v3", alias="MD_ASR_MODEL_REPO"
    )
    asr_model_revision: str = Field(default="", alias="MD_ASR_MODEL_REVISION")
    asr_model_sha256: str = Field(default="", alias="MD_ASR_MODEL_SHA256")
    # Budget covers both decode passes.
    asr_max_inference_seconds_multiplier: float = Field(
        default=6.5, alias="MD_ASR_MAX_INFERENCE_SECONDS_MULTIPLIER"
    )
    asr_jobs_before_recycle: int = Field(default=100, alias="MD_ASR_JOBS_BEFORE_RECYCLE")

    # ── Model-provider seam (libs/models) ───────────────────────────────
    # `ASR_BACKEND` names a backend in config/models.yaml; validated at startup.
    asr_backend: str = Field(default="inproc_cpu_asr", alias="ASR_BACKEND")
    models_config: str = Field(default="config/models.yaml", alias="MODELS_CONFIG")
    # Registry env: dev | test | staging | prod; derived from ENVIRONMENT when unset.
    models_env: str = Field(default="", alias="ENV")

    @staticmethod
    def registry_environ() -> Mapping[str, str]:
        """Mapping for ``${VAR}`` in config/models.yaml; only config.py may read os.environ."""
        return os.environ

    def registry_env(self) -> str:
        if self.models_env:
            return self.models_env
        if self.testing:
            return "test"
        return {
            "development": "dev",
            "production": "prod",
            "test": "test",
            "staging": "staging",
        }.get(self.environment, self.environment)

    # ── Offline diarization ─────────────────────────────────────────────
    # ECAPA weights digest-verified at load (fail-closed, docs/models/PINS.md); loaded lazily.
    diar_model_dir: str = Field(default="/opt/models/ecapa", alias="MDX_DIAR_MODEL_DIR")
    diar_device: str = Field(default="cpu", alias="MDX_DIAR_DEVICE")
    diar_model_repo: str = Field(default="", alias="MDX_DIAR_MODEL_REPO")
    diar_model_revision: str = Field(default="", alias="MDX_DIAR_MODEL_REVISION")
    diar_model_sha256: str = Field(default="", alias="MDX_DIAR_MODEL_SHA256")
    diar_meanvar_sha256: str = Field(default="", alias="MDX_DIAR_MEANVAR_SHA256")

    # ── Diarizer engine selection ───────────────────────────────────────
    # `legacy` = ECAPA + agglomeration; `pyannote` = community-1 in-process;
    # `http` = community-1 on an endpoint (ADR-0052 shape B).
    diar_engine: str = Field(default="legacy", alias="MDX_DIAR_ENGINE")
    # Shadow engine: labels discarded, only counts and wall time kept. Empty = off.
    diar_shadow_engine: str = Field(default="", alias="MDX_DIAR_SHADOW_ENGINE")
    diar_v2_model_dir: str = Field(
        default="/opt/models/pyannote-community-1", alias="MDX_DIAR_V2_MODEL_DIR"
    )
    diar_v2_model_repo: str = Field(
        default="pyannote/speaker-diarization-community-1", alias="MDX_DIAR_V2_MODEL_REPO"
    )
    diar_v2_model_revision: str = Field(default="", alias="MDX_DIAR_V2_MODEL_REVISION")
    # filename → sha256, JSON (docs/models/PINS.md). Verified at load, fail-closed.
    diar_v2_pins: str = Field(default="", alias="MDX_DIAR_V2_PINS")
    # Windows embedded at once; 0 = 16 on CPU, 32 on GPU.
    diar_v2_batch: int = Field(default=0, alias="MDX_DIAR_V2_BATCH")
    # Roster guard, both engines; both 0 = grade only, dissolve nothing (ADR-0052).
    diar_min_speaker_speech_ms: int = Field(default=8000, alias="MDX_DIAR_MIN_SPEAKER_SPEECH_MS")
    diar_min_speaker_share: float = Field(default=0.03, alias="MDX_DIAR_MIN_SPEAKER_SHARE")
    # Engine=http: backend in config/models.yaml; empty = the env's `diarization` override.
    diar_http_backend: str = Field(default="", alias="MDX_DIAR_HTTP_BACKEND")
    # X-MDX-Diar-Token: a managed gateway eats `Authorization`; empty = send the bearer in both.
    diar_http_token: str = Field(default="", alias="MDX_DIAR_SERVER_TOKEN")
    # Timeout slope, seconds per audio second; a CPU-hosted endpoint needs more (ADR-0052).
    diar_http_seconds_per_audio_second: float = Field(
        default=0.5, alias="MDX_DIAR_HTTP_SECONDS_PER_AUDIO_SECOND"
    )

    def diar_v2_pin_map(self) -> dict[str, str]:
        if not self.diar_v2_pins.strip():
            return {}
        raw = json.loads(self.diar_v2_pins)
        if not isinstance(raw, dict):
            raise ValueError("MDX_DIAR_V2_PINS must be a JSON object of filename → sha256")
        return {str(k): str(v) for k, v in raw.items()}

    def diar_v2_batch_size(self) -> int:
        if self.diar_v2_batch > 0:
            return self.diar_v2_batch
        return 32 if self.diar_device.startswith("cuda") else 16

    # ── Database / queue / storage ──────────────────────────────────────
    db_app_role_dsn: str = Field(
        default="postgresql://app_role:app_role@postgres:5432/notes",
        alias="DB_APP_ROLE_DSN",
    )
    db_audit_writer_dsn: str = Field(
        default="postgresql://audit_writer:audit_writer@postgres:5432/notes",
        alias="DB_AUDIT_WRITER_DSN",
    )
    db_crypto_writer_dsn: str = Field(
        default="postgresql://crypto_writer:crypto_writer@postgres:5432/notes",
        alias="DB_CRYPTO_WRITER_DSN",
    )

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # Notification bus kill switch (ADR-0029).
    notifications_enabled: bool = Field(default=True, alias="MDX_NOTIFICATIONS_ENABLED")

    asr_jobs_stream: str = Field(default="asr:jobs", alias="MD_ASR_JOBS_STREAM")
    asr_jobs_dlq_stream: str = Field(default="asr:jobs:dlq", alias="MD_ASR_JOBS_DLQ_STREAM")
    asr_jobs_group: str = Field(default="asr-workers", alias="MD_ASR_JOBS_GROUP")
    asr_jobs_max_retries: int = Field(default=3, alias="MD_ASR_JOBS_MAX_RETRIES")
    asr_jobs_idle_reclaim_ms: int = Field(default=60_000, alias="MD_ASR_JOBS_IDLE_RECLAIM_MS")

    s3_endpoint: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key: str = Field(default="minioadmin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", alias="S3_SECRET_KEY")
    s3_audio_bucket: str = Field(default="mdx-audio", alias="S3_AUDIO_BUCKET")
    s3_transcripts_bucket: str = Field(default="mdx-transcripts", alias="S3_TRANSCRIPTS_BUCKET")
    s3_use_ssl: bool = Field(default=False, alias="S3_USE_SSL")

    master_key_path: str = Field(default="/etc/mdx/master.key", alias="MDX_MASTER_KEY_PATH")

    # ── Master-key provider (ADR-0011) ──────────────────────────────────
    # 'file' or 'vault' (fail-closed probe); with 'vault' the file stays a read-only
    # fallback for rows not yet re-wrapped.
    master_key_provider: str = Field(default="file", alias="MDX_MASTER_KEY_PROVIDER")
    vault_addr: str = Field(default="http://localhost:8200", alias="MDX_VAULT_ADDR")
    vault_token: SecretStrEnv = Field(default_factory=lambda: Secret(""), alias="MDX_VAULT_TOKEN")
    vault_transit_key: str = Field(default="mdx-master", alias="MDX_VAULT_TRANSIT_KEY")
    vault_transit_mount: str = Field(default="transit", alias="MDX_VAULT_TRANSIT_MOUNT")

    ffmpeg_path: str = Field(default="ffmpeg", alias="MD_ASR_FFMPEG_PATH")
    ffmpeg_timeout_seconds: float = Field(default=30.0, alias="MD_ASR_FFMPEG_TIMEOUT_SECONDS")

    worker_consumer_name: str = Field(default="worker-1", alias="MD_ASR_WORKER_NAME")


# pyannote telemetry and HF hub access forced off at import, before pyannote can be
# imported; an inherited "true" must not win. The v2 engine re-checks these.
PYANNOTE_PROCESS_ENV: Mapping[str, str] = {
    "PYANNOTE_METRICS_ENABLED": "false",
    "HF_HUB_OFFLINE": "1",
}
os.environ.update(PYANNOTE_PROCESS_ENV)

settings = Settings()
