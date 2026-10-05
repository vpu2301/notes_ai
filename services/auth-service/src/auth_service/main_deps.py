"""Service-wide singletons (JWKS cache, DB pools, audit), built in the lifespan."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
import httpx

from audit import AuditVerifier, AuditWriter, Severity
from auth import (
    IssuerConfig,
    JwksCache,
    RedisSessionDenylist,
    build_session_denylist,
    issuer_url_map,
    issuers_from_env,
)
from crypto import Envelope, TenantKekRepository, build_master_key_provider
from db import create_pool
from ratelimit import FixedWindowLimiter

from .adapters.client_lock import RedisClientLock
from .adapters.email import EmailProvider, build_provider
from .audit_kinds import AUTH_ACCOUNT_LOCKED
from .config import settings
from .domain.account_service import AccountService
from .domain.credential_repository import CredentialRepository
from .domain.credential_service import (
    LOCK_SECONDS,
    LOCK_THRESHOLD,
    LOCK_WINDOW_SECONDS,
    CredentialService,
)
from .domain.email_code import LockoutPolicy
from .domain.email_code_service import (
    CodeMailer,
    EmailCodeConfig,
    EmailCodeService,
)
from .domain.identity_repository import (
    RecoveryCodeRepository,
    TotpRepository,
    build_repositories,
)
from .domain.identity_secrets import EnvelopeSecretBox
from .domain.mfa_service import MfaService
from .domain.security_mail import SecurityMailer
from .domain.session_service import SessionService
from .domain.signing_keys import KeySet, SigningKeyError
from .domain.token_service import TokenService
from .jwks_metrics import instrument_jwks_cache
from .keycloak_client import KeycloakClient
from .rate_limit import PasswordResetRateLimiter

logger = logging.getLogger(__name__)


@dataclass
class ServiceState:
    """Container for runtime singletons. Stored on ``app.state.svc``."""

    jwks_cache: JwksCache
    app_pool: asyncpg.Pool
    tenant_writer_pool: asyncpg.Pool
    audit_writer_pool: asyncpg.Pool
    audit_reader_pool: asyncpg.Pool
    audit_writer: AuditWriter
    audit_verifier: AuditVerifier
    keycloak: KeycloakClient
    # Session-revocation denylist (None = feature off).
    denylist: RedisSessionDenylist | None = None
    # Native issuer; both None in `keycloak` mode.
    signing_keys: KeySet | None = None
    token_service: TokenService | None = None
    # ── Password recovery (None = feature off) ──────────────────────────
    email_provider: EmailProvider | None = None
    password_rate_limiter: PasswordResetRateLimiter | None = None
    # Email one-time codes; None in keycloak mode or without a mail provider (routes 404).
    email_code_service: EmailCodeService | None = None
    # Second factors and the account surface; same posture.
    account_services: AccountServices | None = None
    # Rotation/revocation for `/auth/refresh` and `/auth/logout`; needs no mail provider.
    session_service: SessionService | None = None
    # Self-serve signup; None unless MDX_SIGNUP_ENABLED and a mail provider are set.
    onboarding_service: Any = None
    _redis: Any = None

    @property
    def notification_bus(self) -> Any:
        """Redis client the notification producer publishes on; None = don't publish."""
        return self._redis if settings.notifications_enabled else None

    # Lazy envelope wiring: built on first use so MFA-less deployments need no master key.
    crypto_pool: asyncpg.Pool | None = None
    envelope: Envelope | None = None
    _envelope_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_envelope(self) -> Envelope:
        """Build (once) and return the envelope for TOTP-secret crypto; raises MasterKeyError (callers → 503)."""
        async with self._envelope_lock:
            if self.envelope is not None:
                return self.envelope
            master = build_master_key_provider(
                provider=settings.master_key_provider,
                file_path=settings.master_key_path,
                vault_addr=settings.vault_addr,
                vault_token=settings.vault_token,
                vault_transit_key=settings.vault_transit_key,
                vault_transit_mount=settings.vault_transit_mount,
            )
            await master.startup_self_check()
            self.crypto_pool = await create_pool(
                settings.db_crypto_writer_dsn,
                application_name=f"{settings.service_name}/crypto_writer",
                min_size=1,
                max_size=2,
            )
            kek_repo = TenantKekRepository(pool=self.crypto_pool, master_key_provider=master)
            self.envelope = Envelope(master_key_provider=master, kek_repository=kek_repo)
            return self.envelope


