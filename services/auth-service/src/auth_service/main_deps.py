"""Service-wide singletons: JWKS cache, DB pools, audit components.

Created at process start (in main.py's lifespan). Routers consume them
via :func:`auth_service.deps.get_state`.
"""

from __future__ import annotations

import asyncio
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
    # ── Sprint 16: session-revocation denylist (None = feature off) ─────
    denylist: RedisSessionDenylist | None = None
    # IDX-A2 native issuer. Both None in `keycloak` mode.
    signing_keys: KeySet | None = None
    token_service: TokenService | None = None
    # ── Password recovery (None = feature off) ──────────────────────────
    email_provider: EmailProvider | None = None
    password_rate_limiter: PasswordResetRateLimiter | None = None
    # IDX-A3 email one-time codes. None in keycloak mode, or when native
    # mode has no mail provider — the routes 404 rather than half-work.
    email_code_service: EmailCodeService | None = None
    # IDX-A5 second factors and the account surface. Same posture.
    account_services: AccountServices | None = None
    # IDX-A2's session half (carried by IDX-M1): rotation and revocation
    # for `/auth/refresh` and `/auth/logout`. Native mode only, and —
    # unlike the two above — it needs no mail provider: a deployment that
    # cannot send a code can still renew a session that already exists.
    session_service: SessionService | None = None
    # BE-0 self-serve signup. None unless MDX_SIGNUP_ENABLED and a mail
    # provider are both set — an endpoint that accepts a signup and can
    # never send the code is worse than one that is not there.
    onboarding_service: Any = None
    _redis: Any = None

    @property
    def notification_bus(self) -> Any:
        """The Redis client S21's notification producer publishes on.

        None when notifications are off or the client failed to build —
        `emit_mfa_reminder` treats that as "don't publish", which is the
        correct posture: the reminder's durable half is the DB row.
        """
        return self._redis if settings.notifications_enabled else None

    # ── Sprint 16 MFA: lazy envelope wiring ──────────────────────────────
    # The TOTP secret store needs libs/crypto, which needs the master key
    # and the crypto_writer pool. Built on FIRST use so an auth-service
    # deployment that never enables MFA never needs the master key mounted.
    crypto_pool: asyncpg.Pool | None = None
    envelope: Envelope | None = None
    _envelope_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_envelope(self) -> Envelope:
        """Build (once) and return the envelope for TOTP-secret crypto.

        Raises ``crypto.MasterKeyError`` if the configured master-key
        provider is unusable — callers surface that as 503 with the
        runbook pointer, never as a silent fallback.
        """
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
    """The native issuer's key set + minter, or (None, None) in keycloak mode.

    In `dual` and `native` a missing or invalid key list is a startup
    failure: an issuer that cannot sign is not a degraded issuer, it is no
    issuer. In `dual` in particular, booting without keys would leave the
    fleet configured to trust an issuer that never produces a token —
    silent, and indistinguishable from a working rollout until the first
    signup fails.
    """
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
    """The issuers THIS service trusts on its own protected endpoints.

    Not simply the fleet-wide ``AUTH_ISSUERS_JSON``: auth-service's list
    is decided by its mode, because it is the one service whose mode says
    which issuers actually exist.

    - ``keycloak`` — the configured list (in practice Keycloak alone).
    - ``dual``     — the configured list plus its own native issuer. Both
      are live, so both open a protected endpoint; that is the whole
      point of the period (ADR-0047).
    - ``native``   — its own issuer ONLY. Keycloak no longer mints, and a
      Keycloak-signed token left in a browser must not outlive the
      cut-over by opening a native endpoint.
    """
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
    # dual: both, with the native entry appended only if the fleet-wide
    # config has not already named it.
    if any(entry.issuer == native.issuer for entry in configured):
        return configured
    return [*configured, native]


