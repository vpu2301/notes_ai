"""Self-serve password signup against Keycloak.

Keycloak user first (disabled), then Postgres; a DB failure deletes the Keycloak
user so nothing exists half-way. Every branch answers the same 202 with the same
amount of work, so the response never says whether the address is known.
"""

from __future__ import annotations

import json
import logging
import secrets as _secrets
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import asyncpg
from opentelemetry import metrics

from ratelimit import RateLimiterUnavailableError

from ..keycloak_client import KeycloakError
from . import compose
from . import email_code as ec
from .disposable_domains import is_disposable
from .errors import ApiError
from .password_policy import check_password

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth")
_signup_counter = _meter.create_counter(
    "mdx_auth_signup_total",
    description="Self-serve signup attempts by outcome",
    unit="1",
)
_signup_verify_counter = _meter.create_counter(
    "mdx_auth_signup_verify_total",
    description="Signup confirmation submissions by outcome",
    unit="1",
)
# `stage` = requested | verified.
_signup_referred_counter = _meter.create_counter(
    "mdx_auth_signup_referred_total",
    description="Signups that arrived through a shared note's CTA, by stage",
    unit="1",
)

KIND_SIGNUP_VERIFY = "signup_verify"

SCOPE_SIGNUP_IP = "signup_ip"
SCOPE_SIGNUP_EMAIL = "signup_email"
SCOPE_SIGNUP_VERIFY_EMAIL = "signup_verify_email"
SCOPE_SIGNUP_RESEND_EMAIL = "signup_resend_email"

# `users.role` for the founding owner of a personal workspace.
_OWNER_USER_ROLE = "tenant_admin"

# Both roles: `tenant_admin` alone has no content permission.
SIGNUP_REALM_ROLES = ("tenant_admin", "member")

_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_=+"


class SignupError(ApiError):
    """A refusal from the signup flow. See :class:`ApiError`."""


@dataclass(frozen=True, slots=True)
class SignupConfig:
    ttl_seconds: int = 600
    max_attempts: int = 5
    resend_seconds: int = 60
    min_password_length: int = 12
    signup_ip_limit: int = 5
    signup_ip_window_seconds: int = 3600
    signup_email_limit: int = 3
    signup_email_window_seconds: int = 86400
    verify_email_limit: int = 10
    verify_email_window_seconds: int = 3600
    resend_email_limit: int = 3
    resend_email_window_seconds: int = 3600
    # Recorded on the tenant, not enforced.
    free_limits: dict[str, int] = field(
        default_factory=lambda: {"notes_per_month": 50, "members": 3}
    )
    # Throwaway-mail domains answer 202 and create nothing.
    disposable_domains: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Account:
    """What signup created, for the caller's audit line. Never a password."""

    sub: UUID
    tenant_id: UUID
    email: str
    display_name: str
    source: str


class SignupMailer(Protocol):
    """Sends the two signup mails. Injected so the service stays testable."""

    async def send_verify(
        self, *, to: str, code: str, lang: str, user_agent: str, ttl_seconds: int
    ) -> None: ...

    async def send_exists(self, *, to: str, lang: str, user_agent: str) -> None: ...

    async def send_concierge(
        self, *, to: str, display_name: str, temporary_password: str, lang: str
    ) -> None: ...


