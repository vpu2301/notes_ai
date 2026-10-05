"""asr-service configuration. All env vars read here (sprint-01 hook enforced)."""

from __future__ import annotations

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

    service_name: str = "asr-service"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    testing: bool = Field(default=False, alias="TESTING")

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_sdk_disabled: bool = Field(default=False, alias="OTEL_SDK_DISABLED")

    # ── libs/auth (Keycloak) ─────────────────────────────────────────────
    auth_issuer: str = Field(
        default="http://localhost:8088/realms/notes",
        alias="AUTH_ISSUER",
    )
    auth_jwks_url: str = Field(
        default="http://localhost:8088/realms/notes/protocol/openid-connect/certs",
        alias="AUTH_JWKS_URL",
    )
    auth_audience: str = Field(default="mdx-api", alias="AUTH_AUDIENCE")
    # ADR-0047: JSON list `[{"issuer", "jwks_url", "audience"}, …]`; the token's `iss`
    # selects the entry. Unset = a one-element list from the three values above.
    auth_issuers_json: str = Field(default="", alias="AUTH_ISSUERS_JSON")
    auth_clock_skew_seconds: int = Field(default=30, alias="AUTH_CLOCK_SKEW_SECONDS")

    # ── CORS (SPA integration) ──────────────────────────────────────────
    # Explicit origins, never "*": allow_credentials=True forbids the wildcard.
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        alias="CORS_ALLOWED_ORIGINS",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    # ── Database DSNs ───────────────────────────────────────────────────
    db_app_role_dsn: str = Field(
        default="postgresql://app_role:app_role@localhost:5432/notes",
        alias="DB_APP_ROLE_DSN",
    )
    db_audit_writer_dsn: str = Field(
        default="postgresql://audit_writer:audit_writer@localhost:5432/notes",
        alias="DB_AUDIT_WRITER_DSN",
    )
    db_crypto_writer_dsn: str = Field(
        default="postgresql://crypto_writer:crypto_writer@localhost:5432/notes",
        alias="DB_CRYPTO_WRITER_DSN",
    )
    db_pool_min_size: int = Field(default=1, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=10, alias="DB_POOL_MAX_SIZE")

    # ── Redis Streams (libs/messaging concrete impl) ────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    asr_jobs_stream: str = Field(default="asr:jobs", alias="MD_ASR_JOBS_STREAM")
    asr_jobs_dlq_stream: str = Field(default="asr:jobs:dlq", alias="MD_ASR_JOBS_DLQ_STREAM")
    asr_jobs_group: str = Field(default="asr-workers", alias="MD_ASR_JOBS_GROUP")
    asr_jobs_maxlen: int = Field(default=100_000, alias="MD_ASR_JOBS_MAXLEN")

    # ── S3 object storage ──────────────────────────────────────────────────
    s3_endpoint: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key: str = Field(default="minioadmin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", alias="S3_SECRET_KEY")
    s3_audio_bucket: str = Field(default="mdx-audio", alias="S3_AUDIO_BUCKET")
    s3_transcripts_bucket: str = Field(default="mdx-transcripts", alias="S3_TRANSCRIPTS_BUCKET")
    s3_use_ssl: bool = Field(default=False, alias="S3_USE_SSL")
    s3_presigned_ttl_seconds: int = Field(default=300, alias="S3_PRESIGNED_TTL_SECONDS")

    # ── Master key (envelope crypto) ────────────────────────────────────
    master_key_path: str = Field(default="/etc/mdx/master.key", alias="MDX_MASTER_KEY_PATH")

    # ── Master-key provider (ADR-0011) ──────────────────────────────────
    # 'file' or 'vault' (fail-closed probe); with 'vault' the file stays a read-only
    # fallback for rows not yet re-wrapped.
    master_key_provider: str = Field(default="file", alias="MDX_MASTER_KEY_PROVIDER")
    vault_addr: str = Field(default="http://localhost:8200", alias="MDX_VAULT_ADDR")
    vault_token: SecretStrEnv = Field(default_factory=lambda: Secret(""), alias="MDX_VAULT_TOKEN")
    vault_transit_key: str = Field(default="mdx-master", alias="MDX_VAULT_TRANSIT_KEY")
    vault_transit_mount: str = Field(default="transit", alias="MDX_VAULT_TRANSIT_MOUNT")

    # ── Upload validation ───────────────────────────────────────────────
    # Clients read these (GET /asr/limits) and stop at them. 250 MB ≈ two hours of WAV.
    max_upload_mb: int = Field(default=250, alias="MD_ASR_MAX_UPLOAD_MB")
    max_duration_seconds: int = Field(default=2 * 3600, alias="MD_ASR_MAX_DURATION_SECONDS")
    # Floor: below this Whisper answers noise with a confident hallucination.
    min_duration_ms: int = Field(default=400, alias="MD_ASR_MIN_DURATION_MS")
    min_sample_rate_hz: int = Field(default=8000, alias="MD_ASR_MIN_SAMPLE_RATE_HZ")
    max_channels: int = Field(default=2, alias="MD_ASR_MAX_CHANNELS")
    monthly_quota_bytes: int = Field(
        default=10 * 1024 * 1024 * 1024, alias="MD_ASR_MONTHLY_QUOTA_BYTES"
    )
    ffprobe_path: str = Field(default="ffprobe", alias="MD_ASR_FFPROBE_PATH")
    ffprobe_timeout_seconds: float = Field(default=5.0, alias="MD_ASR_FFPROBE_TIMEOUT_SECONDS")

    # ── Concurrency limits ──────────────────────────────────────────────
    per_tenant_concurrent_jobs: int = Field(default=10, alias="MD_ASR_PER_TENANT_CONCURRENT_JOBS")

    # ── Stranded-job reaper ─────────────────────────────────────────────
    # The grace windows are the ONLY interlock (no worker heartbeat). Keep `running`
    # above max_duration_seconds × the worker's inference multiplier (2 h × 6.5 = 13 h
    # at the defaults), plus a redelivery.
    job_reaper_enabled: bool = Field(default=True, alias="MD_ASR_JOB_REAPER_ENABLED")
    job_reaper_interval_s: float = Field(default=300.0, alias="MD_ASR_JOB_REAPER_INTERVAL_S")
    job_reaper_running_grace_s: float = Field(
        default=14 * 3600.0, alias="MD_ASR_JOB_REAPER_RUNNING_GRACE_S"
    )
    # Unclaimed this long = lost, not backlogged.
    job_reaper_queued_grace_s: float = Field(
        default=6 * 3600.0, alias="MD_ASR_JOB_REAPER_QUEUED_GRACE_S"
    )
    job_reaper_batch_limit: int = Field(default=100, alias="MD_ASR_JOB_REAPER_BATCH_LIMIT")

    # ── Speaker re-labelling (POST /asr/jobs/{id}/rediarize) ────────────
    # A full diarization pass: capped per job (one in flight, this many total) and per user/hour.
    rediarize_max_runs: int = Field(default=5, alias="MD_ASR_REDIARIZE_MAX_RUNS")
    rediarize_user_hourly_limit: int = Field(default=10, alias="MD_ASR_REDIARIZE_USER_HOURLY_LIMIT")

    # ── Name suggestions + re-label offer ───────────────────────────────
    # Suggestions ship dark until the shadow experiment shows ≥ 95 % precision.
    name_suggestions_enabled: bool = Field(default=False, alias="MDX_NAME_SUGGESTIONS_ENABLED")
    # Spelling unification. Off = the view is the artefact; auto-apply off = every
    # correction is a proposal a person accepts.
    entity_unify_enabled: bool = Field(default=True, alias="MDX_ENTITY_UNIFY_ENABLED")
    entity_unify_auto_apply: bool = Field(default=True, alias="MDX_ENTITY_UNIFY_AUTO_APPLY")
    # Unifier budget per audio hour (over = ``skipped_budget``); never below the floor.
    entity_unify_budget_s_per_hour: float = Field(
        default=2.0, alias="MDX_ENTITY_UNIFY_BUDGET_S_PER_HOUR"
    )
    entity_unify_budget_floor_s: float = Field(default=0.5, alias="MDX_ENTITY_UNIFY_BUDGET_FLOOR_S")
    entity_unify_recompute_hourly_limit: int = Field(
        default=20, alias="MDX_ENTITY_UNIFY_RECOMPUTE_HOURLY_LIMIT", ge=1
    )
    # The worker's current engine id; a transcript by another one is offered a re-label.
    current_diar_engine: str = Field(default="legacy-ecapa-ahc", alias="MDX_DIAR_CURRENT_ENGINE")

    # ── NLP batch enrichment ────────────────────────────────────────────
    # The result view runs through nlp-service; degrades to the raw transcript.
    nlp_enrich_enabled: bool = Field(default=True, alias="MD_ASR_NLP_ENRICH_ENABLED")
    nlp_base_url: str = Field(default="http://localhost:8005", alias="MD_ASR_NLP_BASE_URL")
    nlp_timeout_seconds: float = Field(default=10.0, alias="MD_ASR_NLP_TIMEOUT_SECONDS")

    # ── Session revocation check ────────────────────────────────────────
    # Redis denylist pushed by auth-service; fail-OPEN on Redis outage (ADR-0040).
    session_revocation_enabled: bool = Field(default=False, alias="MDX_SESSION_REVOCATION_ENABLED")


settings = Settings()
