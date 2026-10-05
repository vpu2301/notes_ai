"""dictation-service configuration. All env vars read here."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from secret import Secret

# pydantic-settings json.loads() generic types from env; NoDecode hands the raw
# string to Secret's validator. Every env-fed Secret field must use this alias.
SecretStrEnv = Annotated[Secret[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "dictation-service"
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
    # ADR-0047: JSON list `[{"issuer", "jwks_url", "audience"}, …]`; the token's
    # `iss` selects the entry. Unset = one-element list from the values above.
    auth_issuers_json: str = Field(default="", alias="AUTH_ISSUERS_JSON")
    auth_clock_skew_seconds: int = Field(default=30, alias="AUTH_CLOCK_SKEW_SECONDS")

    # ── Database ────────────────────────────────────────────────────────
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
    db_pool_max_size: int = Field(default=8, alias="DB_POOL_MAX_SIZE")

    # ── Redis (rate-limit + worker liveness + notification bus) ────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── Notification event bus (ADR-0029) ──────────────────────────────
    # Kill switch shared with note-service; source-level cut-off for a storm.
    notifications_enabled: bool = Field(default=True, alias="MDX_NOTIFICATIONS_ENABLED")

    # ── S3 object storage (finalized audio uploads) ────────────────────
    s3_endpoint: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key: str = Field(default="minioadmin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", alias="S3_SECRET_KEY")
    s3_audio_bucket: str = Field(default="mdx-audio", alias="S3_AUDIO_BUCKET")
    s3_use_ssl: bool = Field(default=False, alias="S3_USE_SSL")

    # ── Demo privacy envelope (ADR-0018) ────────────────────────────────
    # Disabled = no finalized audio reaches object storage; purge also zeroes the PCM buffer.
    object_store_disabled: bool = Field(default=False, alias="MD_OBJECT_STORE_DISABLED")
    demo_audio_purge_on_finalize: bool = Field(default=False, alias="DEMO_AUDIO_PURGE_ON_FINALIZE")

    # ── Master key (envelope crypto for finalized uploads) ──────────────
    master_key_path: str = Field(default="/etc/mdx/master.key", alias="MDX_MASTER_KEY_PATH")

    # ── Master-key provider (ADR-0011) ──────────────────────────────────
    # 'file' (dev) or 'vault' (Transit, fail-closed probe); with 'vault' the
    # file stays a read-only fallback for rows not yet re-wrapped.
    master_key_provider: str = Field(default="file", alias="MDX_MASTER_KEY_PROVIDER")
    vault_addr: str = Field(default="http://localhost:8200", alias="MDX_VAULT_ADDR")
    vault_token: SecretStrEnv = Field(default_factory=lambda: Secret(""), alias="MDX_VAULT_TOKEN")
    vault_transit_key: str = Field(default="mdx-master", alias="MDX_VAULT_TRANSIT_KEY")
    vault_transit_mount: str = Field(default="transit", alias="MDX_VAULT_TRANSIT_MOUNT")

    # ── Streaming protocol ──────────────────────────────────────────────
    ws_subprotocol: str = Field(default="dictation.v1", alias="MDX_WS_SUBPROTOCOL")
    ws_heartbeat_interval_s: float = Field(default=10.0, alias="MDX_WS_HEARTBEAT_INTERVAL_S")
    ws_idle_timeout_s: float = Field(default=35.0, alias="MDX_WS_IDLE_TIMEOUT_S")
    ws_max_binary_frame_bytes: int = Field(default=8 * 1024, alias="MDX_WS_MAX_BINARY_FRAME_BYTES")
    ws_idle_close_after_no_session_s: float = Field(
        default=10.0, alias="MDX_WS_IDLE_CLOSE_AFTER_NO_SESSION_S"
    )

    # ── Rate limits on the upgrade endpoint ─────────────────────────────
    upgrade_ratelimit_per_ip_per_minute: int = Field(
        default=10, alias="MDX_UPGRADE_RATELIMIT_PER_IP_PER_MINUTE"
    )
    upgrade_ratelimit_per_user_per_hour: int = Field(
        default=30, alias="MDX_UPGRADE_RATELIMIT_PER_USER_PER_HOUR"
    )

    # ── Session lifecycle ───────────────────────────────────────────────
    session_idle_abandon_minutes: int = Field(default=30, alias="MDX_SESSION_IDLE_ABANDON_MINUTES")
    session_hard_cap_minutes: int = Field(default=60, alias="MDX_SESSION_HARD_CAP_MINUTES")
    session_token_expiry_warn_seconds: int = Field(
        default=60, alias="MDX_SESSION_TOKEN_EXPIRY_WARN_SECONDS"
    )

    # ── Stale-session reaper ────────────────────────────────────────────
    # Out-of-process backstop for sessions stranded by a dead worker; only
    # touches sessions whose worker heartbeat has expired.
    session_reaper_enabled: bool = Field(default=True, alias="MDX_SESSION_REAPER_ENABLED")
    session_reaper_interval_s: float = Field(default=300.0, alias="MDX_SESSION_REAPER_INTERVAL_S")
    # Must comfortably exceed worker_heartbeat_ttl_s (rolling restart != crash).
    session_reaper_grace_s: float = Field(default=300.0, alias="MDX_SESSION_REAPER_GRACE_S")
    session_reaper_batch_limit: int = Field(default=200, alias="MDX_SESSION_REAPER_BATCH_LIMIT")

    # ── Windowing / inference ───────────────────────────────────────────
    window_seconds: float = Field(default=4.0, alias="MDX_WINDOW_SECONDS")
    window_overlap_seconds: float = Field(default=2.0, alias="MDX_WINDOW_OVERLAP_SECONDS")
    window_min_for_partial_seconds: float = Field(
        default=1.5, alias="MDX_WINDOW_MIN_FOR_PARTIAL_SECONDS"
    )
    window_tick_interval_ms: int = Field(default=600, alias="MDX_WINDOW_TICK_INTERVAL_MS")
    window_inference_deadline_multiplier: float = Field(
        default=1.5, alias="MDX_WINDOW_INFERENCE_DEADLINE_MULTIPLIER"
    )
    no_speech_prob_drop_threshold: float = Field(
        default=0.6, alias="MDX_NO_SPEECH_PROB_DROP_THRESHOLD"
    )
    # A word older than this commits without a VAD boundary, so continuous
    # speech never stalls the transcript (2× the commit horizon).
    commit_max_provisional_ms: int = Field(default=4000, alias="MDX_COMMIT_MAX_PROVISIONAL_MS")
    aligner_boundary_uncertainty_threshold: float = Field(
        default=0.30, alias="MDX_ALIGNER_BOUNDARY_UNCERTAINTY_THRESHOLD"
    )
    prompt_max_tokens: int = Field(default=150, alias="MDX_PROMPT_MAX_TOKENS")
    # Fallback initial_prompt when start_session carries no vocabulary hint.
    default_vocabulary_hint: str = Field(default="", alias="MDX_DEFAULT_VOCABULARY_HINT")

    # ── Conversation mode / diarization (ADR-0034) ──────────────────────
    conversation_enabled: bool = Field(default=True, alias="MDX_CONVERSATION_ENABLED")
    # Baked model dir from scripts/models/prepare_ecapa.py (`make prepare-ecapa`).
    diar_model_dir: str = Field(default="/opt/models/ecapa", alias="MDX_DIAR_MODEL_DIR")
    # The GPU compose overlay sets MDX_DIAR_DEVICE=cuda.
    diar_device: str = Field(default="cpu", alias="MDX_DIAR_DEVICE")
    # Digests stamped by the Dockerfile (docs/models/PINS.md), re-asserted at
    # startup fail-closed. Empty = dev path: presence checked, content only logged.
    diar_model_repo: str = Field(default="", alias="MDX_DIAR_MODEL_REPO")
    diar_model_revision: str = Field(default="", alias="MDX_DIAR_MODEL_REVISION")
    diar_model_sha256: str = Field(default="", alias="MDX_DIAR_MODEL_SHA256")
    diar_meanvar_sha256: str = Field(default="", alias="MDX_DIAR_MEANVAR_SHA256")
    # Warm both models at startup; a cold diarizer blows the first-window budget.
    diar_warm_at_startup: bool = Field(default=True, alias="MDX_DIAR_WARM_AT_STARTUP")
    # Weight 2 => 4 dictation OR 2 conversation OR 2+1 mix per worker; not GPU-measured.
    conversation_session_weight: int = Field(default=2, alias="MDX_CONVERSATION_SESSION_WEIGHT")

    # ── Finalize-time NLP + draft creation ──────────────────────────────
    # Not latency-critical; raw transcript persists if either call fails.
    nlp_base_url: str = Field(default="http://nlp-service:8000", alias="MDX_NLP_BASE_URL")
    finalize_nlp_timeout_seconds: float = Field(
        default=5.0, alias="MDX_FINALIZE_NLP_TIMEOUT_SECONDS"
    )
    note_base_url: str = Field(default="http://note-service:8000", alias="MDX_NOTE_BASE_URL")
    note_draft_timeout_seconds: float = Field(default=5.0, alias="MDX_NOTE_DRAFT_TIMEOUT_SECONDS")

    # ── Concurrency cap per GPU worker ──────────────────────────────────
    per_worker_max_sessions: int = Field(default=4, alias="MDX_PER_WORKER_MAX_SESSIONS")
    per_tenant_max_active_sessions: int = Field(
        default=10, alias="MDX_PER_TENANT_MAX_ACTIVE_SESSIONS"
    )
    retransmit_max_range_frames: int = Field(
        default=1500,
        alias="MDX_RETRANSMIT_MAX_RANGE_FRAMES",  # 30s @ 50fps
    )

    # ── tmpfs ring buffer ───────────────────────────────────────────────
    tmpfs_root: str = Field(default="/run/dictation", alias="MDX_TMPFS_ROOT")
    # 30 min × 60 s × 16 000 Hz × 4 bytes = 115 200 000 bytes
    tmpfs_ring_seconds: int = Field(default=30 * 60, alias="MDX_TMPFS_RING_SECONDS")

    # ── Worker identity (Redis liveness key) ────────────────────────────
    worker_id: str = Field(default="worker-1", alias="MDX_WORKER_ID")
    worker_heartbeat_interval_s: float = Field(default=5.0, alias="MDX_WORKER_HEARTBEAT_INTERVAL_S")
    worker_heartbeat_ttl_s: float = Field(default=30.0, alias="MDX_WORKER_HEARTBEAT_TTL_S")

    # ── Origin allow-list for WS upgrades ──────────────────────────────
    ws_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"],
        alias="MDX_WS_ALLOWED_ORIGINS",
    )

    # ── CORS for the SPA (dev origins) ─────────────────────────────────
    # WS upgrades are gated separately by ws_allowed_origins.
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        alias="CORS_ALLOWED_ORIGINS",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    # ── Startup model warmup ────────────────────────────────────────────
    # false: blocking load. true: background load; /healthz serves at once,
    # /readyz stays 503 until the models are resident.
    warm_in_background: bool = Field(default=False, alias="MDX_WARM_IN_BACKGROUND")

    # ── Session revocation check (ADR-0040) ─────────────────────────────
    # Rejects tokens on the Redis denylist; fail-OPEN on Redis outage.
    session_revocation_enabled: bool = Field(default=False, alias="MDX_SESSION_REVOCATION_ENABLED")


settings = Settings()