def generate_password(length: int = 20) -> str:
    """A concierge account's first password (mailed once, never logged); rejection-sampled against the policy."""
    for _ in range(50):
        candidate = "".join(_secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if check_password(candidate, min_length=12).ok:
            return candidate
    # Failing loudly beats mailing a password Keycloak will refuse.
    raise RuntimeError("could not generate a policy-compliant password")


class OnboardingService:
    """Create, verify and resend. One class; two callers (HTTP and the CLI)."""

    def __init__(
        self,
        *,
        keycloak: Any,
        pool: asyncpg.Pool,
        challenges: Any,
        mailer: SignupMailer,
        config: SignupConfig,
        limiter: Any = None,
        audit: Any = None,
    ) -> None:
        self._kc = keycloak
        self._pool = pool
        self._challenges = challenges
        self._mailer = mailer
        self._cfg = config
        self._limiter = limiter
        self._audit = audit

    @property
    def mailer(self) -> SignupMailer:
        """Exposed for the concierge CLI; the password it mails never enters this class."""
        return self._mailer

    # ── signup ───────────────────────────────────────────────────────────

    async def signup(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        locale: str = "en",
        ip: str = "",
        user_agent: str = "",
        lang: str = "en",
        ref_code: str | None = None,
    ) -> None:
        """The public path: every outcome is the same 202; raises only for refusals a caller should see."""
        address = ec.normalise_email(email)
        if not compose.looks_like_email(address):
            _signup_counter.add(1, {"result": "invalid_email"})
            raise SignupError(
                "invalid_email", 400, detail="that does not look like an email address"
            )

        display_name = (display_name or "").strip()
        if not display_name:
            _signup_counter.add(1, {"result": "display_name"})
            raise SignupError("display_name_required", 400, detail="a name is required")

        verdict = check_password(
            password,
            min_length=self._cfg.min_password_length,
            email=address,
            display_name=display_name,
        )
        if not verdict.ok:
            # Checked here for a field-level message instead of a wrapped realm error.
            _signup_counter.add(1, {"result": "policy"})
            raise SignupError(
                "password_policy",
                400,
                detail="that password is too easy to guess",
                extras={
                    "min_length": self._cfg.min_password_length,
                    "reasons": list(verdict.reasons),
                },
            )

        await self._check_signup_limits(address=address, ip=ip)

        if is_disposable(address, self._cfg.disposable_domains):
            # A throwaway address gets the same 202 and nothing else.
            _signup_counter.add(1, {"result": "disposable"})
            return

        if await self._address_is_taken(address):
            # Taken: one mail, no user, no challenge, same 202.
            _signup_counter.add(1, {"result": "existing"})
            await self._mailer.send_exists(to=address, lang=lang, user_agent=user_agent)
            return

        account = await self.create_account(
            email=address,
            password=password,
            display_name=display_name,
            locale=locale,
            source="referral" if ref_code else "self_serve",
            ref_code=ref_code,
        )
        await self._open_challenge_and_mail(
            email=address, lang=lang, user_agent=user_agent, identity_sub=account.sub
        )
        _signup_counter.add(1, {"result": "created"})
        if ref_code:
            _signup_referred_counter.add(1, {"stage": "requested"})

    async def create_account(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        locale: str = "en",
        source: str = "self_serve",
        verified: bool = False,
        ref_code: str | None = None,
    ) -> Account:
        """Keycloak user + tenant + membership + `users` row, or nothing at all; ``verified=True`` is the concierge path."""
        tenant_id = uuid4()
        names = ec.personal_workspace_names(email)

        try:
            sub = await self._kc.create_user_with_password(
                email=email,
                display_name=display_name,
                tenant_id=tenant_id,
                password=password,
                realm_roles=list(SIGNUP_REALM_ROLES),
                enabled=verified,
            )
        except KeycloakError as exc:
            if exc.status == 409:
                # Keycloak knows the address though our lookup did not; same outward behaviour.
                raise SignupError(
                    "email_taken", 409, detail="that address is already registered"
                ) from exc
            _signup_counter.add(1, {"result": "unavailable"})
            logger.error("auth.signup.keycloak_failed", extra={"status": exc.status})
            raise SignupError(
                "signup_unavailable", 503, detail="signup is temporarily unavailable"
            ) from exc

        if verified:
            # Enabled at creation, so mark the address confirmed too.
            try:
                await self._kc.set_email_verified(sub, verified=True)
            except KeycloakError:
                logger.warning("auth.signup.concierge_verify_flag_failed", extra={"sub": str(sub)})

        try:
            await self._write_account_rows(
                sub=sub,
                tenant_id=tenant_id,
                email=email,
                display_name=display_name,
                locale=locale,
                names=names,
                status="active" if verified else "invited",
                source=source,
                ref_code=ref_code,
            )
        except Exception as exc:  # noqa: BLE001 — every failure compensates
            # Compensation: a Keycloak user with no rows would occupy the address.
            _signup_counter.add(1, {"result": "compensated"})
            logger.error(
                "auth.signup.db_failed_compensating",
                extra={"sub": str(sub), "error_class": type(exc).__name__},
            )
            try:
                await self._kc.delete_user(sub)
            except Exception:  # noqa: BLE001
                # Now there IS an orphan; the reconciliation query counts these.
                logger.error("auth.signup.compensation_failed", extra={"sub": str(sub)})
            raise SignupError(
                "signup_unavailable", 503, detail="signup is temporarily unavailable"
            ) from exc

        await self._write_audit(
            tenant_id=tenant_id,
            kind="auth.signup",
            actor_sub=sub,
            # Never the ref code itself: it joins to a sender's tenant.
            payload={"source": source, "plan": "free", "ref_present": ref_code is not None},
        )
        return Account(
            sub=sub,
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            source=source,
        )

    async def _write_account_rows(
        self,
        *,
        sub: UUID,
        tenant_id: UUID,
        email: str,
        display_name: str,
        locale: str,
        names: ec.WorkspaceNames,
        status: str,
        attempts: int = 3,
        source: str = "self_serve",
        ref_code: str | None = None,
    ) -> None:
        """Tenant + membership + `users` + identity in ONE transaction (identity id = Keycloak sub, legacy_idp = true)."""
        last_exc: asyncpg.UniqueViolationError | None = None
        for attempt in range(attempts):
            # Collisions are on the workspace name, so only the name is re-drawn.
            name = names.name if attempt == 0 else f"{names.name}-{_secrets.token_hex(2)}"
            try:
                async with self._pool.acquire() as conn, conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO tenants
                            (id, name, display_name, slug, kind, locale, timezone,
                             status, is_active, plan, signup_source, plan_limits)
                        VALUES ($1, $2, $3, $4, 'personal', $5, 'Europe/Kyiv', 'active', true,
                                'free', $6, $7::jsonb)
                        """,
                        tenant_id,
                        name,
                        f"{display_name}'s workspace",
                        names.slug,
                        locale,
                        source,
                        json.dumps(self._cfg.free_limits),
                    )
                    await conn.execute(
                        """
                        INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
                        VALUES ($1, $2, 'owner', 'active')
                        """,
                        tenant_id,
                        sub,
                    )
                    await conn.execute(
                        """
                        INSERT INTO identities
                            (id, email, email_verified_at, display_name, status,
                             locale, timezone, legacy_idp, last_tenant_id)
                        VALUES ($1, $2, $3, $4, 'active', $5, 'Europe/Kyiv', true, $6)
                        """,
                        sub,
                        email,
                        datetime.now(UTC) if status == "active" else None,
                        display_name,
                        locale,
                        tenant_id,
                    )
                    # `users` is RLS-scoped even for tenant_writer; transaction-local setting.
                    await conn.execute(
                        "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                    )
                    await conn.execute(
                        """
                        INSERT INTO users (sub, tenant_id, email, display_name, role, status)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        sub,
                        tenant_id,
                        email,
                        display_name,
                        _OWNER_USER_ROLE,
                        status,
                    )
                    if ref_code:
                        # The workspace id lands on this row at verify; no FK, no sender tenant id.
                        await conn.execute(
                            """
                            INSERT INTO referrals (ref_code, referred_sub, source)
                            VALUES ($1, $2, 'signup')
                            """,
                            ref_code,
                            sub,
                        )
                return
            except asyncpg.UniqueViolationError as exc:
                constraint = str(getattr(exc, "constraint_name", "") or exc)
                if "tenants" not in constraint:
                    # Not a naming collision; retrying will not help.
                    raise
                last_exc = exc
                logger.info("auth.signup.workspace_name_taken", extra={"attempt": attempt + 1})
                continue
        assert last_exc is not None
        raise last_exc

    # ── verify ───────────────────────────────────────────────────────────

    async def verify(self, *, email: str, code: str, ip: str = "") -> None:
        """Spend the code: Keycloak enabled BEFORE the challenge is consumed (an outage keeps the code usable)."""
        address = ec.normalise_email(email)
        await self._check_verify_limits(address=address)

        challenge = await self._challenges.latest_open_for_email(
            kind=KIND_SIGNUP_VERIFY, email=address
        )
        if challenge is None:
            # Same body as an expired challenge: no enumeration oracle.
            _signup_verify_counter.add(1, {"result": "unknown"})
            raise SignupError(
                "challenge_expired", 400, detail="that code has expired; request a new one"
            )

        decision = ec.evaluate(challenge, code)
        if decision.outcome is not ec.VerifyOutcome.OK:
            await self._handle_failed_attempt(challenge, decision)

        sub = challenge.identity_id
        if sub is None:
            _signup_verify_counter.add(1, {"result": "orphan_challenge"})
            raise SignupError(
                "challenge_expired", 400, detail="that code has expired; request a new one"
            )

        try:
            await self._kc.set_email_verified(sub, verified=True)
        except KeycloakError as exc:
            # Before consuming: the code survives an outage.
            _signup_verify_counter.add(1, {"result": "verify_retry"})
            logger.error("auth.signup.enable_failed", extra={"status": exc.status})
            raise SignupError(
                "verify_retry", 409, detail="could not finish just now; try again in a moment"
            ) from exc

        await self._challenges.consume(challenge.id)

        tenant_id = await self._activate_user(sub)
        _signup_verify_counter.add(1, {"result": "ok"})
        if tenant_id is not None:
            referred = await self._attribute_referral(sub, tenant_id)
            if referred:
                _signup_referred_counter.add(1, {"stage": "verified"})
            await self._write_audit(
                tenant_id=tenant_id,
                kind="auth.email_verified",
                actor_sub=sub,
                payload={"ref_present": referred},
                severity="sec",
            )

    async def _attribute_referral(self, sub: UUID, tenant_id: UUID) -> bool:
        """Stamp the tenant id on the referral row; True when the person came through a shared note."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE referrals SET referred_tenant_id = $2
                WHERE referred_sub = $1 AND referred_tenant_id IS NULL
                """,
                sub,
                tenant_id,
            )
        return bool(result) and result.split()[-1] != "0"

    async def _activate_user(self, sub: UUID) -> UUID | None:
        """`users.status` → active and stamp the identity verified.

        The tenant comes from `identities` (no token here) and must be in scope
        before touching `users`: its RLS policy casts an unset setting and raises.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            tenant_id = await conn.fetchval(
                "SELECT last_tenant_id FROM identities WHERE id = $1", sub
            )
            await conn.execute(
                "UPDATE identities SET email_verified_at = now()"
                " WHERE id = $1 AND email_verified_at IS NULL",
                sub,
            )
            if tenant_id is None:
                # No home workspace: nothing to activate.
                return None
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
            await conn.execute(
                "UPDATE users SET status = 'active', updated_at = now()"
                " WHERE sub = $1 AND status = 'invited'",
                sub,
            )
            return UUID(str(tenant_id))

    async def _handle_failed_attempt(
        self, challenge: ec.Challenge, decision: ec.VerifyDecision
    ) -> None:
        """Persist what the attempt did, then raise. Never returns."""
        if decision.consume:
            await self._challenges.consume(challenge.id)
        elif decision.attempts_after != challenge.attempts:
            await self._challenges.record_attempt(challenge.id, attempts=decision.attempts_after)

        outcome = decision.outcome
        _signup_verify_counter.add(1, {"result": str(outcome)})
        if outcome is ec.VerifyOutcome.EXPIRED:
            raise SignupError(
                "challenge_expired", 400, detail="that code has expired; request a new one"
            )
        if outcome is ec.VerifyOutcome.CONSUMED:
            raise SignupError("challenge_consumed", 400, detail="that code has already been used")
        if outcome is ec.VerifyOutcome.EXHAUSTED:
            raise SignupError(
                "too_many_attempts", 429, detail="too many attempts; request a new code"
            )
        raise SignupError(
            "code_invalid",
            400,
            detail="that code is not right",
            extras={"attempts_left": decision.attempts_left},
        )

    # ── resend ───────────────────────────────────────────────────────────

    async def resend(
        self, *, email: str, ip: str = "", user_agent: str = "", lang: str = "en"
    ) -> None:
        """A fresh code, and the old one dies. Uniform 202 like signup."""
        address = ec.normalise_email(email)
        await self._check_resend_limits(address=address)

        sub = await self._pending_signup_sub(address)
        if sub is None:
            # No pending signup: silence, same cost as the other branch.
            return
        await self._open_challenge_and_mail(
            email=address, lang=lang, user_agent=user_agent, identity_sub=sub
        )

    async def _pending_signup_sub(self, email: str) -> UUID | None:
        """The identity of a signup that never confirmed, or None (read from `identities`, not RLS-scoped `users`)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT id FROM identities"
                " WHERE email = $1 AND email_verified_at IS NULL AND status = 'active'"
                " LIMIT 1",
                email,
            )
        return UUID(str(row)) if row else None

    async def _address_is_taken(self, email: str) -> bool:
        """Ours OR Keycloak's. Both, because either one blocks a create."""
        async with self._pool.acquire() as conn:
            known = await conn.fetchval("SELECT 1 FROM identities WHERE email = $1 LIMIT 1", email)
        if known:
            return True
        try:
            return await self._kc.find_user_by_email(email) is not None
        except KeycloakError:
            # A lookup that cannot answer must not be read as "free" (the 409 would leak).
            raise SignupError(
                "signup_unavailable", 503, detail="signup is temporarily unavailable"
            ) from None

    # ── shared ───────────────────────────────────────────────────────────

    async def _open_challenge_and_mail(
        self, *, email: str, lang: str, user_agent: str, identity_sub: UUID
    ) -> None:
        """One open challenge per address: the previous one is consumed first."""
        await self._challenges.consume_open_for_email(kind=KIND_SIGNUP_VERIFY, email=email)

        challenge_id = uuid4()
        code = ec.generate_code()
        await self._challenges.open(
            challenge_id=challenge_id,
            kind=KIND_SIGNUP_VERIFY,
            email=email,
            identity_id=identity_sub,
            code_hash=ec.code_hash(code, challenge_id),
            expires_at=datetime.now(UTC) + timedelta(seconds=self._cfg.ttl_seconds),
            max_attempts=self._cfg.max_attempts,
            client_type="web",
            ip="",
            metadata={},
        )
        await self._mailer.send_verify(
            to=email,
            code=code,
            lang=lang,
            user_agent=user_agent,
            ttl_seconds=self._cfg.ttl_seconds,
        )

    async def _write_audit(
        self,
        *,
        tenant_id: UUID,
        kind: str,
        actor_sub: UUID | None,
        payload: dict[str, Any],
        severity: str = "info",
    ) -> None:
        if self._audit is None:
            return
        try:
            await self._audit(
                tenant_id=tenant_id,
                kind=kind,
                actor_sub=actor_sub,
                payload=payload,
                severity=severity,
            )
        except Exception:  # noqa: BLE001 — never fail the operation it describes
            logger.warning("auth.signup.audit_failed", extra={"kind": kind})

    # ── rate limits ──────────────────────────────────────────────────────

    async def _check_signup_limits(self, *, address: str, ip: str) -> None:
        """Fail CLOSED. A down Redis must not turn signup into an open relay."""
        await self._limit(
            SCOPE_SIGNUP_IP,
            ip or "unknown",
            limit=self._cfg.signup_ip_limit,
            window=self._cfg.signup_ip_window_seconds,
            fail_open=False,
            counter_result="rate_limited",
        )
        await self._limit(
            SCOPE_SIGNUP_EMAIL,
            ec.email_subject_hash(address),
            limit=self._cfg.signup_email_limit,
            window=self._cfg.signup_email_window_seconds,
            fail_open=False,
            counter_result="rate_limited",
        )

    async def _check_verify_limits(self, *, address: str) -> None:
        """Fail OPEN: the attempt budget on the challenge row is the real bound."""
        await self._limit(
            SCOPE_SIGNUP_VERIFY_EMAIL,
            ec.email_subject_hash(address),
            limit=self._cfg.verify_email_limit,
            window=self._cfg.verify_email_window_seconds,
            fail_open=True,
            counter_result=None,
        )

    async def _check_resend_limits(self, *, address: str) -> None:
        await self._limit(
            SCOPE_SIGNUP_RESEND_EMAIL,
            ec.email_subject_hash(address),
            limit=self._cfg.resend_email_limit,
            window=self._cfg.resend_email_window_seconds,
            fail_open=False,
            counter_result="rate_limited",
        )

    async def _limit(
        self,
        scope: str,
        subject: str,
        *,
        limit: int,
        window: int,
        fail_open: bool,
        counter_result: str | None,
    ) -> None:
        if self._limiter is None:
            return
        try:
            decision = await self._limiter.allow(
                scope, subject, limit=limit, window_seconds=window, fail_open=fail_open
            )
        except RateLimiterUnavailableError as exc:
            if fail_open:
                return
            raise SignupError(
                "signup_rate_limited", 429, detail="too many attempts; please wait"
            ) from exc
        if not decision.allowed:
            if counter_result:
                _signup_counter.add(1, {"result": counter_result})
            raise SignupError(
                "signup_rate_limited",
                429,
                detail="too many attempts; please wait",
                retry_after=decision.retry_after,
            )