def build_issuer() -> tuple[KeySet | None, TokenService | None]:
    """Native issuer key set + minter, or (None, None) in keycloak mode; missing keys fail startup."""
    if not settings.native_issuer_enabled:
        return None, None
    raw = settings.signing_keys_json()
    if not raw:
        raise SigningKeyError(
            f"MDX_IDP_MODE={settings.idp_mode} needs AUTH_SIGNING_KEYS_JSON "
            "(or, in dev, AUTH_SIGNING_KEYS_FILE)"
        )
    keys = KeySet.from_json(raw)
    active = keys.active()
    logger.info(
        "auth.issuer.ready",
        extra={"issuer": settings.auth_issuer_url, "active_kid": active.kid, "kids": keys.kids},
    )
    return keys, TokenService(
        keys=keys,
        issuer=settings.auth_issuer_url,
        audience=settings.auth_audience,
        access_ttl_seconds=settings.auth_access_ttl_seconds,
    )


def native_issuer_config() -> IssuerConfig:
    """This service's own issuer entry — the one it signs with."""
    issuer = settings.auth_issuer_url.rstrip("/")
    return IssuerConfig(
        issuer=issuer,
        jwks_url=f"{issuer}/.well-known/jwks.json",
        audience=settings.auth_audience,
    )


def auth_issuers() -> list[IssuerConfig]:
    """Issuers this service trusts, by mode: keycloak = configured list, dual = list + own, native = own only."""
    configured = issuers_from_env(
        settings.auth_issuers_json,
        issuer=settings.auth_issuer,
        jwks_url=settings.auth_jwks_url,
        audience=settings.auth_audience,
    )
    native = native_issuer_config()
    if settings.idp_mode == "native":
        return [native]
    if settings.idp_mode == "keycloak":
        return configured
    # dual: append the native entry unless the fleet-wide config already names it.
    if any(entry.issuer == native.issuer for entry in configured):
        return configured
    return [*configured, native]


def build_jwks_cache(signing_keys: KeySet | None) -> JwksCache:
    """JWKS cache for ``current_user``; our own JWKS URL is served from memory (no self-call), others over HTTP."""
    issuers = auth_issuers()
    urls = issuer_url_map(issuers)

    if signing_keys is None:
        return JwksCache(issuer_to_url=urls)

    # Match the JWKS URL the configured issuer entry names, not the one derived from
    # AUTH_ISSUER_URL (they differ with an in-cluster JWKS address).
    native = native_issuer_config()
    self_jwks_url = urls.get(native.issuer, native.jwks_url)

    def _serve(request: httpx.Request) -> httpx.Response:
        # Read the live key set on every call so rotation needs no restart.
        return httpx.Response(
            200, json=signing_keys.jwks(access_ttl_seconds=settings.auth_access_ttl_seconds)
        )

    transport: httpx.AsyncBaseTransport = httpx.MockTransport(_serve)
    if len(urls) > 1:
        transport = _SelfServingTransport(self_jwks_url, _serve)

    return JwksCache(
        issuer_to_url=urls,
        http_client=httpx.AsyncClient(transport=transport),
    )


class _SelfServingTransport(httpx.AsyncBaseTransport):
    """Answer our own JWKS URL from memory; send everything else to the network (dual only)."""

    def __init__(self, self_url: str, serve: Callable[[httpx.Request], httpx.Response]) -> None:
        self._self_url = self_url
        self._serve = serve
        self._network = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == self._self_url:
            return self._serve(request)
        return await self._network.handle_async_request(request)

    async def aclose(self) -> None:
        await self._network.aclose()


