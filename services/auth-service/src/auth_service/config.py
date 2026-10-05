"""Auth-service configuration. All env vars are read here (no ``os.environ`` elsewhere)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from secret import Secret

# pydantic-settings json.loads() generic types; NoDecode hands the raw string to Secret.
SecretStrEnv = Annotated[Secret[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "auth-service"
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
    # JSON list of trusted issuers `[{"issuer", "jwks_url", "audience"}]`; the token's
    # `iss` selects the entry. Unset = one-element list from the three values above.
    auth_issuers_json: str = Field(default="", alias="AUTH_ISSUERS_JSON")
    auth_clock_skew_seconds: int = Field(default=30, alias="AUTH_CLOCK_SKEW_SECONDS")

    # ── Native issuer (ADR-0047) ────────────────────────────────────────
    # keycloak: Keycloak mints tokens. native: auth-service mints RS256 tokens,
    # serves JWKS, owns sessions in Postgres. dual: both (migration state).
    idp_mode: Literal["keycloak", "dual", "native"] = Field(
        default="keycloak", alias="MDX_IDP_MODE"
    )
    # `iss` of every native token; other services' AUTH_ISSUER at cut-over.
    auth_issuer_url: str = Field(default="http://localhost:8000", alias="AUTH_ISSUER_URL")
    auth_access_ttl_seconds: int = Field(default=900, alias="AUTH_ACCESS_TTL_SECONDS")
    # Refresh idle window (30 days).
    auth_refresh_ttl_seconds: int = Field(default=2592000, alias="AUTH_REFRESH_TTL_SECONDS")
    # Ceiling the sliding idle window never passes, from session start (90 days).
    auth_session_absolute_ttl_seconds: int = Field(
        default=7776000, alias="AUTH_SESSION_ABSOLUTE_TTL_SECONDS"
    )
    # Retired refresh token stays valid this long: inside = retry, outside = replay
    # (session revoked).
    auth_refresh_grace_seconds: int = Field(default=30, alias="AUTH_REFRESH_GRACE_SECONDS")
    # Step-up window: how long a proof of identity counts as recent.
    auth_reauth_window_seconds: int = Field(default=300, alias="AUTH_REAUTH_WINDOW_SECONDS")
    # Tenant for audit events with no customer (e.g. OTP for an unknown address).
    auth_platform_tenant_id: str = Field(
        default="00000000-0000-0000-0000-0000000000f1", alias="AUTH_PLATFORM_TENANT_ID"
    )
    # JSON list of {kid, private_pem, not_after}; see scripts/ops/gen-signing-key.py.
    auth_signing_keys_json: SecretStrEnv = Field(
        default_factory=lambda: Secret(""), alias="AUTH_SIGNING_KEYS_JSON"
    )
    # Dev-only path to the same JSON; refused in production.
    auth_signing_keys_file: str = Field(default="", alias="AUTH_SIGNING_KEYS_FILE")

    # ── Email one-time codes ────────────────────────────────────────────
    otp_ttl_seconds: int = Field(default=600, alias="AUTH_OTP_TTL_SECONDS")
    otp_max_attempts: int = Field(default=5, alias="AUTH_OTP_MAX_ATTEMPTS")
    otp_resend_seconds: int = Field(default=60, alias="AUTH_OTP_RESEND_SECONDS")
    # Rate limits: start_* fail CLOSED (no open mail relay on a down Redis);
    # verify_ip fails open (the DB attempt counter still bounds it).
    otp_start_email_limit: int = Field(default=5, alias="AUTH_OTP_START_EMAIL_LIMIT")
    otp_start_email_window_seconds: int = Field(
        default=900, alias="AUTH_OTP_START_EMAIL_WINDOW_SECONDS"
    )
    otp_start_ip_limit: int = Field(default=20, alias="AUTH_OTP_START_IP_LIMIT")
    otp_start_ip_window_seconds: int = Field(default=3600, alias="AUTH_OTP_START_IP_WINDOW_SECONDS")
    otp_verify_ip_limit: int = Field(default=60, alias="AUTH_OTP_VERIFY_IP_LIMIT")
    otp_verify_ip_window_seconds: int = Field(
        default=900, alias="AUTH_OTP_VERIFY_IP_WINDOW_SECONDS"
    )
    email_send_timeout_seconds: float = Field(default=5.0, alias="AUTH_EMAIL_SEND_TIMEOUT_SECONDS")

    # ── Self-serve signup ───────────────────────────────────────────────
    # Off by default: it creates Keycloak users and mails unverified addresses.
    signup_enabled: bool = Field(default=False, alias="MDX_SIGNUP_ENABLED")
    signup_ttl_seconds: int = Field(default=600, alias="AUTH_SIGNUP_TTL_SECONDS")
    signup_max_attempts: int = Field(default=5, alias="AUTH_SIGNUP_MAX_ATTEMPTS")
    signup_resend_seconds: int = Field(default=60, alias="AUTH_SIGNUP_RESEND_SECONDS")
    # Mirrors the realm password policy (field-level reason instead of a realm error).
    signup_min_password_length: int = Field(default=12, alias="AUTH_SIGNUP_MIN_PASSWORD_LENGTH")
    # Recorded on every self-serve tenant as `plan_limits`; NOT enforced.
    signup_free_limits: str = Field(
        default='{"notes_per_month": 50, "members": 3}', alias="MDX_SIGNUP_FREE_LIMITS"
    )
    # Optional extra throwaway-domain list (one per line) on top of the bundled floor.
    disposable_domains_file: str = Field(default="", alias="MDX_DISPOSABLE_DOMAINS_FILE")
    # `/auth/signup` never answers faster than this (uniform 202 needs uniform timing).
    signup_min_response_ms: int = Field(default=300, alias="AUTH_SIGNUP_MIN_RESPONSE_MS")
    # Rate limits; the two `start` scopes fail CLOSED (no open mail relay).
    signup_ip_limit: int = Field(default=5, alias="AUTH_SIGNUP_IP_LIMIT")
    signup_ip_window_seconds: int = Field(default=3600, alias="AUTH_SIGNUP_IP_WINDOW_SECONDS")
    signup_email_limit: int = Field(default=3, alias="AUTH_SIGNUP_EMAIL_LIMIT")
    signup_email_window_seconds: int = Field(
        default=86400, alias="AUTH_SIGNUP_EMAIL_WINDOW_SECONDS"
    )
    signup_verify_email_limit: int = Field(default=10, alias="AUTH_SIGNUP_VERIFY_EMAIL_LIMIT")
    signup_verify_email_window_seconds: int = Field(
        default=3600, alias="AUTH_SIGNUP_VERIFY_EMAIL_WINDOW_SECONDS"
    )
    signup_resend_email_limit: int = Field(default=3, alias="AUTH_SIGNUP_RESEND_EMAIL_LIMIT")
    signup_resend_email_window_seconds: int = Field(
        default=3600, alias="AUTH_SIGNUP_RESEND_EMAIL_WINDOW_SECONDS"
    )
    # Unverified accounts older than this are removed by the cleanup job.
    signup_stale_after_days: int = Field(default=30, alias="AUTH_SIGNUP_STALE_AFTER_DAYS")
    # Lockout (DB-backed): failures before a lock, first lock length, doubling cap.
    lockout_threshold: int = Field(default=10, alias="AUTH_LOCKOUT_THRESHOLD")
    lockout_base_seconds: int = Field(default=900, alias="AUTH_LOCKOUT_BASE_SECONDS")
    lockout_max_seconds: int = Field(default=3600, alias="AUTH_LOCKOUT_MAX_SECONDS")
    # Proxies whose X-Forwarded-For we believe (CIDRs). Empty = TCP peer is the client.
    trusted_proxy_cidrs: str = Field(default="", alias="TRUSTED_PROXY_CIDRS")

    @property
    def native_issuer_enabled(self) -> bool:
        """Does this deployment sign its own tokens? (`dual` or `native`; gate on this, never `== "native"`)."""
        return self.idp_mode in ("dual", "native")

    @property
    def keycloak_enabled(self) -> bool:
        """Does Keycloak still mint tokens here? (`keycloak` or `dual`)"""
        return self.idp_mode in ("keycloak", "dual")

    def signing_keys_json(self) -> str:
        """The raw key list text, from the env value or (dev only) the file."""
        inline = self.auth_signing_keys_json.value()
        if inline:
            return inline
        if self.auth_signing_keys_file:
            if self.environment == "production":
                raise ValueError("AUTH_SIGNING_KEYS_FILE is a dev-only escape hatch")
            with open(self.auth_signing_keys_file, encoding="utf-8") as fh:
                return fh.read()
        return ""

    # ── Database DSNs (RLS depends on the right role — never mix them) ──
    db_app_role_dsn: str = Field(
        default="postgresql://app_role:app_role@localhost:5432/notes",
        alias="DB_APP_ROLE_DSN",
    )
    db_tenant_writer_dsn: str = Field(
        default="postgresql://tenant_writer:tenant_writer@localhost:5432/notes",
        alias="DB_TENANT_WRITER_DSN",
    )
    db_audit_writer_dsn: str = Field(
        default="postgresql://audit_writer:audit_writer@localhost:5432/notes",
        alias="DB_AUDIT_WRITER_DSN",
    )
    db_audit_reader_dsn: str = Field(
        default="postgresql://audit_reader:audit_reader@localhost:5432/notes",
        alias="DB_AUDIT_READER_DSN",
    )

    db_pool_min_size: int = Field(default=1, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=10, alias="DB_POOL_MAX_SIZE")

    # ── Keycloak (server-side login proxy + admin API) ──────────────────
    keycloak_base_url: str = Field(default="http://localhost:8088", alias="KEYCLOAK_BASE_URL")
    keycloak_realm: str = Field(default="notes", alias="KEYCLOAK_REALM")
    keycloak_login_client_id: str = Field(default="mdx-backend", alias="KEYCLOAK_LOGIN_CLIENT_ID")
    keycloak_login_client_secret: str = Field(
        default="dev-secret-change-in-prod-mdx-backend",
        alias="KEYCLOAK_LOGIN_CLIENT_SECRET",
    )
    keycloak_admin_client_id: str = Field(default="mdx-admin", alias="KEYCLOAK_ADMIN_CLIENT_ID")
    keycloak_admin_client_secret: str = Field(
        default="dev-secret-change-in-prod-mdx-admin",
        alias="KEYCLOAK_ADMIN_CLIENT_SECRET",
    )

    # ── Refresh cookie ──────────────────────────────────────────────────
    auth_cookie_name: str = Field(default="mdx_rt", alias="AUTH_COOKIE_NAME")
    auth_cookie_path: str = Field(default="/auth", alias="AUTH_COOKIE_PATH")
    # Browsers refuse Secure cookies on http://localhost; staging/prod must override.
    auth_cookie_secure: bool = Field(default=False, alias="AUTH_COOKIE_SECURE")
    # Dev SPA and auth-service are same-site but cross-origin, so `lax` works;
    # cross-site prod deployments must set `none` + Secure.
    auth_cookie_samesite: str = Field(default="lax", alias="AUTH_COOKIE_SAMESITE")

    # ── CORS ────────────────────────────────────────────────────────────
    # Explicit origins only — allow_credentials=true forbids "*".
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        alias="CORS_ALLOWED_ORIGINS",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    # ── MFA enforcement ─────────────────────────────────────────────────
    # requires_mfa() rejects tokens without `mfa: true`: unenrolled → 403
    # `mfa_enrolment_required`, enrolled with a pre-enrolment token → 401.
    require_mfa: bool = Field(default=False, alias="MDX_REQUIRE_MFA")
    # Separate switch so enrolment can roll out before MDX_REQUIRE_MFA;
    # needs the envelope wiring below (TOTP secret is envelope-encrypted).
    mfa_enrolment_enabled: bool = Field(default=False, alias="MDX_MFA_ENROLMENT_ENABLED")
    mfa_totp_issuer: str = Field(default="Notes AI", alias="MDX_MFA_TOTP_ISSUER")

    # Envelope wiring for the TOTP secret store (lazy-built on first MFA call).
    db_crypto_writer_dsn: str = Field(
        default="postgresql://crypto_writer:crypto_writer@localhost:5432/notes",
        alias="DB_CRYPTO_WRITER_DSN",
    )
    master_key_path: str = Field(default="/etc/mdx/master.key", alias="MDX_MASTER_KEY_PATH")

    # ── Master-key provider (ADR-0011) ──────────────────────────────────
    master_key_provider: str = Field(default="file", alias="MDX_MASTER_KEY_PROVIDER")
    vault_addr: str = Field(default="http://localhost:8200", alias="MDX_VAULT_ADDR")
    vault_token: SecretStrEnv = Field(default_factory=lambda: Secret(""), alias="MDX_VAULT_TOKEN")
    vault_transit_key: str = Field(default="mdx-master", alias="MDX_VAULT_TRANSIT_KEY")
    vault_transit_mount: str = Field(default="transit", alias="MDX_VAULT_TRANSIT_MOUNT")

    # ── Session revocation (ADR-0040) ───────────────────────────────────
    # Logout / refresh replay / deactivation push `sid` (or `sub`) onto a Redis
    # denylist checked by current_user fleet-wide. Fails OPEN on Redis outage.
    session_revocation_enabled: bool = Field(default=False, alias="MDX_SESSION_REVOCATION_ENABLED")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    # TTL for sub-level denies: must cover the access-token lifetime with margin.
    revoked_sub_ttl_seconds: int = Field(
        default=1200,
        validation_alias=AliasChoices(
            "MDX_REVOKED_SUB_TTL_SECONDS", "AUTH_REVOKED_SUB_TTL_SECONDS"
        ),
    )

    # ── Notification bus (ADR-0029) ─────────────────────────────────────
    # Off ⇒ the MFA reminder is still recorded and shown as a banner; only
    # the bell/email half goes quiet.
    notifications_enabled: bool = Field(default=True, alias="MDX_NOTIFICATIONS_ENABLED")

    # ── demo mode: DemoRateLimitMiddleware caps on session endpoints ────
    demo_mode: bool = Field(default=False, alias="MDX_DEMO_MODE")

    # ── Password recovery ───────────────────────────────────────────────
    # Off by default: it mints credentials over email.
    password_reset_enabled: bool = Field(default=False, alias="MDX_PASSWORD_RESET_ENABLED")
    # 30 minutes (OWASP range 15–60).
    password_reset_ttl_seconds: int = Field(default=1800, alias="MDX_PASSWORD_RESET_TTL_SECONDS")
    # Lockdown link (in the "password changed" mail) lives 7 days: the account
    # holder may read it long after the change.
    lockdown_token_ttl_seconds: int = Field(default=604800, alias="MDX_LOCKDOWN_TOKEN_TTL_SECONDS")
    # NIST SP 800-63B: length matters, composition rules do not.
    password_min_length: int = Field(default=12, alias="MDX_PASSWORD_MIN_LENGTH")

    # Abuse caps for the unauthenticated request endpoint; both fail OPEN on a
    # Redis outage (recovery must not depend on a cache).
    password_reset_ip_per_hour: int = Field(default=20, alias="MDX_PASSWORD_RESET_IP_PER_HOUR")
    password_reset_email_per_hour: int = Field(default=5, alias="MDX_PASSWORD_RESET_EMAIL_PER_HOUR")
    # Salt for stored IP hashes. MUST be set per deployment (unsalted IP hashes
    # are brute-forceable).
    password_reset_ip_hash_salt: SecretStrEnv = Field(
        default_factory=lambda: Secret("dev-ip-hash-salt-change-in-prod"),
        alias="MDX_PASSWORD_RESET_IP_HASH_SALT",
    )

    # ── Outbound mail (password recovery) ───────────────────────────────
    # `mock` captures in memory and refuses to run in production.
    email_provider: str = Field(default="mock", alias="MDX_EMAIL_PROVIDER")
    auth_smtp_host: str = Field(default="localhost", alias="MDX_AUTH_SMTP_HOST")
    auth_smtp_port: int = Field(default=1025, alias="MDX_AUTH_SMTP_PORT")
    auth_smtp_use_tls: bool = Field(default=False, alias="MDX_AUTH_SMTP_USE_TLS")
    auth_smtp_username: str = Field(default="", alias="MDX_AUTH_SMTP_USERNAME")
    # Google Workspace needs an App Password here (symptom otherwise: 535-5.7.8).
    auth_smtp_password: SecretStrEnv = Field(
        default_factory=lambda: Secret(""), alias="MDX_AUTH_SMTP_PASSWORD"
    )
    auth_email_from: str = Field(default="sales@notes-ai.local", alias="MDX_AUTH_EMAIL_FROM")
    auth_email_from_name: str = Field(default="Notes AI", alias="MDX_AUTH_EMAIL_FROM_NAME")
    auth_email_reply_to: str = Field(
        default="sales@notes-ai.local", alias="MDX_AUTH_EMAIL_REPLY_TO"
    )
    # SPA origin the mailed links point at.
    app_base_url: str = Field(default="http://localhost:5173", alias="MDX_APP_BASE_URL")
    support_url: str = Field(default="https://notes-ai.local/contact", alias="MDX_SUPPORT_URL")

    # ── Outbox delivery worker ──────────────────────────────────────────
    background_jobs_enabled: bool = Field(default=True, alias="MDX_BACKGROUND_JOBS")
    mail_delivery_interval_s: float = Field(default=5.0, alias="MDX_AUTH_MAIL_DELIVERY_INTERVAL_S")
    mail_delivery_batch_size: int = Field(default=25, alias="MDX_AUTH_MAIL_DELIVERY_BATCH")
    mail_delivery_max_attempts: int = Field(default=5, alias="MDX_AUTH_MAIL_DELIVERY_MAX_ATTEMPTS")
    mail_delivery_backoff_base_s: float = Field(
        default=60.0, alias="MDX_AUTH_MAIL_DELIVERY_BACKOFF_BASE_S"
    )

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "staging"}


settings = Settings()