def build_jwks_cache(signing_keys: KeySet | None) -> JwksCache:
    """The cache ``current_user`` verifies bearer tokens against.

    Keycloak's document is fetched over HTTP like every other service in
    the fleet does it.

    Its OWN document is not. auth-service is that issuer, so fetching it
    would be a self-call over the network — one that fails during startup,
    behind a load balancer that has not yet marked the pod healthy, or any
    time the pod cannot resolve its own public name. The keys are already
    in memory, so the same document is served in-process. The verification
    path is otherwise byte for byte the one note-service uses: same cache,
    same `verify_token`, same issuer and audience checks. Anything else
    would mean auth-service accepting tokens the rest of the fleet rejects.

    In `dual` both are needed at once, so the transport routes: the
    service's own JWKS URL is answered from memory, everything else goes
    to the real network.
    """
    issuers = auth_issuers()
    urls = issuer_url_map(issuers)

    if signing_keys is None:
        return JwksCache(issuer_to_url=urls)

    # The URL to answer from memory is the one THIS service's issuer entry
    # actually names, not the one `native_issuer_config()` derives from
    # `AUTH_ISSUER_URL`. Those differ whenever the fleet is configured with
    # an in-cluster JWKS address behind a browser-facing `iss` — the normal
    # shape once anything but the SPA's own origin can reach this service.
    # Matching the derived URL there would send auth-service out over the
    # network to fetch its own keys.
    native = native_issuer_config()
    self_jwks_url = urls.get(native.issuer, native.jwks_url)

    def _serve(request: httpx.Request) -> httpx.Response:
        # Read through to the live key set on every call, so a rotation is
        # picked up at the cache's next refresh rather than at restart.
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
    """Answer our own JWKS URL from memory; send everything else to the network.

    Only reachable in `dual`, where the cache holds two issuers and only
    one of them is us.
    """

    def __init__(
        self, self_url: str, serve: Callable[[httpx.Request], httpx.Response]
    ) -> None:
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
    """Everything the IDX-A5 routers resolve through one attribute.

    A bundle rather than five fields on ``ServiceState`` because the five
    are useless apart: a deployment either has the native account surface
    or it does not, and ``native_services()`` needs one thing to check.
    """

    identities: Any
    challenges: Any
    sessions: Any
    mfa: MfaService
    account: AccountService
    # None when there is no Redis: the client-credentials lock fails
    # closed, and a grant endpoint that cannot enforce its lock must not
    # be reachable at all.
    credentials: CredentialService | None
    platform_tenant_id: str


def build_account_services(
    state: ServiceState,
    *,
    token_service: TokenService | None,
    redis_client: Any = None,
) -> AccountServices | None:
    """Wire IDX-A5, or return None so its routes 404.

    Needs everything IDX-A3 needs plus a mail provider for the security
    notices. The envelope for TOTP secrets is NOT built here: it is
    resolved on first use, so a deployment where nobody has enrolled a
    second factor never needs the master key mounted.
    """
    # `dual` gets these too: the welcome step writes the browser's
    # timezone through `PATCH /auth/me`, which lives in this bundle. What
    # `dual` does NOT get is the native MFA router — see `create_app`.
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
        # The revert link lands on THIS service, not the SPA: the page has
        # to restore the address and end every session before it can show
        # anything, and routing that through the app would hand the SPA a
        # one-shot credential it has no other use for.
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
    # IDX-B1b. Built only with a Redis client, because the guessing lock
    # fails closed: without a backend every grant would answer 503, and an
    # endpoint that can only fail is worse than one that is not mounted.
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
    # Built before the pools because in native mode it needs the key set,
    # and a missing key is a startup failure rather than a 503 later.
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

    # ── Password recovery ────────────────────────────────────────────
    # Built only when the feature is on, so a deployment that never
    # enables it needs no mail relay, no Redis for the limiter, and
    # cannot trip the MockProvider production guard at startup.
    email_provider: EmailProvider | None = None
    password_rate_limiter: PasswordResetRateLimiter | None = None

    # One connection for both Redis users in this service — the recovery
    # rate limiter and (S21) the notification publisher. Built when EITHER
    # is on: a deployment that mails no password resets but does remind
    # users about MFA still needs a bus, and two clients to one server
    # would be two connection pools for no reason. (The revocation
    # denylist keeps its own client: it is built by libs/auth behind
    # `build_session_denylist` and has its own failure posture.)
    # IDX-A3 adds a third user: the OTP rate limiter, whose start scopes
    # fail CLOSED. It needs the same client for the same reason.
    native_email_code = settings.native_issuer_enabled
    # BE-0 adds a fourth: signup's per-IP and per-email caps, which fail
    # CLOSED. Without the client they would fail by omission — the one
    # posture an unauthenticated mail-sending endpoint must never have.
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

    # Signup needs a relay for the same reason the code login does: the
    # mail IS the proof of the address.
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
            # The limiter is fail-open by design; failing to construct it
            # at all is the same posture, so it must not stop the service
            # from starting. The router treats None as "no limit" and
            # logs it once here rather than on every request.
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


