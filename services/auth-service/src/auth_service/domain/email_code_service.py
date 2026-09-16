"""Email one-time-code sign-in: the orchestration between the pieces.

``domain.email_code`` decides things, ``domain.identity_repository``
stores them, ``libs/ratelimit`` counts them, ``adapters.email`` mails
them. This module is the sequence, and the sequence is where the
security properties live:

**Start is an enumeration dead end.** It does the same work for an
address that has an account and one that does not — the same lookup, the
same challenge row, the same mail — and returns the same 202 with the
same fields. Two differences are visible and both are accepted:
rate-limit rejections are deliberate (the per-email limit applies
identically to known and unknown addresses, so it says nothing about the
address), and a locked account that has already been sent its lock
notice answers faster because it sends no mail — see ``start``.

**Verify never becomes an oracle.** A dead challenge (consumed, expired)
is refused before the code is compared, so "wrong code" and "wrong
challenge" cannot be told apart by trying a code you know is right.

**Nothing here logs an address or a code.** Log records carry
``challenge_id`` / ``identity_id``; both are opaque and both are
already in the audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, Protocol
from uuid import UUID, uuid4

from opentelemetry import metrics

from ratelimit import Decision, RateLimiterUnavailableError

from ..adapters.email import EmailProvider
from . import compose, mailing
from . import copy as copy_mod
from . import email_code as ec
from .errors import ApiError
from .identity_repository import Identity, IdentityRepository, Membership
from .session_service import SessionService, StartedSession

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth")
_otp_start_counter = _meter.create_counter(
    "mdx_auth_otp_start_total",
    description="Sign-in code requests by outcome",
    unit="1",
)
_otp_verify_counter = _meter.create_counter(
    "mdx_auth_otp_verify_total",
    description="Sign-in code submissions by outcome",
    unit="1",
)
_signup_counter = _meter.create_counter(
    "mdx_auth_signup_total",
    description="Identities created by self-serve signup",
    unit="1",
)
# The send histogram and failure counter live in `domain.mailing`, which
# owns the actual send; declaring them twice would create two instruments
# with one name.

# Rate-limit scopes (libs/ratelimit key: mdx:auth:rl:<scope>:<subject>:<window>).
SCOPE_START_EMAIL = "otp_start_email"
SCOPE_START_IP = "otp_start_ip"
SCOPE_VERIFY_IP = "otp_verify_ip"
SCOPE_COOLDOWN = "otp_cooldown"


class EmailCodeError(ApiError):
    """A refusal from the email-code flow. See :class:`ApiError`."""


@dataclass(frozen=True, slots=True)
class EmailCodeConfig:
    ttl_seconds: int = 600
    max_attempts: int = 5
    resend_seconds: int = 60
    start_email_limit: int = 5
    start_email_window_seconds: int = 900
    start_ip_limit: int = 20
    start_ip_window_seconds: int = 3600
    verify_ip_limit: int = 60
    verify_ip_window_seconds: int = 900
    send_timeout_seconds: float = 5.0
    lockout: ec.LockoutPolicy = field(default_factory=ec.LockoutPolicy)


@dataclass(frozen=True, slots=True)
class StartResult:
    challenge_id: UUID
    expires_in: int
    resend_after: int


class MfaGate(Protocol):
    """The second-factor check every first factor must pass through (IDX-A5 F3).

    Structural, so this module knows nothing about TOTP; ``MfaService``
    satisfies it and ``main_deps`` wires the two together.
    """

    async def challenge_if_required(
        self,
        identity: Identity,
        *,
        membership: Membership,
        client_type: str,
        ip: str,
        user_agent: str,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class VerifyResult:
    identity: Identity
    membership: Membership
    memberships: list[Membership]
    # None exactly when a second factor is still owed — the first factor
    # passed but it does not, on its own, buy a session.
    session: StartedSession | None
    is_new_identity: bool
    reactivated: bool
    challenge_id: UUID
    mfa_challenge: Any = None


class AccountLockedHook(Protocol):
    """Notified when a failure count trips a lock, so the route layer can
    write the ``auth.account_locked`` security event."""

    async def __call__(self, *, identity_id: UUID, locked_until: datetime) -> None: ...


class Limiter(Protocol):
    async def allow(
        self,
        scope: str,
        subject: str,
        *,
        limit: int,
        window_seconds: int,
        fail_open: bool = True,
        cost: int = 1,
    ) -> Decision: ...


# ── mail ─────────────────────────────────────────────────────────────────


class CodeMailer:
    """Renders and sends the two A3 mails inline, under a timeout.

    Inline rather than through the outbox worker that carries password
    mail: a sign-in code is only useful for ten minutes, and a queue the
    user waits on turns a slow relay into "sign-in is broken" with no
    error anywhere. The cost of inline is that a relay hiccup becomes a
    503 the user can see and retry, which is the honest failure.
    """

    def __init__(
        self,
        provider: EmailProvider,
        *,
        reply_to: str,
        timeout_seconds: float,
    ) -> None:
        self._provider = provider
        self._reply_to = reply_to
        self._timeout = timeout_seconds

    async def _send(self, kind: str, lang: str, *, to: str, fields: dict[str, Any]) -> None:
        await mailing.send_rendered(
            self._provider,
            kind,
            lang,
            to=to,
            fields=fields,
            reply_to=self._reply_to,
            timeout_seconds=self._timeout,
        )

    async def send_code(
        self, *, to: str, lang: str, code: str, ttl_seconds: int, user_agent: str
    ) -> None:
        await self._send(
            copy_mod.KIND_AUTH_CODE,
            lang,
            to=to,
            fields=compose.auth_code_fields(
                lang=lang,
                code=code,
                ttl_seconds=ttl_seconds,
                user_agent=user_agent,
                requested_at=datetime.now(UTC),
            ),
        )

    async def send_locked(self, *, to: str, lang: str, locked_until: datetime) -> None:
        await self._send(
            copy_mod.KIND_AUTH_LOCKED,
            lang,
            to=to,
            fields=compose.auth_locked_fields(lang=lang, locked_until=locked_until),
        )


# ── the service ──────────────────────────────────────────────────────────


class EmailCodeService:
    def __init__(
        self,
        *,
        identities: IdentityRepository,
        challenges: ec.ChallengeStore,
        sessions: SessionService,
        mailer: CodeMailer,
        limiter: Limiter | None,
        config: EmailCodeConfig,
        on_account_locked: AccountLockedHook | None = None,
        mfa: MfaGate | None = None,
        clock: Any = None,
    ) -> None:
        self._identities = identities
        self._challenges = challenges
        self._sessions = sessions
        self._mailer = mailer
        self._limiter = limiter
        self._cfg = config
        # Called when a failure trips a lock. A hook rather than an audit
        # writer dependency: this module has no business knowing what a
        # tenant is, and the one caller that does is the route layer.
        self._on_account_locked = on_account_locked
        self._mfa = mfa
        self._now = clock or (lambda: datetime.now(UTC))

    # ── start ────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        email: str,
        ip: str,
        client_type: str,
        lang: str,
        user_agent: str,
    ) -> StartResult:
        """Issue a code. The response shape does not depend on the address."""
        address = ec.normalise_email(email)
        if not compose.looks_like_email(address):
            _otp_start_counter.add(1, {"result": "invalid_email"})
            raise EmailCodeError(
                "invalid_email", 400, detail="that does not look like an email address"
            )

        await self._check_start_limits(address=address, ip=ip)

        # From here on both branches do identical work. The lookup happens
        # for an unknown address too — not because the answer is used
        # differently, but because a skipped query is a timing signal.
        identity = await self._identities.get_by_email(address)
        if identity is not None and identity.status == "deleted":
            identity = None

        await self._check_resend_cooldown(address=address)

        locked_until = identity.locked_until if identity is not None else None
        locked = ec.is_locked(locked_until, now=self._now())

        # A superseded challenge, then a fresh one — for the locked account
        # too, so the row the response points at exists and behaves like
        # any other. Its code is simply never mailed, so it cannot be
        # verified: the lock holds without the response admitting it.
        await self._challenges.consume_open_for_email(kind=ec.KIND_EMAIL_LOGIN, email=address)
        code = ec.generate_code()
        challenge = await self._open_challenge(
            address=address,
            identity=identity,
            code=code,
            client_type=client_type,
            ip=ip,
        )

        try:
            if locked and identity is not None and locked_until is not None:
                # One notice per lock, claimed atomically. A locked account
                # must not become a mail cannon aimed at its owner.
                #
                # Residual, accepted: the second request against an
                # already-notified locked account sends no mail and so
                # returns faster than a normal start. Reaching that state
                # costs an attacker ten failures against an account they
                # must already know exists, so the timing tells them
                # nothing they did not have to know first — and evening it
                # out would mean a deliberate delay on every sign-in.
                if await self._identities.claim_lock_notice(identity.id):
                    await self._mailer.send_locked(to=address, lang=lang, locked_until=locked_until)
                _otp_start_counter.add(1, {"result": "locked"})
            else:
                await self._mailer.send_code(
                    to=address,
                    lang=lang,
                    code=code,
                    ttl_seconds=self._cfg.ttl_seconds,
                    user_agent=user_agent,
                )
                _otp_start_counter.add(1, {"result": "sent"})
        except Exception as exc:
            # No mail means no way to complete this challenge. Leaving the
            # row would leave a live code nobody has, which only shortens
            # the odds for someone guessing six digits.
            await self._challenges.delete(challenge.id)
            raise EmailCodeError(
                "email_delivery_unavailable",
                503,
                detail="the code could not be sent; please try again",
            ) from exc

        logger.info(
            "auth.otp.started",
            extra={
                "challenge_id": str(challenge.id),
                "client_type": client_type,
                "known_identity": identity is not None,
                "locked": locked,
            },
        )
        return StartResult(
            challenge_id=challenge.id,
            expires_in=self._cfg.ttl_seconds,
            resend_after=self._cfg.resend_seconds,
        )

    async def _open_challenge(
        self,
        *,
        address: str,
        identity: Identity | None,
        code: str,
        client_type: str,
        ip: str,
    ) -> ec.Challenge:
        # The id is drawn here, not by the database, because the stored
        # hash is bound to it (F1). Letting Postgres assign it would mean
        # writing a row with a placeholder hash and correcting it a
        # statement later — a row briefly live with a code nobody can use.
        challenge_id = uuid4()
        return await self._challenges.open(
            challenge_id=challenge_id,
            kind=ec.KIND_EMAIL_LOGIN,
            email=address,
            identity_id=identity.id if identity is not None else None,
            code_hash=ec.code_hash(code, challenge_id),
            expires_at=self._now() + timedelta(seconds=self._cfg.ttl_seconds),
            max_attempts=self._cfg.max_attempts,
            client_type=client_type,
            ip=ip,
        )

    async def _check_start_limits(self, *, address: str, ip: str) -> None:
        if self._limiter is None:
            # No limiter configured is the same condition as a limiter that
            # cannot be reached, and this endpoint's posture for that is
            # closed. Anything else would make "Redis is missing" the one
            # way to get an unmetered mail-sending endpoint.
            _otp_start_counter.add(1, {"result": "limiter_unavailable"})
            raise EmailCodeError(
                "rate_limiter_unavailable",
                503,
                detail="sign-in codes are briefly unavailable; please try again",
            )
        subjects = (
            (
                SCOPE_START_EMAIL,
                ec.email_subject_hash(address),
                self._cfg.start_email_limit,
                self._cfg.start_email_window_seconds,
            ),
            (
                SCOPE_START_IP,
                ip or "unknown",
                self._cfg.start_ip_limit,
                self._cfg.start_ip_window_seconds,
            ),
        )
        for scope, subject, limit, window in subjects:
            try:
                # Fail CLOSED. This endpoint sends mail to an
                # attacker-chosen address with no authentication; with the
                # counter down, "allow everything" is an open relay.
                decision = await self._limiter.allow(
                    scope, subject, limit=limit, window_seconds=window, fail_open=False
                )
            except RateLimiterUnavailableError as exc:
                _otp_start_counter.add(1, {"result": "limiter_unavailable"})
                raise EmailCodeError(
                    "rate_limiter_unavailable",
                    503,
                    detail="sign-in codes are briefly unavailable; please try again",
                ) from exc
            if not decision.allowed:
                _otp_start_counter.add(1, {"result": "rate_limited"})
                raise EmailCodeError(
                    "rate_limited",
                    429,
                    detail="too many code requests; please wait",
                    retry_after=decision.retry_after,
                )

    async def _check_resend_cooldown(self, *, address: str) -> None:
        """One code per minute per address.

        The pack keys this on ``challenge_id``; with no separate resend
        endpoint the client's only way to ask again is another ``start``,
        which has no challenge id yet — so the subject is the address and
        the authority is the DB. Redis is the cheap first check and fails
        OPEN: the ``created_at`` comparison below is the real rule and it
        does not depend on a cache.
        """
        if self._limiter is not None:
            decision = await self._limiter.allow(
                SCOPE_COOLDOWN,
                ec.email_subject_hash(address),
                limit=1,
                window_seconds=self._cfg.resend_seconds,
                fail_open=True,
            )
            if not decision.allowed:
                _otp_start_counter.add(1, {"result": "rate_limited"})
                raise EmailCodeError(
                    "rate_limited",
                    429,
                    detail="a code was just sent; please wait before asking for another",
                    retry_after=decision.retry_after,
                )

        latest = await self._challenges.latest_open_for_email(
            kind=ec.KIND_EMAIL_LOGIN, email=address
        )
        if latest is None:
            return
        allowed_at = ec.resend_allowed_at(
            latest.created_at, cooldown_seconds=self._cfg.resend_seconds
        )
        now = self._now()
        if now < allowed_at:
            _otp_start_counter.add(1, {"result": "rate_limited"})
            raise EmailCodeError(
                "rate_limited",
                429,
                detail="a code was just sent; please wait before asking for another",
                retry_after=max(1, int((allowed_at - now).total_seconds())),
            )

    # ── verify ───────────────────────────────────────────────────────

    async def verify(
        self,
        *,
        challenge_id: UUID,
        code: str,
        ip: str,
        client_type: str,
        user_agent: str,
        # BE-3 F4. Only read on the signup branch, and only to seed the
        # new workspace: the browser's `Accept-Language` is a decent first
        # guess at what someone reads, and a much better one than "en" for
        # a product with Ukrainian and German customers. Anything the
        # product has no copy for falls back to `en` (`normalise_lang`).
        locale: str = "en",
    ) -> VerifyResult:
        await self._check_verify_limits(ip=ip)

        challenge = await self._challenges.get(challenge_id)
        if challenge is None or challenge.kind != ec.KIND_EMAIL_LOGIN:
            # Indistinguishable from a challenge that expired and was
            # purged, which is what an unknown id usually is. The client
            # needs the same next step either way: ask for a new code.
            _otp_verify_counter.add(1, {"result": "expired"})
            raise EmailCodeError(
                "challenge_expired", 400, detail="that code has expired; request a new one"
            )

        decision = ec.evaluate(challenge, code, now=self._now())
        if decision.outcome is not ec.VerifyOutcome.OK:
            await self._handle_failed_attempt(challenge, decision)

        # Success is claimed atomically: the loser of a double submit is
        # told the challenge is consumed rather than being handed a
        # second session.
        if not await self._challenges.consume(challenge.id):
            _otp_verify_counter.add(1, {"result": "consumed"})
            raise EmailCodeError(
                "challenge_consumed", 400, detail="that code has already been used"
            )

        return await self._complete(
            challenge, ip=ip, client_type=client_type, user_agent=user_agent, locale=locale
        )

    async def _handle_failed_attempt(
        self, challenge: ec.Challenge, decision: ec.VerifyDecision
    ) -> NoReturn:
        """Persist the consequences of a non-OK attempt, then raise. Never returns."""
        outcome = decision.outcome
        if decision.consume:
            await self._challenges.consume(challenge.id)
        elif decision.attempts_after != challenge.attempts:
            await self._challenges.record_attempt(challenge.id, attempts=decision.attempts_after)

        if outcome is ec.VerifyOutcome.EXHAUSTED and challenge.identity_id is not None:
            # An exhausted challenge is a failed sign-in for lockout
            # purposes — the counter that eventually locks the account is
            # per identity, not per challenge, so five guesses on each of
            # ten challenges is not free.
            lock = await self._identities.register_failure(
                challenge.identity_id, policy=self._cfg.lockout, now=self._now()
            )
            if lock.newly_locked and lock.locked_until is not None:
                logger.warning(
                    "auth.account_locked",
                    extra={"identity_id": str(challenge.identity_id)},
                )
                if self._on_account_locked is not None:
                    await self._on_account_locked(
                        identity_id=challenge.identity_id, locked_until=lock.locked_until
                    )

        logger.info(
            "auth.otp.failed",
            extra={"challenge_id": str(challenge.id), "outcome": str(outcome)},
        )
        _otp_verify_counter.add(1, {"result": str(outcome)})
        if outcome is ec.VerifyOutcome.CONSUMED:
            raise EmailCodeError(
                "challenge_consumed", 400, detail="that code has already been used"
            )
        if outcome is ec.VerifyOutcome.EXPIRED:
            raise EmailCodeError(
                "challenge_expired", 400, detail="that code has expired; request a new one"
            )
        if outcome is ec.VerifyOutcome.EXHAUSTED:
            raise EmailCodeError(
                "too_many_attempts",
                429,
                detail="too many wrong codes; request a new one",
            )
        raise EmailCodeError(
            "code_invalid",
            400,
            detail="that code is not right",
            extras={"attempts_left": decision.attempts_left},
        )

    async def _check_verify_limits(self, *, ip: str) -> None:
        if self._limiter is None:
            return
        # Fail OPEN: the per-challenge attempt budget in the database is
        # the real bound on guessing, and it does not need Redis. Locking
        # everyone out of sign-in because a cache is down would be the
        # more expensive failure.
        decision = await self._limiter.allow(
            SCOPE_VERIFY_IP,
            ip or "unknown",
            limit=self._cfg.verify_ip_limit,
            window_seconds=self._cfg.verify_ip_window_seconds,
            fail_open=True,
        )
        if not decision.allowed:
            _otp_verify_counter.add(1, {"result": "rate_limited"})
            raise EmailCodeError(
                "rate_limited",
                429,
                detail="too many attempts; please wait",
                retry_after=decision.retry_after,
            )

    async def _complete(
        self,
        challenge: ec.Challenge,
        *,
        ip: str,
        client_type: str,
        user_agent: str,
        locale: str = "en",
    ) -> VerifyResult:
        """The code was right. Resolve or create the account and open a session."""
        identity = await self._resolve_identity(challenge)
        is_new_identity = identity is None
        reactivated = False

        if identity is None:
            identity, membership = await self._identities.create_with_personal_workspace(
                challenge.email, locale=locale
            )
            memberships = [membership]
            _signup_counter.add(1, {"source": "email_code"})
        else:
            if identity.status == "disabled":
                _otp_verify_counter.add(1, {"result": "disabled"})
                raise EmailCodeError(
                    "account_disabled", 403, detail="this account has been disabled"
                )
            if identity.status == "pending_deletion":
                await self._identities.reactivate(identity.id)
                reactivated = True
            _refuse_legacy_mfa(identity)
            memberships = await self._identities.list_memberships(identity.id)
            preferred = _preferred_membership(memberships, identity.last_tenant_id)
            if preferred is None:
                # An account with no workspace cannot be given a token:
                # every claim set needs a `tid`. BE-2 F3: give them the
                # personal workspace every identity is entitled to instead
                # of refusing a sign-in they cannot do anything about.
                healed = await self._identities.ensure_personal_workspace(
                    identity.id, identity.email, locale=identity.locale
                )
                if healed is None:
                    _otp_verify_counter.add(1, {"result": "no_workspace"})
                    # 409, not 403: the contract in docs/api/error-codes.md
                    # already names this code for session start, and the
                    # meaning is "the account is in a state that cannot be
                    # served", not "you may not".
                    raise EmailCodeError(
                        "no_workspace",
                        409,
                        detail="this account is not a member of any workspace",
                    )
                memberships = [healed]
                preferred = healed
            membership = preferred

        # IDX-A5: a passed first factor is not a session if a second one
        # is owed. The gate is asked even for a brand-new identity — it
        # cannot have MFA, but routing signup around the check is exactly
        # how a bypass gets introduced later.
        if self._mfa is not None:
            pending = await self._mfa.challenge_if_required(
                identity,
                membership=membership,
                client_type=client_type,
                ip=ip,
                user_agent=user_agent,
            )
            if pending is not None:
                _otp_verify_counter.add(1, {"result": "mfa_required"})
                return VerifyResult(
                    identity=identity,
                    membership=membership,
                    memberships=memberships,
                    session=None,
                    is_new_identity=is_new_identity,
                    reactivated=reactivated,
                    challenge_id=challenge.id,
                    mfa_challenge=pending,
                )

        session = await self._sessions.start(
            identity=identity,
            membership=membership,
            client_type=client_type,
            ip=ip,
            user_agent=user_agent,
        )
        # Clears the lockout counters and remembers the landing workspace.
        await self._identities.note_successful_login(identity.id, tenant_id=membership.tenant_id)

        _otp_verify_counter.add(1, {"result": "new_identity" if is_new_identity else "ok"})
        logger.info(
            "auth.otp.verified",
            extra={
                "challenge_id": str(challenge.id),
                "identity_id": str(identity.id),
                "client_type": client_type,
                "is_new_identity": is_new_identity,
            },
        )
        return VerifyResult(
            identity=identity,
            membership=membership,
            memberships=memberships,
            session=session,
            is_new_identity=is_new_identity,
            reactivated=reactivated,
            challenge_id=challenge.id,
        )

    async def _resolve_identity(self, challenge: ec.Challenge) -> Identity | None:
        """Who the challenge is for, as of now — not as of when it was issued.

        The address may have acquired an identity in the ten minutes since
        (two devices, two codes, the other one finished first), so the
        address is re-checked rather than trusting the stored id.
        """
        identity: Identity | None = None
        if challenge.identity_id is not None:
            identity = await self._identities.get(challenge.identity_id)
        if identity is None or identity.status == "deleted":
            # `deleted` cannot match by address (the purge rewrites it),
            # so this lookup returns None and signup proceeds — which is
            # the documented "treat as unknown email".
            identity = await self._identities.get_by_email(challenge.email)
        if identity is not None and identity.status == "deleted":
            return None
        return identity


def _refuse_legacy_mfa(identity: Identity) -> None:
    """`409 use_password` for a Keycloak account that has a second factor.

    BE-3 F3. This is the one rule that makes the `dual` period safe to
    switch on. An emailed code is a single factor. For an identity whose
    credentials still live in Keycloak, the second factor lives there
    too — this service cannot see it, cannot challenge it, and cannot
    honour it. Minting a native session from a code alone would therefore
    take a person who deliberately enabled two-factor authentication and
    silently give them a one-factor way in, on their behalf, without
    telling them.

    Both halves of the condition matter. `legacy_idp` alone is the
    ordinary migrated user, who gets a native session and keeps their
    password (that is the point of the period). `mfa_enabled` alone is a
    native account whose own second factor `MfaService` challenges a few
    lines below. Only together do they describe a factor we can neither
    check nor skip.

    Not an enumeration leak: the caller has already proved possession of
    the mailbox by submitting the right code. This is on `verify`, never
    on `start` — `start` answers 202 for every syntactically valid address
    by construction (docs/api/error-codes.md).
    """
    if not (identity.legacy_idp and identity.mfa_enabled):
        return
    _otp_verify_counter.add(1, {"result": "use_password"})
    raise EmailCodeError(
        "use_password",
        409,
        detail=(
            "your account uses an authenticator app — sign in with your password"
        ),
    )


def _preferred_membership(
    memberships: list[Membership], last_tenant_id: UUID | None
) -> Membership | None:
    """Where a returning sign-in lands: last workspace used, else the first.

    ``list_memberships`` orders personal workspaces first, so the
    fallback for someone who has never chosen is their own space rather
    than whichever team happens to sort earliest.
    """
    if not memberships:
        return None
    if last_tenant_id is not None:
        for m in memberships:
            if m.tenant_id == last_tenant_id:
                return m
    return memberships[0]
