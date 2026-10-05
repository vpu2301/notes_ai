"""generation-service configuration.

Default backend is llama-server, not Ollama: Ollama's ~420 ms/request scheduler
overhead (ADR-0036) alone eats the p95 <= 400 ms inline budget.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "generation-service"
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
    # JSON list of trusted issuers `[{"issuer", "jwks_url", "audience"}]`; unset = the three above.
    auth_issuers_json: str = Field(default="", alias="AUTH_ISSUERS_JSON")
    auth_clock_skew_seconds: int = Field(default=30, alias="AUTH_CLOCK_SKEW_SECONDS")

    # CORS: explicit origins only (allow_credentials forbids "*").
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        alias="CORS_ALLOWED_ORIGINS",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    db_audit_writer_dsn: str = Field(
        default="postgresql://audit_writer:audit_writer@localhost:5432/notes",
        alias="DB_AUDIT_WRITER_DSN",
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Kill switch: off = always 204, no inference client built, pod stays ready.
    layer_c_enabled: bool = Field(default=True, alias="MDX_LAYER_C_ENABLED")
    # Comma-separated tenant UUIDs; empty = every tenant, others get a silent 204.
    tenant_allowlist: str = Field(default="", alias="MDX_GEN_TENANT_ALLOWLIST")

    @property
    def tenant_allowlist_set(self) -> frozenset[UUID]:
        return frozenset(UUID(t.strip()) for t in self.tenant_allowlist.split(",") if t.strip())

    # Inference backend (ADR-0036)
    gen_backend: Literal["llamacpp", "ollama"] = Field(default="llamacpp", alias="MDX_GEN_BACKEND")
    gen_base_url: str = Field(default="http://localhost:8089", alias="MDX_GEN_BASE_URL")
    # Used by the Ollama backend and echoed in responses; llama-server serves what it was launched with.
    gen_model: str = Field(default="gemma3:1b", alias="MDX_GEN_MODEL")
    gen_max_tokens: int = Field(default=24, alias="MDX_GEN_MAX_TOKENS")
    # Hard end-to-end budget (slot wait + inference); expiry answers 204.
    gen_timeout_ms: int = Field(default=600, alias="MDX_GEN_TIMEOUT_MS")
    # Dedicated inline concurrency slots so long synthesis can never starve typing.
    gen_slots: int = Field(default=2, alias="MDX_GEN_SLOTS")

    # Rate limit: dual fixed windows, burst of 10, sustained ~3 req/s.
    rate_burst_per_second: int = Field(default=10, alias="MDX_GEN_RATE_BURST_PER_S")
    rate_per_10s: int = Field(default=30, alias="MDX_GEN_RATE_PER_10S")

    # Aggregated layer_c.completion.shown audit flush interval.
    shown_audit_flush_s: float = Field(default=600.0, alias="MDX_GEN_SHOWN_AUDIT_FLUSH_S")

    # Pre-warm: fire a 1-token completion at startup; /readyz is 503 until it lands.
    prewarm_enabled: bool = Field(default=False, alias="MDX_PREWARM_ENABLED")
    prewarm_retry_seconds: float = Field(default=5.0, alias="MDX_PREWARM_RETRY_SECONDS")

    # Redis session denylist check; fail-OPEN on Redis outage (ADR-0040).
    session_revocation_enabled: bool = Field(default=False, alias="MDX_SESSION_REVOCATION_ENABLED")


settings = Settings()