def build_onboarding_service(state: ServiceState, *, redis_client: Any = None) -> Any:
    """Wire BE-0 self-serve signup, or return None so its routes 404.

    Three conditions, and each of them would otherwise produce an endpoint
    that accepts a request it cannot finish:

    * ``MDX_SIGNUP_ENABLED`` — an explicit opt-in. Signup creates Keycloak
      users and sends mail to addresses nobody has verified; a deployment
      should not discover it is open because a router happened to be
      mounted.
    * a mail provider — the code is the only proof of the address, so a
      deployment that cannot send one has no signup.
    * ``keycloak`` or ``dual`` mode — in ``native`` Keycloak no longer
      holds credentials and BE-3's ``/auth/email/*`` is the way in.
    """
    if not settings.signup_enabled:
        return None
    if settings.idp_mode == "native":
        return None
    if state.email_provider is None:
        logger.error("auth.signup.disabled_no_mail_provider")
        return None

    from .domain.onboarding_service import OnboardingService, SignupConfig
    from .domain.signup_mailer import SignupMailer

    _identities, challenges, _sessions = build_repositories(state.tenant_writer_pool)
    limiter = (
        FixedWindowLimiter(redis_client, prefix="mdx:auth:rl")
        if redis_client is not None
        else None
    )
    if limiter is None:
        # The per-IP and per-email caps fail CLOSED, and a limiter that is
        # absent rather than merely unavailable would fail OPEN by
        # omission — the one posture signup must never have.
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
        ),
        limiter=limiter,
        audit=_audit_writer_for(state),
    )


def _audit_writer_for(state: ServiceState) -> Any:
    """Adapt the audit writer to the callable OnboardingService expects.

    A callable rather than the writer itself so the domain module never
    imports libs/audit — the severity vocabulary is translated here, at
    the seam, and the service stays testable with a list.
    """

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
    """Wire rotation, or return None so `/auth/refresh` 404s.

    Deliberately independent of `build_account_services`: that one needs
    a mail provider and returns None without one, and a deployment with
    no relay must still be able to keep its existing sessions alive.
    """
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
    """Wire IDX-A3's sign-in flow, or return None so the routes 404.

    Every ingredient is required. A deployment in native mode with no
    signing key cannot mint a session; one with no mail provider cannot
    send a code. Half-wiring either would produce an endpoint that
    accepts requests and can never complete them, which is worse than an
    endpoint that says it is not there.
    """
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
        # The start scopes fail closed, so "no limiter" must not become a
        # silent downgrade to "unlimited": the service treats a missing
        # limiter exactly like an unreachable one and refuses to send.
        # Loud, because the symptom is every signup returning 503.
        logger.error("auth.otp.no_rate_limiter")

    async def _audit_account_locked(*, identity_id: UUID, locked_until: datetime) -> None:
        """`auth.account_locked` on the platform tenant.

        The platform rather than the account's own workspace: a lock is
        reached by failing to sign in, and the failing party is not
        established to be the account holder — which is the entire reason
        the event is worth recording.
        """
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
        # IDX-A5: a passed email code does not become a session while a
        # second factor is owed.
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
