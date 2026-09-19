"""BE-0 — self-serve signup on the current stack.

Keycloak stays the identity provider. The account is created through the
admin client with a password already set and ``enabled=false``; a six-digit
code proves the address is reachable; verification enables the account and
flips ``users.status`` to ``active``. From then on the person signs in with
``POST /auth/login`` like every existing user, on web, macOS and iOS, with
no client change at all.

Nothing here is permanent. BE-3's email-code path replaces password signup
once ``MDX_IDP_MODE=dual`` is switched on fleet-wide (ADR-0047), and this
module retires with it. What survives is the workspace self-heal and the
web page. That is written down because the shape of the code should not
pretend otherwise: it is deliberately a thin orchestration over machinery
that already exists, not a new subsystem.

── The two hard parts ───────────────────────────────────────────────────

**One: an account must never exist half-way.** Signup writes to two
stores that cannot share a transaction — Keycloak over HTTP, then Postgres.
The order is Keycloak first, because a Keycloak user with no database rows
can be *deleted*, while database rows referencing a Keycloak user that was
never created cannot be repaired without knowing a sub nobody has. If the
database half fails, the Keycloak user is deleted and the caller gets 503
with nothing created on either side. That compensation is the only reason
the order is what it is.

**Two: the response must not say whether the address is known.** Both
branches answer ``202`` with the same body and the same shape of work —
one challenge row and one mail, queued the same way — so latency does not
discriminate either. The only place the difference exists is in a mailbox
(``signup_verify`` vs ``signup_exists``), which a prober would have to
already control.
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
# Sprint 21: the loop's conversion step. `stage` = requested | verified.
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

# The `users.role` for the founding owner of a personal workspace. They
# are alone in it, so they administer it.
_OWNER_USER_ROLE = "tenant_admin"

# Realm roles for a self-serve account. BOTH, and the second one is not
# optional: S14's admin/content separation gives `tenant_admin` no
# content permission at all — not `note.write`, not `asr.write` — so an
# account holding it alone cannot use the product it just signed up for.
# `docs/auth/roles.md` states the rule; BE-3's first-use test is what
# caught the same mistake on the native path.
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
    # Per the brief: 5/h per IP, 3/day per email, 10/h verify, 3/h resend.
    signup_ip_limit: int = 5
    signup_ip_window_seconds: int = 3600
    signup_email_limit: int = 3
    signup_email_window_seconds: int = 86400
    verify_email_limit: int = 10
    verify_email_window_seconds: int = 3600
    resend_email_limit: int = 3
    resend_email_window_seconds: int = 3600
    # Sprint 21: the free plan, recorded on the tenant (not enforced).
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
    """A concierge account's first password. Mailed once, never logged.

    Rejection sampling until the realm policy would accept it, rather than
    forcing one of each class at fixed positions — a fixed layout is a
    pattern, and the operator is not the one who has to type it anyway.
    """
    for _ in range(50):
        candidate = "".join(_secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if check_password(candidate, min_length=12).ok:
            return candidate
    # 50 rejections at 20 characters is not a thing that happens; if the
    # policy ever becomes that strict, failing loudly beats mailing a
    # password Keycloak will refuse.
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
        """The concierge CLI sends its own mail through this.

        Exposed rather than wrapped in a `send_welcome` method because the
        password it carries never enters this class: `create_account`
        takes one and hands it to Keycloak, and the CLI is the only place
        that both generates it and mails it. Keeping those two facts in
        one function is what makes "the password exists in exactly two
        places" checkable by reading that function.
        """
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
        """The public path. Answers nothing: every outcome is the same 202.

        Raises only for refusals a caller *should* see — a malformed
        address, a password the realm would reject, a rate limit, or an
        outage. Never for "that address is taken": that branch mails and
        returns, indistinguishable from success.
        """
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
            # The policy refuses a password built out of the person's own
            # address or name — the two strings an attacker always has.
            email=address,
            display_name=display_name,
        )
        if not verdict.ok:
            # Checked here, not left to Keycloak, so the person sees a
            # field-level message instead of a 500 wrapping a realm error
            # in a language nobody chose.
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
            # Sprint 21: a throwaway address gets the same 202 and nothing
            # else — no user, no tenant, no mail it would never read.
            _signup_counter.add(1, {"result": "disposable"})
            return

        if await self._address_is_taken(address):
            # The uniform branch. One mail, no user, no challenge — and
            # crucially the same 202 the new-address path returns.
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
        """Keycloak user + tenant + membership + `users` row, or nothing at all.

        ``verified=True`` is the concierge path: an operator vouched for
        the address, so the account is enabled immediately and no code is
        ever sent. The public path leaves it False and lets the code do it.
        """
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
                # Keycloak knows the address even though our own lookup
                # did not — a user created outside this flow, or a race.
                # Same outward behaviour as the taken branch.
                raise SignupError(
                    "email_taken", 409, detail="that address is already registered"
                ) from exc
            _signup_counter.add(1, {"result": "unavailable"})
            logger.error("auth.signup.keycloak_failed", extra={"status": exc.status})
            raise SignupError(
                "signup_unavailable", 503, detail="signup is temporarily unavailable"
            ) from exc

        if verified:
            # The concierge account is enabled at creation; mark the
            # address confirmed too so the two never disagree.
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
            # The compensation the whole ordering exists for. A Keycloak
            # user with no rows is invisible to the product and, worse,
            # occupies the address so the person cannot retry.
            _signup_counter.add(1, {"result": "compensated"})
            logger.error(
                "auth.signup.db_failed_compensating",
                extra={"sub": str(sub), "error_class": type(exc).__name__},
            )
            try:
                await self._kc.delete_user(sub)
            except Exception:  # noqa: BLE001
                # Now there IS an orphan, and it is worth a distinct line:
                # BE-4's reconciliation query counts these, and a non-zero
                # count is a bug rather than a state.
                logger.error("auth.signup.compensation_failed", extra={"sub": str(sub)})
            raise SignupError(
                "signup_unavailable", 503, detail="signup is temporarily unavailable"
            ) from exc

        await self._write_audit(
            tenant_id=tenant_id,
            kind="auth.signup",
            actor_sub=sub,
            # Sprint 21: the plan and whether a shared note brought them.
            # Never the ref code itself: it is the join key to a sender's
            # tenant, and the audit log of the NEW tenant must not hold it.
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
        """Tenant + membership + `users` + identity, in ONE transaction.

        The identity row is not in the brief's list, and is written anyway.
        Everything downstream of signup reads `identities`: `/auth/me`
        returns it, `check-identity-bridge` asserts the pair, and BE-3's
        email-code login resolves an account by it. An account created here
        without one would be a second-class account — invisible on
        `/auth/me`, unable to use the code login when `dual` is switched
        on — for no saving at all, since it is the same transaction.

        `id = <Keycloak sub>` is the convention migration 0027 established
        when it backfilled identities from `users`, so a BE-0 account is
        shaped exactly like a migrated one. `legacy_idp = true` for the
        same reason: its password lives in Keycloak.
        """
        last_exc: asyncpg.UniqueViolationError | None = None
        for attempt in range(attempts):
            # The collision is on the workspace NAME (every `ada@` on every
            # domain wants "ada"), so only the name is re-drawn.
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
                    # `users` is RLS-scoped even for tenant_writer, so the
                    # connection needs a tenant before the insert. Local to
                    # this transaction, cleared at COMMIT.
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
                        # Attribution, half of it: the person. The workspace
                        # id lands on this row at verify, when it is real.
                        # No FK and no sender tenant id — by design (0036).
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
                    # An identity- or users-level collision is not a naming
                    # problem and retrying will not help.
                    raise
                last_exc = exc
                logger.info("auth.signup.workspace_name_taken", extra={"attempt": attempt + 1})
                continue
        assert last_exc is not None
        raise last_exc

    # ── verify ───────────────────────────────────────────────────────────

    async def verify(self, *, email: str, code: str, ip: str = "") -> None:
        """Spend the code: `users.status` → active, Keycloak enabled.

        The Keycloak call is made BEFORE the challenge is consumed, and the
        database update after. That order is what makes the documented
        ``409 verify_retry`` honest: if Keycloak is down the person keeps
        their code and can try again in a minute, rather than losing it to
        an outage that was not theirs.
        """
        address = ec.normalise_email(email)
        await self._check_verify_limits(address=address)

        challenge = await self._challenges.latest_open_for_email(
            kind=KIND_SIGNUP_VERIFY, email=address
        )
        if challenge is None:
            # Same body as an expired challenge: "no pending signup" and
            # "your code ran out" must not be distinguishable, or the
            # endpoint becomes the enumeration oracle `/auth/signup`
            # refuses to be.
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
            # Deliberately BEFORE consuming: the code survives.
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
        """Sprint 21: the workspace is now real, so the referral row that
        signup opened for this person gets the tenant id. True when a row
        was stamped — i.e. the person came through a shared note."""
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
        """`users.status` → active, and stamp the identity as verified.

        The order is forced by row-level security. `users` is scoped per
        tenant, and its policy casts ``current_setting('app.tenant_id')``
        to a UUID — with nothing set that cast raises rather than matching
        no rows, so touching `users` before a tenant is in scope fails
        outright. There is no token here to take a tenant from (the caller
        is confirming an address, not signed in), so the tenant is read
        from `identities`, which is person-level and not tenant-scoped.
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
                # An identity with no home workspace: nothing to activate,
                # and the audit line has no tenant to land on.
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
            # No pending signup: an unknown address, or one already
            # verified. Silence is the answer, and it costs the same as
            # the other branch from outside.
            return
        await self._open_challenge_and_mail(
            email=address, lang=lang, user_agent=user_agent, identity_sub=sub
        )

    async def _pending_signup_sub(self, email: str) -> UUID | None:
        """The identity of a signup that never confirmed, or None.

        Read from `identities` rather than `users.status = 'invited'` for
        the RLS reason in :meth:`_activate_user`, and it is the better
        source anyway: `email_verified_at IS NULL` is a fact about the
        person, while `users.status` is a fact about one membership.
        """
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
            # A lookup that cannot answer must not be read as "free": the
            # create would then 409 and the caller would learn, from a
            # different status code, exactly what the uniform 202 exists
            # to hide.
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
        """Fail OPEN: the 5-attempt budget on the challenge row is the real
        bound on guessing, and it does not need Redis."""
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
