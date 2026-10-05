"""autocomplete-service configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from secret import Secret

# pydantic-settings json.loads() generic types like ``Secret[str]``; NoDecode passes the raw string through.
# Every env-fed Secret field must use this alias.
SecretStrEnv = Annotated[Secret[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "autocomplete-service"
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
    # ADR-0047: JSON list of `{issuer, jwks_url, audience}`; unset = one-element list from the trio above.
    auth_issuers_json: str = Field(default="", alias="AUTH_ISSUERS_JSON")
    auth_clock_skew_seconds: int = Field(default=30, alias="AUTH_CLOCK_SKEW_SECONDS")

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
    db_pool_min_size: int = Field(default=2, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=16, alias="DB_POOL_MAX_SIZE")
    db_statement_cache_size: int = Field(default=0, alias="DB_STATEMENT_CACHE_SIZE")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    trie_cache_ttl_seconds: int = Field(default=3600, alias="MDX_TRIE_CACHE_TTL")

    suggest_default_limit: int = Field(default=3, alias="MDX_SUGGEST_DEFAULT_LIMIT")
    suggest_max_limit: int = Field(default=10, alias="MDX_SUGGEST_MAX_LIMIT")

    phrase_max_creates_per_hour: int = Field(default=100, alias="MDX_PHRASE_MAX_PER_HOUR")

    telemetry_flush_interval_s: float = Field(default=5.0, alias="MDX_TELEMETRY_FLUSH_S")
    telemetry_flush_batch: int = Field(default=100, alias="MDX_TELEMETRY_FLUSH_BATCH")

    # In-process maintenance loops; disable when an external scheduler owns them.
    background_jobs_enabled: bool = Field(default=True, alias="MDX_BACKGROUND_JOBS")
    background_jobs_interval_s: float = Field(
        default=86400.0, alias="MDX_BACKGROUND_JOBS_INTERVAL_S"
    )

    # Archive expired telemetry partitions to encrypted object storage before dropping; archive failure blocks the drop.
    telemetry_cold_archive_enabled: bool = Field(
        default=False, alias="MDX_TELEMETRY_COLD_ARCHIVE_ENABLED"
    )
    s3_endpoint: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key: str = Field(default="minioadmin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", alias="S3_SECRET_KEY")
    s3_use_ssl: bool = Field(default=False, alias="S3_USE_SSL")
    s3_telemetry_archive_bucket: str = Field(
        default="mdx-telemetry-archive", alias="S3_TELEMETRY_ARCHIVE_BUCKET"
    )
    # Envelope wiring (archives are encrypted at rest).
    db_crypto_writer_dsn: str = Field(
        default="postgresql://crypto_writer:crypto_writer@localhost:5432/notes",
        alias="DB_CRYPTO_WRITER_DSN",
    )
    master_key_path: str = Field(default="/etc/mdx/master.key", alias="MDX_MASTER_KEY_PATH")
    master_key_provider: str = Field(default="file", alias="MDX_MASTER_KEY_PROVIDER")
    vault_addr: str = Field(default="http://localhost:8200", alias="MDX_VAULT_ADDR")
    vault_token: SecretStrEnv = Field(default_factory=lambda: Secret(""), alias="MDX_VAULT_TOKEN")
    vault_transit_key: str = Field(default="mdx-master", alias="MDX_VAULT_TRANSIT_KEY")
    vault_transit_mount: str = Field(default="transit", alias="MDX_VAULT_TRANSIT_MOUNT")

    # Redis denylist check in current_user; fail-OPEN on Redis outage (ADR-0040).
    session_revocation_enabled: bool = Field(default=False, alias="MDX_SESSION_REVOCATION_ENABLED")


settings = Settings()
