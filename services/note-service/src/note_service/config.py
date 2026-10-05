"""note-service configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from secret import Secret

# pydantic-settings json.loads() a generic Secret[str] from the env (JSONDecodeError on
# plain strings); NoDecode hands the raw string to the validator. Use for every env Secret.
SecretStrEnv = Annotated[Secret[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "note-service"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    testing: bool = Field(default=False, alias="TESTING")

    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_sdk_disabled: bool = Field(default=False, alias="OTEL_SDK_DISABLED")

    auth_issuer: str = Field(
        default="http://localhost:8088/realms/notes",
        alias="AUTH_ISSUER",
    )
    auth_jwks_url: str = Field(
        default="http://localhost:8088/realms/notes/protocol/openid-connect/certs",
        alias="AUTH_JWKS_URL",
    )
    auth_audience: str = Field(default="mdx-api", alias="AUTH_AUDIENCE")
    # ADR-0047: JSON `[{"issuer", "jwks_url", "audience"}, …]`; the token's `iss`
    # selects the entry. Unset: the three values above form a one-element list.
    auth_issuers_json: str = Field(default="", alias="AUTH_ISSUERS_JSON")
    auth_clock_skew_seconds: int = Field(default=30, alias="AUTH_CLOCK_SKEW_SECONDS")

    # ── CORS ────────────────────────────────────────────────────────────
    # Explicit origins only, never "*": allow_credentials=True forbids the wildcard.
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        alias="CORS_ALLOWED_ORIGINS",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    db_app_role_dsn: str = Field(
        default="postgresql://app_role:app_role@localhost:5432/notes",
        alias="DB_APP_ROLE_DSN",
    )
    db_audit_writer_dsn: str = Field(
        default="postgresql://audit_writer:audit_writer@localhost:5432/notes",
        alias="DB_AUDIT_WRITER_DSN",
    )
    db_pool_min_size: int = Field(default=1, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=8, alias="DB_POOL_MAX_SIZE")

    # Notification event bus (ADR-0029).
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    # Escape hatch: false stops emitting entirely.
    notifications_enabled: bool = Field(default=True, alias="MDX_NOTIFICATIONS_ENABLED")

    # In-process TTLCache for templates
    template_cache_maxsize: int = Field(default=5000, alias="MDX_TEMPLATE_CACHE_MAXSIZE")
    template_cache_ttl_seconds: int = Field(default=60, alias="MDX_TEMPLATE_CACHE_TTL_SECONDS")

    # Issuing organisation printed on the exported PDF.
    pdf_issuer_name: str = Field(default="Notes AI", alias="MDX_PDF_ISSUER_NAME")

    # ── Recipient links and the shared page ─────────────────────────────
    # Brand name in the shared page's product header.
    product_brand_name: str = Field(default="Notes AI", alias="MDX_PRODUCT_BRAND_NAME")
    # Recipient links expire by default; public links still do not.
    recipient_link_default_days: int = Field(default=90, alias="MDX_RECIPIENT_LINK_DEFAULT_DAYS")
    # Abuse caps on the anonymous /v1/shared/* surface (domain/public_rate_limit).
    # Fail-open: a Redis outage must not take every client-facing page down.
    shared_rl_ip_per_minute: int = Field(default=60, alias="MDX_SHARED_RL_IP_PER_MINUTE")
    shared_rl_link_per_hour: int = Field(default=300, alias="MDX_SHARED_RL_LINK_PER_HOUR")
    shared_rl_cta_per_hour: int = Field(default=20, alias="MDX_SHARED_RL_CTA_PER_HOUR")
    # CIDRs whose X-Forwarded-For is believed (same rule as libs/ratelimit). Empty:
    # the TCP peer is the client, so behind an untrusted proxy every reader shares one bucket.
    trusted_proxy_cidrs: str = Field(default="", alias="TRUSTED_PROXY_CIDRS")
    # ── Recipient mail ──────────────────────────────────────────────────
    # Public base of the anonymous API; the unsubscribe link is built from it.
    api_public_base_url: str = Field(
        default="http://localhost:8006", alias="MDX_API_PUBLIC_BASE_URL"
    )
    # Sends per link, per sender and per workspace, per day.
    share_mail_link_per_day: int = Field(default=3, alias="MDX_SHARE_MAIL_LINK_PER_DAY")
    share_mail_user_per_day: int = Field(default=50, alias="MDX_SHARE_MAIL_USER_PER_DAY")
    share_mail_tenant_per_day: int = Field(default=200, alias="MDX_SHARE_MAIL_TENANT_PER_DAY")
    # Pepper for the opt-out hash (hex); dev default is NOT a secret. Rotating it
    # orphans every suppression row.
    share_mail_suppression_pepper_hex: str = Field(
        default="6d64782d6465762d73686172652d6d61696c2d7065707065722d3030303030",
        alias="MDX_SHARE_MAIL_SUPPRESSION_PEPPER_HEX",
    )
    # ── External sharing flags, verification, retention ─────────────────
    # Master switch: off → no recipient/public links; the anonymous page answers 404.
    external_sharing_enabled: bool = Field(default=True, alias="MDX_EXTERNAL_SHARING_ENABLED")
    # Off → the page reads but nobody can confirm/dispute/flag.
    recipient_actions_enabled: bool = Field(default=True, alias="MDX_RECIPIENT_ACTIONS_ENABLED")
    # Recipient one-time codes (policy `verified_recipients_required`).
    share_otp_ttl_seconds: int = Field(default=600, alias="MDX_SHARE_OTP_TTL_SECONDS")
    share_otp_max_attempts: int = Field(default=5, alias="MDX_SHARE_OTP_MAX_ATTEMPTS")
    # Links expired longer than this lose responses, address and codes.
    share_retention_days: int = Field(default=30, alias="MDX_SHARE_RETENTION_DAYS")
    # Writes per link per hour on the anonymous page.
    shared_rl_write_per_hour: int = Field(default=60, alias="MDX_SHARED_RL_WRITE_PER_HOUR")
    # The author is told once per link per this many seconds.
    response_notify_debounce_s: int = Field(default=600, alias="MDX_RESPONSE_NOTIFY_DEBOUNCE_S")
    # `rules` is the deterministic parser; the seam exists for a model later.
    action_item_extractor: Literal["rules"] = Field(
        default="rules", alias="MDX_ACTION_ITEM_EXTRACTOR"
    )

    # Typed-field extraction (ADR-0028). Fail-open: an unreachable nlp-service costs proposals, not drafts.
    nlp_service_base_url: str = Field(
        default="http://localhost:8005", alias="MDX_NLP_SERVICE_BASE_URL"
    )

    # create-from-transcript fetches the job's transcript here, forwarding the caller's JWT.
    asr_service_base_url: str = Field(default="http://localhost:8001", alias="ASR_SERVICE_BASE_URL")

    # ── Chat provider (libs/models, ADR-0046) ───────────────────────────
    # Resolved on first use, so a Mac without a model server still serves notes.
    models_config: str = Field(default="config/models.yaml", alias="MODELS_CONFIG")
    # Registry env: dev | test | staging | prod; derived from ENVIRONMENT when unset.
    models_env: str = Field(default="", alias="ENV")
    # Dev only: forces a chat backend. Ignored outside dev/test; refused in a production config.
    dev_chat_backend: str = Field(default="", alias="MDX_DEV_CHAT_BACKEND")
    ask_max_tokens: int = Field(default=700, alias="MDX_ASK_MAX_TOKENS")
    # How much of the note + transcript goes into the prompt (characters).
    ask_context_chars: int = Field(default=60_000, alias="MDX_ASK_CONTEXT_CHARS")

    @staticmethod
    def registry_environ() -> Mapping[str, str]:
        """Mapping for ``${VAR}`` placeholders in config/models.yaml; here because only
        config.py may read the process environment (check-no-os-environ gate)."""
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

    # ── Audio replay (ADR-0037): same S3+crypto wiring and env names as dictation-service ──
    db_crypto_writer_dsn: str = Field(
        default="postgresql://crypto_writer:crypto_writer@localhost:5432/notes",
        alias="DB_CRYPTO_WRITER_DSN",
    )
    master_key_path: str = Field(default="/etc/mdx/master.key", alias="MDX_MASTER_KEY_PATH")

    # ── Master-key provider (ADR-0011) ──────────────────────────────────
    # 'file' or 'vault' (fail-closed startup probe). With 'vault', master_key_path
    # stays a read-only fallback for rows not yet re-wrapped.
    master_key_provider: str = Field(default="file", alias="MDX_MASTER_KEY_PROVIDER")
    vault_addr: str = Field(default="http://localhost:8200", alias="MDX_VAULT_ADDR")
    vault_token: SecretStrEnv = Field(default_factory=lambda: Secret(""), alias="MDX_VAULT_TOKEN")
    vault_transit_key: str = Field(default="mdx-master", alias="MDX_VAULT_TRANSIT_KEY")
    vault_transit_mount: str = Field(default="transit", alias="MDX_VAULT_TRANSIT_MOUNT")
    s3_endpoint: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key: str = Field(default="minioadmin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", alias="S3_SECRET_KEY")
    s3_use_ssl: bool = Field(default=False, alias="S3_USE_SSL")
    s3_audio_bucket: str = Field(default="mdx-audio", alias="S3_AUDIO_BUCKET")
    s3_transcripts_bucket: str = Field(default="mdx-transcripts", alias="S3_TRANSCRIPTS_BUCKET")
    # 1-day bucket ILM is a backstop; the real lifetime is the Redis registry + token TTL.
    s3_clips_bucket: str = Field(default="mdx-audio-clips", alias="S3_CLIPS_BUCKET")
    object_store_disabled: bool = Field(default=False, alias="MD_OBJECT_STORE_DISABLED")

    # HMAC key for clip download tokens (hex); dev default is NOT a secret. Rotate freely.
    clip_token_hmac_key_hex: str = Field(
        default="6d64782d6465762d636c69702d746f6b656e2d6b65792d3030303030303030",
        alias="MDX_CLIP_TOKEN_HMAC_KEY_HEX",
    )
    clip_token_ttl_seconds: int = Field(default=300, alias="MDX_CLIP_TOKEN_TTL_SECONDS")
    # HMAC key for public share tokens (hex); dev default is NOT a secret. Rotating it
    # invalidates every public link.
    share_link_hmac_key_hex: str = Field(
        default="6d64782d6465762d73686172652d6c696e6b2d6b65792d3030303030303030",
        alias="MDX_SHARE_LINK_HMAC_KEY_HEX",
    )
    # Document engine. Without a chat backend no generation starts; the note keeps its transcript.
    note_generation_enabled: bool = Field(default=True, alias="MDX_NOTE_GENERATION_ENABLED")
    # How many generations one tenant may have in flight at once.
    note_generation_per_tenant: int = Field(default=3, alias="MDX_NOTE_GENERATION_PER_TENANT")
    # One bounded model call per generation to respell unknown names. OFF: precision
    # on the small model was 0/8; enable per environment only with an eval clearing 0.9.
    note_entity_model_tier: bool = Field(default=False, alias="MDX_NOTE_ENTITY_MODEL_TIER")
    # `none` shows plans and changes nothing; `manual` changes the plan at once; `stripe` later.
    billing_provider: Literal["none", "manual"] = Field(
        default="none", alias="MDX_BILLING_PROVIDER"
    )
    # Past this many seconds per recording hour the coverage re-read is skipped and the
    # thin third named as missing. Unset: no limit (no backend meets the 300 s target yet).
    note_coverage_retry_budget_s_per_hour: float | None = Field(
        default=None, alias="MDX_NOTE_COVERAGE_RETRY_BUDGET_S_PER_HOUR"
    )
    clip_max_span_ms: int = Field(default=60_000, alias="MDX_CLIP_MAX_SPAN_MS")
    clip_pad_ms: int = Field(default=300, alias="MDX_CLIP_PAD_MS")
    # The cap defends against bulk extraction, not normal evidence playback.
    clips_per_user_per_hour: int = Field(default=60, alias="MDX_CLIPS_PER_USER_PER_HOUR")
    ffmpeg_path: str = Field(default="ffmpeg", alias="MDX_FFMPEG_PATH")

    # ── In-process scheduler (ADR-0041) ─────────────────────────────────
    # Idle-draft cleanup loop; off in dev. The job is idempotent, shorter intervals are safe.
    background_jobs_enabled: bool = Field(default=False, alias="MDX_BACKGROUND_JOBS")
    # How long a transcript snapshot may outlive its run.
    generation_snapshot_hours: int = Field(
        default=24, ge=1, alias="MDX_NOTE_GENERATION_SNAPSHOT_HOURS"
    )
    # Shadow backend: runs beside the real one on a share of generations; its output is
    # counted and thrown away, never stored or shown. Empty: no shadow runs.
    note_generation_shadow_backend: str = Field(
        default="", alias="MDX_NOTE_GENERATION_SHADOW_BACKEND"
    )
    note_generation_shadow_percent: int = Field(
        default=5, ge=0, le=100, alias="MDX_NOTE_GENERATION_SHADOW_PERCENT"
    )
    background_jobs_interval_s: float = Field(
        default=86400.0, alias="MDX_BACKGROUND_JOBS_INTERVAL_S"
    )
    # Draft-idleness threshold (docs/runbooks/notes.md).
    idle_draft_days: int = Field(default=30, alias="MDX_IDLE_DRAFT_DAYS")
    # How long a capture may claim to be recording/uploading before the sweeper calls it no_audio.
    meeting_stale_hours: int = Field(default=12, alias="MDX_MEETING_STALE_HOURS")

    # ── Calendar connections ────────────────────────────────────────────
    # Empty client id = feature off: reads answer ``available: false``, connect answers 503.
    google_calendar_client_id: str = Field(default="", alias="GOOGLE_CALENDAR_CLIENT_ID")
    google_calendar_client_secret: SecretStrEnv = Field(
        default_factory=lambda: Secret(""), alias="GOOGLE_CALENDAR_CLIENT_SECRET"
    )
    # Must match the URI registered at Google exactly (scheme, host, port, path).
    google_calendar_redirect_uri: str = Field(
        default="http://localhost:8006/v1/calendar/google/callback",
        alias="GOOGLE_CALENDAR_REDIRECT_URI",
    )
    # HMAC key for the OAuth ``state`` (hex); dev default is NOT a secret. Rotating it
    # only invalidates mid-flight sign-ins.
    calendar_state_hmac_key_hex: str = Field(
        default="6d64782d6465762d63616c656e6461722d73746174652d6b65792d30303030",
        alias="MDX_CALENDAR_STATE_HMAC_KEY_HEX",
    )
    # Extra return_to URL prefixes beyond the CORS origins and ``notesai://``.
    calendar_return_to_extra: str = Field(default="", alias="MDX_CALENDAR_RETURN_TO_EXTRA")

    @property
    def calendar_return_to_prefixes(self) -> list[str]:
        extra = [p.strip() for p in self.calendar_return_to_extra.split(",") if p.strip()]
        return [*self.cors_origins_list, "notesai://", *extra]

    # ── Outbound mail (sharing a note by e-mail) ────────────────────────
    # `mock` captures in memory and refuses to run in production; `smtp` is real.
    # Same env name as auth-service so one switch flips both.
    email_provider: str = Field(default="mock", alias="MDX_EMAIL_PROVIDER")
    note_smtp_host: str = Field(default="localhost", alias="MDX_NOTE_SMTP_HOST")
    note_smtp_port: int = Field(default=1025, alias="MDX_NOTE_SMTP_PORT")
    note_smtp_use_tls: bool = Field(default=False, alias="MDX_NOTE_SMTP_USE_TLS")
    note_smtp_username: str = Field(default="", alias="MDX_NOTE_SMTP_USERNAME")
    # Google Workspace needs a 16-character App Password (else `535-5.7.8`).
    note_smtp_password: SecretStrEnv = Field(
        default_factory=lambda: Secret(""), alias="MDX_NOTE_SMTP_PASSWORD"
    )
    note_email_from: str = Field(default="notes@notes-ai.local", alias="MDX_NOTE_EMAIL_FROM")
    note_email_from_name: str = Field(default="Notes AI", alias="MDX_NOTE_EMAIL_FROM_NAME")
    # Fallback only: Reply-To is set per send to the sharer's address.
    note_email_reply_to: str = Field(
        default="notes@notes-ai.local", alias="MDX_NOTE_EMAIL_REPLY_TO"
    )
    # SPA origin the mailed links point at.
    app_base_url: str = Field(default="http://localhost:5173", alias="MDX_APP_BASE_URL")
    # A hung relay must not hold an HTTP worker until the client gives up.
    share_email_timeout_s: float = Field(default=15.0, alias="MDX_SHARE_EMAIL_TIMEOUT_S")
    # Per request, and per sender per hour (without the cap the endpoint is a spam relay).
    share_email_max_recipients: int = Field(default=10, alias="MDX_SHARE_EMAIL_MAX_RECIPIENTS")
    share_emails_per_user_per_hour: int = Field(
        default=60, alias="MDX_SHARE_EMAILS_PER_USER_PER_HOUR"
    )
    # How much of the sharer's own words the mail carries.
    share_email_max_message_chars: int = Field(
        default=1000, alias="MDX_SHARE_EMAIL_MAX_MESSAGE_CHARS"
    )

    # ── Session revocation check ────────────────────────────────────────
    # Rejects tokens on the Redis denylist auth-service pushes. Fail-OPEN on Redis outage.
    session_revocation_enabled: bool = Field(default=False, alias="MDX_SESSION_REVOCATION_ENABLED")

    @property
    def is_production(self) -> bool:
        # Staging counts, so it proves what production will do.
        return self.environment in {"production", "staging"}


settings = Settings()
