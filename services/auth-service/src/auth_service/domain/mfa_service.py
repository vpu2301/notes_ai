"""Second factors: enrolment, the login challenge, disable, recovery codes.

Three things here are load-bearing and easy to get subtly wrong, so each
is stated once:

**A second factor gates every first factor.** ``challenge_if_required`` is
called by whatever proved the first factor — an email code today, a
password once IDX-A4 lands, anything later — and returns a challenge
instead of a session. No login path can forget it, because none of them
starts a session themselves: they hand the identity to this gate and it
decides. The pack calls this ``AuthOutcome.after_first_factor``.

**A TOTP code is spendable once.** RFC 6238's drift window makes the same
six digits valid across three steps, i.e. for up to 90 seconds. The step
that matched is claimed in the database with a strictly-greater-than
guard, so the second use of a still-valid code is refused.

**The enrolment secret lives in one place.** The pack parks it in the
challenge's ``metadata``; here it goes straight into ``identity_totp``
with ``confirmed_at IS NULL``. One encrypted home instead of two, and an
unconfirmed row gates nothing — so an abandoned enrolment cannot lock
anyone out, which is the property that made the pack keep it out of the
main table in the first place.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from opentelemetry import metrics

from .. import totp
from . import email_code as ec
from . import mfa
from .errors import ApiError
from .identity_repository import (
    Identity,
    IdentityRepository,
    Membership,
    RecoveryCodeRepository,
    SessionRepository,
    TotpRepository,
)
from .session_service import SessionService, StartedSession

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth")
_mfa_verify_counter = _meter.create_counter(
    "mdx_auth_mfa_verify_total",
    description="Second-factor verifications by method and outcome",
    unit="1",
)
_mfa_enrolled_counter = _meter.create_counter(
    "mdx_auth_mfa_enrolled_total",
    description="Second factors confirmed",
    unit="1",
)
_mfa_disabled_counter = _meter.create_counter(
    "mdx_auth_mfa_disabled_total",
    description="Second factors removed, by who removed them",
    unit="1",
)
_recovery_used_counter = _meter.create_counter(
    "mdx_auth_recovery_code_used_total",
    description="Recovery codes spent",
    unit="1",
)

KIND_TOTP_ENROLL = "totp_enroll"
KIND_MFA_LOGIN = "mfa_login"
KIND_REAUTH = "reauth"

ENROLMENT_TTL_SECONDS = 900  # 15 minutes: long enough to install an app.
MFA_LOGIN_TTL_SECONDS = 300  # 5 minutes: the gap between factors.
MFA_LOGIN_MAX_ATTEMPTS = 5


class MfaError(ApiError):
    """A refusal from a second-factor path. See :class:`ApiError`."""


class SecretBox(Protocol):
    """Encrypt/decrypt a TOTP secret at rest. Backed by ``libs/crypto``."""

    async def seal(self, *, secret: str, identity_id: UUID) -> tuple[str, UUID]: ...

    async def open(self, *, sealed: str, identity_id: UUID, kek_tenant_id: UUID) -> str: ...


class Notifier(Protocol):
    """Security mail for the events a person must be told about."""

    async def mfa_enabled(self, *, to: str, lang: str) -> None: ...

    async def mfa_disabled(self, *, to: str, lang: str, by_admin: bool) -> None: ...

    async def recovery_code_used(self, *, to: str, lang: str, remaining: int) -> None: ...


@dataclass(frozen=True, slots=True)
class Enrolment:
    enrollment_id: UUID
    secret: str
    otpauth_uri: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class MfaChallengeIssued:
    """What a passed first factor gets instead of a session."""

    challenge_id: UUID
    methods: list[str]
    expires_in: int


@dataclass(frozen=True, slots=True)
class MfaLoginResult:
    identity: Identity
    membership: Membership
    memberships: list[Membership]
    session: StartedSession
    method: str
    recovery_codes_left: int | None


class MfaService:
    def __init__(
        self,
        *,
        identities: IdentityRepository,
        totp_store: TotpRepository,
        recovery: RecoveryCodeRepository,
        challenges: ec.ChallengeStore,
        sessions: SessionService,
        session_rows: SessionRepository,
        secrets_box: SecretBox,
        notifier: Notifier,
        issuer_label: str,
        lockout: ec.LockoutPolicy,
        clock: Any = None,
    ) -> None:
        self._identities = identities
        self._totp = totp_store
        self._recovery = recovery
        self._challenges = challenges
        self._sessions = sessions
        self._session_rows = session_rows
        self._box = secrets_box
        self._notify = notifier
        self._issuer_label = issuer_label
        self._lockout = lockout
        self._now = clock or (lambda: datetime.now(UTC))

    # ── the first-factor gate (F3) ───────────────────────────────────

    async def challenge_if_required(
        self,
        identity: Identity,
        *,
        membership: Membership,
        client_type: str,
        ip: str,
        user_agent: str,
    ) -> MfaChallengeIssued | None:
        """None ⇒ the caller may start a session. Otherwise, finish here first.

        The challenge carries the *first factor's* context, not the second
        factor's. A code typed on a phone must not silently move the
        session to that phone, or land it in a different workspace than
        the one the sign-in asked for.
        """
        if not identity.mfa_enabled:
            return None
        record = await self._totp.get(identity.id)
        methods = ["totp"] if record is not None and record.confirmed_at is not None else []
        if await self._recovery.count_unused(identity.id) > 0:
            methods.append("recovery_code")
        if not methods:
            # `mfa_enabled` with nothing to verify against would be an
            # account nobody — including its owner — can ever enter.
            # Treat it as not enrolled and let the sign-in through, loudly.
            logger.error(
                "auth.mfa.enabled_without_factors", extra={"identity_id": str(identity.id)}
            )
            await self._identities.set_mfa_enabled(identity.id, enabled=False)
            return None

        challenge_id = uuid4()
        await self._challenges.open(
            challenge_id=challenge_id,
            kind=KIND_MFA_LOGIN,
            email=identity.email,
            identity_id=identity.id,
            # Nothing can match this: an mfa_login challenge is answered by
            # a TOTP or recovery code, never by an emailed one. A random
            # hash keeps the NOT NULL column honest without inventing a
            # second code path that could be brute-forced.
            code_hash=ec.code_hash(secrets.token_hex(32), challenge_id),
            expires_at=self._now() + timedelta(seconds=MFA_LOGIN_TTL_SECONDS),
            max_attempts=MFA_LOGIN_MAX_ATTEMPTS,
            client_type=client_type,
            ip=ip,
            metadata={
                "client_type": client_type,
                "ip": ip,
                "user_agent": user_agent[:512],
                "requested_tenant_id": str(membership.tenant_id),
            },
        )
        logger.info(
            "auth.mfa.challenge_issued",
            extra={"challenge_id": str(challenge_id), "identity_id": str(identity.id)},
        )
        return MfaChallengeIssued(
            challenge_id=challenge_id, methods=methods, expires_in=MFA_LOGIN_TTL_SECONDS
        )

    async def verify_login_challenge(
        self, *, challenge_id: UUID, method: str, code: str
    ) -> MfaLoginResult:
        """Complete the second factor and start the session the first one asked for."""
        challenge = await self._challenges.get(challenge_id)
        if challenge is None or challenge.kind != KIND_MFA_LOGIN:
            _mfa_verify_counter.add(1, {"method": method, "result": "expired"})
            raise MfaError("challenge_expired", 400, detail="that sign-in has expired; start again")
        now = self._now()
        if challenge.consumed_at is not None:
            _mfa_verify_counter.add(1, {"method": method, "result": "consumed"})
            raise MfaError("challenge_consumed", 400, detail="that sign-in is already finished")
        if now >= challenge.expires_at:
            _mfa_verify_counter.add(1, {"method": method, "result": "expired"})
            raise MfaError("challenge_expired", 400, detail="that sign-in has expired; start again")
        if challenge.attempts >= challenge.max_attempts:
            await self._challenges.consume(challenge.id)
            _mfa_verify_counter.add(1, {"method": method, "result": "exhausted"})
            raise MfaError("too_many_attempts", 429, detail="too many attempts; start again")

        assert challenge.identity_id is not None
        identity = await self._identities.get(challenge.identity_id)
        if identity is None:
            raise MfaError("challenge_expired", 400, detail="that sign-in has expired")

        ok, remaining = await self._check_factor(identity, method=method, code=code)
        if not ok:
            attempts = challenge.attempts + 1
            await self._challenges.record_attempt(challenge.id, attempts=attempts)
            left = challenge.max_attempts - attempts
            if left <= 0:
                await self._challenges.consume(challenge.id)
                # An exhausted second factor is a failed sign-in for the
                # A3 lockout counter — otherwise MFA would be a way to
                # guess at an account without ever tripping the lock.
                await self._identities.register_failure(identity.id, policy=self._lockout, now=now)
                _mfa_verify_counter.add(1, {"method": method, "result": "exhausted"})
                raise MfaError("too_many_attempts", 429, detail="too many attempts; start again")
            _mfa_verify_counter.add(1, {"method": method, "result": "invalid"})
            raise MfaError(
                "code_invalid",
                400,
                detail="that code is not right",
                extras={"attempts_left": left},
            )

        if not await self._challenges.consume(challenge.id):
            _mfa_verify_counter.add(1, {"method": method, "result": "consumed"})
            raise MfaError("challenge_consumed", 400, detail="that sign-in is already finished")

        memberships = await self._identities.list_memberships(identity.id)
        requested = challenge.metadata.get("requested_tenant_id")
        membership = next(
            (m for m in memberships if str(m.tenant_id) == requested),
            memberships[0] if memberships else None,
        )
        if membership is None:
            raise MfaError(
                "no_workspace", 409, detail="this account is not a member of any workspace"
            )

        session = await self._sessions.start(
            identity=identity,
            membership=membership,
            client_type=str(challenge.metadata.get("client_type") or "web"),
            ip=str(challenge.metadata.get("ip") or ""),
            user_agent=str(challenge.metadata.get("user_agent") or ""),
            mfa=True,
        )
        await self._identities.note_successful_login(identity.id, tenant_id=membership.tenant_id)
        _mfa_verify_counter.add(1, {"method": method, "result": "ok"})
        return MfaLoginResult(
            identity=identity,
            membership=membership,
            memberships=memberships,
            session=session,
            method=method,
            recovery_codes_left=remaining,
        )

    # ── factor checking, shared by login / disable / reauth ──────────

    async def _check_factor(
        self, identity: Identity, *, method: str, code: str
    ) -> tuple[bool, int | None]:
        """``(accepted, recovery_codes_left)``. Spends the factor on success."""
        if method == mfa.MfaMethod.TOTP:
            record = await self._totp.get(identity.id)
            if record is None or record.confirmed_at is None:
                return False, None
            secret = await self._box.open(
                sealed=record.secret_enc,
                identity_id=identity.id,
                kek_tenant_id=record.kek_tenant_id,
            )
            decision = mfa.decide_step(totp.matching_step(secret, code), record.last_used_step)
            if not decision.accepted or decision.step is None:
                if decision.reason == "code_replayed":
                    logger.warning(
                        "auth.mfa.code_replayed", extra={"identity_id": str(identity.id)}
                    )
                return False, None
            # The claim is the real check: two requests with the same code
            # race here, and only one UPDATE finds a smaller stored step.
            if not await self._totp.spend_step(identity.id, step=decision.step):
                logger.warning("auth.mfa.step_race_lost", extra={"identity_id": str(identity.id)})
                return False, None
            return True, None

        if method == mfa.MfaMethod.RECOVERY_CODE:
            digest = mfa.recovery_code_hash(code)
            if not await self._recovery.consume(identity.id, code_hash=digest):
                return False, None
            remaining = await self._recovery.count_unused(identity.id)
            _recovery_used_counter.add(1)
            logger.info(
                "auth.mfa.recovery_code_used",
                extra={"identity_id": str(identity.id), "remaining": remaining},
            )
            await self._safe_notify(
                self._notify.recovery_code_used(
                    to=identity.email, lang=identity_lang(identity), remaining=remaining
                )
            )
            return True, remaining

        raise MfaError("method_unsupported", 400, detail=f"unknown method {method!r}")

    async def verify_factor(self, identity: Identity, *, method: str, code: str) -> bool:
        """Public wrapper for the step-up and disable paths."""
        ok, _ = await self._check_factor(identity, method=method, code=code)
        return ok

    # ── enrolment ────────────────────────────────────────────────────

    async def start_enrolment(self, identity: Identity) -> Enrolment:
        if identity.mfa_enabled:
            raise MfaError("mfa_already_enabled", 409, detail="a second factor is already set up")
        secret = totp.generate_secret()
        sealed, kek_tenant_id = await self._box.seal(secret=secret, identity_id=identity.id)
        await self._totp.put_candidate(identity.id, secret_enc=sealed, kek_tenant_id=kek_tenant_id)
        enrollment_id = uuid4()
        await self._challenges.open(
            challenge_id=enrollment_id,
            kind=KIND_TOTP_ENROLL,
            email=identity.email,
            identity_id=identity.id,
            code_hash=ec.code_hash(secrets.token_hex(32), enrollment_id),
            expires_at=self._now() + timedelta(seconds=ENROLMENT_TTL_SECONDS),
            max_attempts=MFA_LOGIN_MAX_ATTEMPTS,
            client_type="",
            ip="",
        )
        return Enrolment(
            enrollment_id=enrollment_id,
            secret=secret,
            otpauth_uri=totp.provisioning_uri(
                secret, account=identity.email, issuer=self._issuer_label
            ),
            expires_in=ENROLMENT_TTL_SECONDS,
        )

    async def confirm_enrolment(
        self, identity: Identity, *, enrollment_id: UUID, code: str
    ) -> list[str]:
        """A valid code turns the candidate into a factor and returns recovery codes."""
        challenge = await self._challenges.get(enrollment_id)
        if (
            challenge is None
            or challenge.kind != KIND_TOTP_ENROLL
            or challenge.identity_id != identity.id
        ):
            raise MfaError("challenge_expired", 400, detail="that enrolment has expired")
        if challenge.consumed_at is not None or self._now() >= challenge.expires_at:
            raise MfaError("challenge_expired", 400, detail="that enrolment has expired")

        record = await self._totp.get(identity.id)
        if record is None or record.confirmed_at is not None:
            raise MfaError("challenge_expired", 400, detail="that enrolment has expired")

        secret = await self._box.open(
            sealed=record.secret_enc,
            identity_id=identity.id,
            kek_tenant_id=record.kek_tenant_id,
        )
        step = totp.matching_step(secret, code)
        if step is None:
            attempts = challenge.attempts + 1
            await self._challenges.record_attempt(enrollment_id, attempts=attempts)
            if attempts >= challenge.max_attempts:
                await self._challenges.consume(enrollment_id)
                await self._totp.delete(identity.id)
                raise MfaError("too_many_attempts", 429, detail="too many attempts; start again")
            raise MfaError(
                "code_invalid",
                400,
                detail="that code is not right",
                extras={"attempts_left": challenge.max_attempts - attempts},
            )

        if not await self._totp.confirm(identity.id, step=step):
            raise MfaError("challenge_expired", 400, detail="that enrolment has expired")
        await self._challenges.consume(enrollment_id)
        await self._identities.set_mfa_enabled(identity.id, enabled=True)
        codes = await self._issue_recovery_codes(identity)
        _mfa_enrolled_counter.add(1)
        await self._safe_notify(
            self._notify.mfa_enabled(to=identity.email, lang=identity_lang(identity))
        )
        return codes

    async def disable(
        self, identity: Identity, *, method: str, code: str, by_admin: bool = False
    ) -> None:
        """Remove the second factor. A user must prove one; an admin may not need to."""
        if not identity.mfa_enabled:
            raise MfaError("mfa_not_enabled", 409, detail="no second factor is set up")
        if not by_admin and not await self.verify_factor(identity, method=method, code=code):
            raise MfaError("code_invalid", 400, detail="that code is not right")
        await self._totp.delete(identity.id)
        await self._recovery.delete_all(identity.id)
        await self._identities.set_mfa_enabled(identity.id, enabled=False)
        _mfa_disabled_counter.add(1, {"by": "admin" if by_admin else "user"})
        await self._safe_notify(
            self._notify.mfa_disabled(
                to=identity.email, lang=identity_lang(identity), by_admin=by_admin
            )
        )

    async def regenerate_recovery_codes(self, identity: Identity) -> list[str]:
        if not identity.mfa_enabled:
            raise MfaError("mfa_not_enabled", 409, detail="no second factor is set up")
        return await self._issue_recovery_codes(identity)

    async def _issue_recovery_codes(self, identity: Identity) -> list[str]:
        codes = mfa.generate_recovery_codes()
        await self._recovery.replace_all(
            identity.id, hashes=[mfa.recovery_code_hash(c) for c in codes]
        )
        return codes

    async def _safe_notify(self, coro: Any) -> bool:
        """Security mail is best-effort. The operation it describes already happened.

        Failing the disable because the notice could not be sent would
        leave the account in the state the user was trying to leave, which
        is the worse of the two outcomes.
        """
        try:
            await coro
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("auth.mfa.notify_failed", extra={"error_class": type(exc).__name__})
            return False


def identity_lang(identity: Identity) -> str:
    from . import copy as copy_mod

    return copy_mod.normalise_lang(identity.locale)