@dataclass
class AccountServices:
    """Bundle the native account routers resolve through one attribute (all or nothing)."""

    identities: Any
    challenges: Any
    sessions: Any
    mfa: MfaService
    account: AccountService
    # None without Redis: the client-credentials lock fails closed.
    credentials: CredentialService | None
    platform_tenant_id: str


def build_account_services(
    state: ServiceState,
    *,
    token_service: TokenService | None,
    redis_client: Any = None,
) -> AccountServices | None:
    """Wire the native account surface, or return None so its routes 404 (TOTP envelope is lazy)."""
    # `dual` gets these too (PATCH /auth/me); it does NOT get the native MFA router.
    if not settings.native_issuer_enabled or token_service is None:
        return None
    if state.email_provider is None:
        logger.error("auth.account.disabled_no_mail_provider")
        return None

    identities, challenges, sessions_repo = build_repositories(state.tenant_writer_pool)
    totp_store = TotpRepository(state.tenant_writer_pool)
    recovery = RecoveryCodeRepository(state.tenant_writer_pool)
    session_service = SessionService(
        tokens=token_service,
        sessions=sessions_repo,
        refresh_ttl_seconds=settings.auth_refresh_ttl_seconds,
    )
    mailer = SecurityMailer(
        state.email_provider,
        reply_to=settings.auth_email_reply_to,
        timeout_seconds=settings.email_send_timeout_seconds,
        # The revert link lands on THIS service, not the SPA (one-shot credential).
        public_base_url=settings.auth_issuer_url,
    )
    lockout = LockoutPolicy(
        threshold=settings.lockout_threshold,
        base_seconds=settings.lockout_base_seconds,
        max_seconds=settings.lockout_max_seconds,
    )
    mfa_service = MfaService(
        identities=identities,
        totp_store=totp_store,
        recovery=recovery,
        challenges=challenges,
        sessions=session_service,
        session_rows=sessions_repo,
        secrets_box=EnvelopeSecretBox(
            envelope_provider=state.get_envelope,
            kek_tenant_id=UUID(settings.auth_platform_tenant_id),
        ),
        notifier=mailer,
        issuer_label=settings.mfa_totp_issuer,
        lockout=lockout,
    )
    account = AccountService(
        identities=identities,
        sessions=sessions_repo,
        challenges=challenges,
        notifier=mailer,
        code_sender=CodeMailer(
            state.email_provider,
            reply_to=settings.auth_email_reply_to,
            timeout_seconds=settings.email_send_timeout_seconds,
        ),
        denylist=state.denylist,
        revoked_ttl_seconds=settings.revoked_sub_ttl_seconds,
        reauth_window_seconds=settings.auth_reauth_window_seconds,
        mfa_service=mfa_service,
    )
    # Only with Redis: the guessing lock fails closed, so every grant would 503.
    credentials: CredentialService | None = None
    if redis_client is not None:
        credentials = CredentialService(
            repo=CredentialRepository(state.tenant_writer_pool),
            tokens=token_service,
            limiter=FixedWindowLimiter(redis_client, prefix="mdx:auth:rl"),
            lock=RedisClientLock(
                redis_client,
                threshold=LOCK_THRESHOLD,
                window_seconds=LOCK_WINDOW_SECONDS,
                lock_seconds=LOCK_SECONDS,
            ),
            denylist=state.denylist,
            platform_tenant_id=UUID(settings.auth_platform_tenant_id),
            revoked_ttl_seconds=settings.revoked_sub_ttl_seconds,
        )
    else:
        logger.error("auth.credentials.disabled_no_redis")

    return AccountServices(
        identities=identities,
        challenges=challenges,
        sessions=sessions_repo,
        mfa=mfa_service,
        account=account,
        credentials=credentials,
        platform_tenant_id=settings.auth_platform_tenant_id,
    )


async def build_state() -> ServiceState:
    """Construct every async resource the service needs."""
    # Before the pools: a missing key is a startup failure, not a 503 later.
    signing_keys, token_service = build_issuer()
    jwks_cache = build_jwks_cache(signing_keys)
    instrument_jwks_cache(jwks_cache)

    app_pool = await create_pool(
        settings.db_app_role_dsn,
        application_name=f"{settings.service_name}/app",
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    tenant_writer_pool = await create_pool(
        settings.db_tenant_writer_dsn,
        application_name=f"{settings.service_name}/tenant_writer",
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    audit_writer_pool = await create_pool(
        settings.db_audit_writer_dsn,
        application_name=f"{settings.service_name}/audit_writer",
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    audit_reader_pool = await create_pool(
        settings.db_audit_reader_dsn,
        application_name=f"{settings.service_name}/audit_reader",
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )

    keycloak = KeycloakClient(
        base_url=settings.keycloak_base_url,
        realm=settings.keycloak_realm,
        login_client_id=settings.keycloak_login_client_id,
        login_client_secret=settings.keycloak_login_client_secret,
        admin_client_id=settings.keycloak_admin_client_id,
        admin_client_secret=settings.keycloak_admin_client_secret,
    )

    # ── Password recovery (built only when on) ───────────────────────
    email_provider: EmailProvider | None = None
    password_rate_limiter: PasswordResetRateLimiter | None = None

    # One Redis client shared by the rate limiters, the notification publisher
    # and the OTP limiter (the revocation denylist keeps its own, via libs/auth).
    native_email_code = settings.native_issuer_enabled
    signup = settings.signup_enabled and settings.idp_mode != "native"
    redis_client: Any = None
    if (
        settings.password_reset_enabled
        or settings.notifications_enabled
        or native_email_code
        or signup
    ):
        try:
            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
        except Exception:  # noqa: BLE001 — both users are fail-open
            logging.getLogger(__name__).warning("auth.redis_unavailable_fail_open")

    # The mail IS the proof of the address.
    if settings.password_reset_enabled or native_email_code or signup:
        email_provider = build_provider(
            kind=settings.email_provider,
            is_production=settings.is_production,
            host=settings.auth_smtp_host,
            port=settings.auth_smtp_port,
            from_address=settings.auth_email_from,
            from_name=settings.auth_email_from_name,
            use_tls=settings.auth_smtp_use_tls,
            username=settings.auth_smtp_username,
            password=settings.auth_smtp_password.value(),
        )

    if settings.password_reset_enabled:
        try:
            if redis_client is None:
                raise RuntimeError("no redis client")
            password_rate_limiter = PasswordResetRateLimiter(
                redis_client,
                ip_per_hour=settings.password_reset_ip_per_hour,
                email_per_hour=settings.password_reset_email_per_hour,
                email_salt=settings.password_reset_ip_hash_salt.value(),
            )
        except Exception:  # noqa: BLE001
            # Fail-open limiter: construction failure must not stop startup.
            logging.getLogger(__name__).warning("auth.password.rate_limiter_unavailable_fail_open")

    state = ServiceState(
        jwks_cache=jwks_cache,
        app_pool=app_pool,
        tenant_writer_pool=tenant_writer_pool,
        audit_writer_pool=audit_writer_pool,
        audit_reader_pool=audit_reader_pool,
        audit_writer=AuditWriter(audit_writer_pool),
        audit_verifier=AuditVerifier(audit_reader_pool),
        keycloak=keycloak,
        signing_keys=signing_keys,
        token_service=token_service,
        denylist=build_session_denylist(
            enabled=settings.session_revocation_enabled,
            redis_url=settings.redis_url,
        ),
        email_provider=email_provider,
        password_rate_limiter=password_rate_limiter,
        _redis=redis_client,
    )
    state.session_service = build_session_service(state, token_service=token_service)
    state.account_services = build_account_services(
        state, token_service=token_service, redis_client=redis_client
    )
    state.email_code_service = build_email_code_service(
        state,
        token_service=token_service,
        redis_client=redis_client,
        mfa=state.account_services.mfa if state.account_services else None,
    )
    state.onboarding_service = build_onboarding_service(state, redis_client=redis_client)
    return state


def _free_limits() -> dict[str, int]:
    """`MDX_SIGNUP_FREE_LIMITS` as a dict; malformed values fall back to the default."""
    try:
        parsed = json.loads(settings.signup_free_limits)
        return {str(k): int(v) for k, v in dict(parsed).items()}
    except (ValueError, TypeError):
        logger.error("auth.signup.free_limits_invalid")
        return {"notes_per_month": 50, "members": 3}


def build_onboarding_service(state: ServiceState, *, redis_client: Any = None) -> Any:
    """Wire self-serve signup, or return None so its routes 404.

    Needs MDX_SIGNUP_ENABLED, a mail provider and keycloak/dual mode.
    """
    if not settings.signup_enabled:
        return None
    if settings.idp_mode == "native":
        return None
    if state.email_provider is None:
        logger.error("auth.signup.disabled_no_mail_provider")
        return None

    from .domain import disposable_domains
    from .domain.onboarding_service import OnboardingService, SignupConfig
    from .domain.signup_mailer import SignupMailer

    _identities, challenges, _sessions = build_repositories(state.tenant_writer_pool)
    limiter = (
        FixedWindowLimiter(redis_client, prefix="mdx:auth:rl") if redis_client is not None else None
    )
    if limiter is None:
        # The caps fail CLOSED; an absent limiter must not fail open by omission.
        logger.error("auth.signup.disabled_no_redis")
        return None

    return OnboardingService(
        keycloak=state.keycloak,
        pool=state.tenant_writer_pool,
        challenges=challenges,
        mailer=SignupMailer(
            state.email_provider,
            reply_to=settings.auth_email_reply_to,
            app_base_url=settings.app_base_url,
            timeout_seconds=settings.email_send_timeout_seconds,
        ),
        config=SignupConfig(
            ttl_seconds=settings.signup_ttl_seconds,
            max_attempts=settings.signup_max_attempts,
            resend_seconds=settings.signup_resend_seconds,
            min_password_length=settings.signup_min_password_length,
            signup_ip_limit=settings.signup_ip_limit,
            signup_ip_window_seconds=settings.signup_ip_window_seconds,
            signup_email_limit=settings.signup_email_limit,
            signup_email_window_seconds=settings.signup_email_window_seconds,
            verify_email_limit=settings.signup_verify_email_limit,
            verify_email_window_seconds=settings.signup_verify_email_window_seconds,
            resend_email_limit=settings.signup_resend_email_limit,
            resend_email_window_seconds=settings.signup_resend_email_window_seconds,
            free_limits=_free_limits(),
            disposable_domains=disposable_domains.load(settings.disposable_domains_file or None),
        ),
        limiter=limiter,
        audit=_audit_writer_for(state),
    )


def _audit_writer_for(state: ServiceState) -> Any:
    """Adapt the audit writer to the callable OnboardingService expects (domain never imports libs/audit)."""

    async def _write(
        *,
        tenant_id: UUID,
        kind: str,
        actor_sub: UUID | None,
        payload: dict[str, Any],
        severity: str = "info",
    ) -> None:
        await state.audit_writer.write_event(
            tenant_id=tenant_id,
            kind=kind,
            actor_sub=actor_sub,
            target_kind="user",
            target_id=actor_sub,
            payload=payload,
            severity=Severity.SEC if severity == "sec" else Severity.INFO,
        )

    return _write


def build_session_service(
    state: ServiceState,
    *,
    token_service: TokenService | None,
) -> SessionService | None:
    """Wire rotation, or return None so `/auth/refresh` 404s; needs no mail provider."""
    if not settings.native_issuer_enabled or token_service is None:
        return None
    identities, _challenges, sessions_repo = build_repositories(state.tenant_writer_pool)
    return SessionService(
        tokens=token_service,
        sessions=sessions_repo,
        identities=identities,
        refresh_ttl_seconds=settings.auth_refresh_ttl_seconds,
        absolute_ttl_seconds=settings.auth_session_absolute_ttl_seconds,
        grace_seconds=settings.auth_refresh_grace_seconds,
    )


def build_email_code_service(
    state: ServiceState,
    *,
    token_service: TokenService | None,
    redis_client: Any,
    mfa: MfaService | None = None,
) -> EmailCodeService | None:
    """Wire the email-code sign-in flow, or return None so the routes 404; every ingredient is required."""
    if not settings.native_issuer_enabled:
        return None
    if token_service is None or state.email_provider is None:
        logger.error(
            "auth.otp.disabled_missing_dependency",
            extra={
                "has_token_service": token_service is not None,
                "has_email_provider": state.email_provider is not None,
            },
        )
        return None

    identities, challenges, sessions_repo = build_repositories(state.tenant_writer_pool)
    limiter = None
    if redis_client is not None:
        limiter = FixedWindowLimiter(redis_client, prefix="mdx:auth:rl")
    else:
        # Start scopes fail closed: a missing limiter refuses to send (every signup 503s).
        logger.error("auth.otp.no_rate_limiter")

    async def _audit_account_locked(*, identity_id: UUID, locked_until: datetime) -> None:
        """`auth.account_locked` on the platform tenant (the failing party is not proven to be the holder)."""
        try:
            await state.audit_writer.write_event(
                tenant_id=UUID(settings.auth_platform_tenant_id),
                kind=AUTH_ACCOUNT_LOCKED,
                actor_sub=None,
                target_kind="user",
                target_id=identity_id,
                payload={
                    "identity_id": str(identity_id),
                    "locked_until": locked_until.isoformat(),
                    "method": "email_code",
                },
                severity=Severity.SEC,
            )
        except Exception:  # noqa: BLE001 — never block a refusal on the trail
            logger.warning("auth.otp.lock_audit_failed")

    return EmailCodeService(
        identities=identities,
        challenges=challenges,
        sessions=SessionService(
            tokens=token_service,
            sessions=sessions_repo,
            refresh_ttl_seconds=settings.auth_refresh_ttl_seconds,
        ),
        mailer=CodeMailer(
            state.email_provider,
            reply_to=settings.auth_email_reply_to,
            timeout_seconds=settings.email_send_timeout_seconds,
        ),
        limiter=limiter,
        config=EmailCodeConfig(
            ttl_seconds=settings.otp_ttl_seconds,
            max_attempts=settings.otp_max_attempts,
            resend_seconds=settings.otp_resend_seconds,
            start_email_limit=settings.otp_start_email_limit,
            start_email_window_seconds=settings.otp_start_email_window_seconds,
            start_ip_limit=settings.otp_start_ip_limit,
            start_ip_window_seconds=settings.otp_start_ip_window_seconds,
            verify_ip_limit=settings.otp_verify_ip_limit,
            verify_ip_window_seconds=settings.otp_verify_ip_window_seconds,
            send_timeout_seconds=settings.email_send_timeout_seconds,
            lockout=LockoutPolicy(
                threshold=settings.lockout_threshold,
                base_seconds=settings.lockout_base_seconds,
                max_seconds=settings.lockout_max_seconds,
            ),
        ),
        on_account_locked=_audit_account_locked,
        # A passed email code does not become a session while a second factor is owed.
        mfa=mfa,
    )


async def teardown_state(state: ServiceState) -> None:
    await state.jwks_cache.aclose()
    await state.app_pool.close()
    await state.tenant_writer_pool.close()
    await state.audit_writer_pool.close()
    await state.audit_reader_pool.close()
    await state.keycloak.aclose()
    if state.denylist is not None:
        await state.denylist.aclose()
    if state.email_provider is not None:
        await state.email_provider.aclose()
    if state._redis is not None:
        await state._redis.aclose()
    if state.crypto_pool is not None:
        await state.crypto_pool.close()
