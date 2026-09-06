"""The account surface: sessions, step-up, email change, deletion (IDX-A5).

What ties these four together is that each of them can take an account
away from its owner. So each is gated on a recent proof of identity, and
each tells somebody about it afterwards — the person who can still act if
it was not them.

**Step-up ("recent auth").** A live access token proves that somebody was
this person at some point. Changing the login address or deleting the
account needs more than that: an unlocked laptop must not be enough. The
proof is ``auth_sessions.last_authenticated_at``, stamped by any first
factor and by ``/auth/reauth``, and the gate is a window measured from
it. IDX-A4 adds a password to the list of things that can re-stamp it.

**Email change is two-sided.** The new address must prove it can receive
mail before it becomes the login; the old address then gets a one-shot
link that restores it and ends every session. That link is the entire
defence against an attacker who has a session and quietly moves the
account to their own mailbox — so it is long-lived (24 h) and destructive
on purpose.

**Deletion is reversible until it isn't.** Requesting it dissolves the
workspaces nobody else is in and signs the person out everywhere, but
destroys nothing: signing in during the grace window puts everything
back (IDX-A3 F3). The purge, thirty days later, is the irreversible half
and lives in a script an operator runs.
"""

from __future__ import annotations

import ipaddress
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from opentelemetry import metrics

from . import email_code as ec
from . import mfa
from .errors import ApiError
from .identity_repository import (
    Identity,
    IdentityRepository,
    Membership,
    SessionRepository,
    SessionRow,
)

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth")
_email_change_counter = _meter.create_counter(
    "mdx_auth_email_change_total",
    description="Email-change flow by stage",
    unit="1",
)
_account_delete_counter = _meter.create_counter(
    "mdx_auth_account_delete_total",
    description="Account deletion by stage",
    unit="1",
)
_sessions_revoked_counter = _meter.create_counter(
    "mdx_auth_sessions_revoked_total",
    description="Sessions ended, by reason",
    unit="1",
)
# The other half of revocation. The database row stops the next refresh;
# this counts the times the access token already in someone's hands could
# NOT be stopped, which is the window revocation exists to close — hence
# a critical alert rather than a log line nobody reads.
_denylist_failed_counter = _meter.create_counter(
    "mdx_auth_denylist_push_failed_total",
    description="Revocations that failed to reach the session denylist",
    unit="1",
)

KIND_EMAIL_CHANGE = "email_change"
KIND_REAUTH = "reauth"

EMAIL_CHANGE_TTL_SECONDS = 900
REVERT_TTL_SECONDS = 86_400  # 24 h — see the module docstring.
REAUTH_TTL_SECONDS = 600
DELETION_GRACE_DAYS = 30


class AccountError(ApiError):
    """A refusal from the account surface. See :class:`ApiError`."""


class AccountNotifier(Protocol):
    async def email_changed(
        self, *, to_old: str, lang: str, new_email: str, token: str, ttl_seconds: int
    ) -> None: ...

    async def account_deletion_scheduled(
        self, *, to: str, lang: str, purge_on: datetime
    ) -> None: ...


class Denylist(Protocol):
    async def revoke_sid(self, sid: str, *, ttl_seconds: int) -> None: ...


class CodeSender(Protocol):
    """Sends a six-digit code to an address (the IDX-A3 mailer)."""

    async def send_code(
        self, *, to: str, lang: str, code: str, ttl_seconds: int, user_agent: str
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class SessionView:
    sid: UUID
    client_type: str
    device_name: str
    user_agent: str
    ip_last: str
    created_at: datetime
    last_used_at: datetime
    last_authenticated_at: datetime
    current: bool


@dataclass(frozen=True, slots=True)
class ReauthOptions:
    methods: list[str]
    challenge_id: UUID | None
    expires_in: int


def mask_ip(raw: str) -> str:
    """``203.0.113.7`` → ``203.0.113.0/24``; IPv6 → ``/48``.

    The sessions list exists so somebody can spot a login they do not
    recognise, and a network is enough for that — "somewhere else in the
    world" reads the same as a full address. Storing precision we then
    show back turns a security screen into a location history, which is
    worth something to whoever gets into the account.
    """
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return ""
    if isinstance(addr, ipaddress.IPv4Address):
        return str(ipaddress.ip_network(f"{addr}/24", strict=False))
    return str(ipaddress.ip_network(f"{addr}/48", strict=False))


def revert_token(challenge_id: UUID, secret: str) -> str:
    """``<challenge id>.<secret>`` — the whole credential in one URL segment.

    The id alone is not enough to use the link (the secret is checked
    against the stored hash) and the secret alone cannot be looked up.
    An attacker needs both, and neither is ever logged.
    """
    return f"{challenge_id.hex}.{secret}"


def parse_revert_token(token: str) -> tuple[UUID, str] | None:
    head, _, secret = (token or "").partition(".")
    if not secret:
        return None
    try:
        return UUID(hex=head), secret
    except ValueError:
        return None


class AccountService:
    def __init__(
        self,
        *,
        identities: IdentityRepository,
        sessions: SessionRepository,
        challenges: ec.ChallengeStore,
        notifier: AccountNotifier,
        code_sender: CodeSender,
        denylist: Denylist | None,
        revoked_ttl_seconds: int,
        reauth_window_seconds: int,
        mfa_service: Any = None,
        clock: Any = None,
    ) -> None:
        self._identities = identities
        self._sessions = sessions
        self._challenges = challenges
        self._notify = notifier
        self._code_sender = code_sender
        self._denylist = denylist
        self._revoked_ttl = revoked_ttl_seconds
        self._reauth_window = reauth_window_seconds
        self._mfa = mfa_service
        self._now = clock or (lambda: datetime.now(UTC))

    # ── step-up ──────────────────────────────────────────────────────

    async def require_recent_auth(self, *, session_id: UUID) -> None:
        """Raise unless this session proved itself inside the window."""
        row = await self._sessions.get(session_id)
        if row is None or row.revoked_at is not None:
            raise AccountError("session_revoked", 401, detail="this session has ended")
        age = (self._now() - row.last_authenticated_at).total_seconds()
        if age > self._reauth_window:
            raise AccountError(
                "reauth_required",
                403,
                detail="confirm it is you before making this change",
                extras={"reauth_window_seconds": self._reauth_window},
            )

    async def start_reauth(self, identity: Identity, *, lang: str) -> ReauthOptions:
        """Offer the ways this person can prove themselves right now.

        An MFA user answers with their authenticator; everyone else gets a
        code mailed to the address on the account. Until IDX-A4 there is
        no password, so that is the complete list.
        """
        if identity.mfa_enabled:
            return ReauthOptions(
                methods=[mfa.MfaMethod.TOTP, mfa.MfaMethod.RECOVERY_CODE],
                challenge_id=None,
                expires_in=0,
            )
        challenge_id = uuid4()
        code = ec.generate_code()
        await self._challenges.open(
            challenge_id=challenge_id,
            kind=KIND_REAUTH,
            email=identity.email,
            identity_id=identity.id,
            code_hash=ec.code_hash(code, challenge_id),
            expires_at=self._now() + timedelta(seconds=REAUTH_TTL_SECONDS),
            max_attempts=5,
            client_type="",
            ip="",
        )
        await self._code_sender.send_code(
            to=identity.email,
            lang=lang,
            code=code,
            ttl_seconds=REAUTH_TTL_SECONDS,
            user_agent="",
        )
        return ReauthOptions(
            methods=[mfa.MfaMethod.EMAIL_CODE],
            challenge_id=challenge_id,
            expires_in=REAUTH_TTL_SECONDS,
        )

    async def complete_reauth(
        self,
        identity: Identity,
        *,
        session_id: UUID,
        method: str,
        code: str,
        challenge_id: UUID | None,
    ) -> None:
        if method == mfa.MfaMethod.EMAIL_CODE:
            if challenge_id is None:
                raise AccountError("challenge_required", 400, detail="start the check first")
            await self._spend_code_challenge(
                challenge_id, kind=KIND_REAUTH, identity=identity, code=code
            )
        else:
            if self._mfa is None or not await self._mfa.verify_factor(
                identity, method=method, code=code
            ):
                raise AccountError("code_invalid", 400, detail="that code is not right")
        await self._sessions.touch_authenticated(session_id)
        logger.info("auth.reauth.ok", extra={"identity_id": str(identity.id), "method": method})

    async def _spend_code_challenge(
        self, challenge_id: UUID, *, kind: str, identity: Identity, code: str
    ) -> ec.Challenge:
        """Verify and consume an emailed-code challenge of a given kind."""
        challenge = await self._challenges.get(challenge_id)
        if challenge is None or challenge.kind != kind or challenge.identity_id != identity.id:
            raise AccountError("challenge_expired", 400, detail="that code has expired")
        decision = ec.evaluate(challenge, code, now=self._now())
        if decision.outcome is ec.VerifyOutcome.OK:
            if not await self._challenges.consume(challenge.id):
                raise AccountError(
                    "challenge_consumed", 400, detail="that code has already been used"
                )
            return challenge
        if decision.consume:
            await self._challenges.consume(challenge.id)
        elif decision.attempts_after != challenge.attempts:
            await self._challenges.record_attempt(challenge.id, attempts=decision.attempts_after)
        if decision.outcome is ec.VerifyOutcome.CONSUMED:
            raise AccountError("challenge_consumed", 400, detail="that code has already been used")
        if decision.outcome is ec.VerifyOutcome.EXPIRED:
            raise AccountError("challenge_expired", 400, detail="that code has expired")
        if decision.outcome is ec.VerifyOutcome.EXHAUSTED:
            raise AccountError("too_many_attempts", 429, detail="too many wrong codes")
        raise AccountError(
            "code_invalid",
            400,
            detail="that code is not right",
            extras={"attempts_left": decision.attempts_left},
        )

    # ── sessions (F4) ────────────────────────────────────────────────

    async def list_sessions(self, identity: Identity, *, current_sid: UUID) -> list[SessionView]:
        rows = await self._sessions.list_live(identity.id)
        return [
            SessionView(
                sid=r.id,
                client_type=r.client_type,
                device_name=r.device_name,
                user_agent=r.user_agent,
                ip_last=mask_ip(r.ip),
                created_at=r.created_at,
                last_used_at=r.last_used_at,
                last_authenticated_at=r.last_authenticated_at,
                current=r.id == current_sid,
            )
            for r in rows
        ]

    async def revoke_session(
        self, identity: Identity, *, session_id: UUID, reason: str = "user_revoked"
    ) -> None:
        """End one session. 404 for a sid that is not this identity's.

        404 rather than 403: answering "forbidden" would confirm that the
        sid exists and belongs to somebody, which is a probe worth nothing
        to the owner and something to an attacker.
        """
        if not await self._sessions.revoke(session_id, identity_id=identity.id, reason=reason):
            raise AccountError("not_found", 404, detail="no such session")
        await self._push_denylist([session_id])
        _sessions_revoked_counter.add(1, {"reason": reason})

    async def revoke_other_sessions(
        self, identity: Identity, *, current_sid: UUID | None, reason: str
    ) -> int:
        revoked = await self._sessions.revoke_all(
            identity.id, reason=reason, except_session_id=current_sid
        )
        await self._push_denylist(revoked)
        _sessions_revoked_counter.add(len(revoked), {"reason": reason})
        return len(revoked)

    async def _push_denylist(self, sids: list[UUID]) -> None:
        """Stop the access tokens already issued for these sessions.

        Best-effort by design (ADR-0040): the database row is the durable
        half and already stops the next refresh. A Redis outage shortens
        the guarantee to "within the access-token lifetime", which is the
        documented degraded mode, not a failure of the request.
        """
        if self._denylist is None:
            return
        for sid in sids:
            try:
                await self._denylist.revoke_sid(str(sid), ttl_seconds=self._revoked_ttl)
            except Exception as exc:  # noqa: BLE001
                _denylist_failed_counter.add(1, {"key": "sid"})
                logger.warning(
                    "auth.session.denylist_push_failed",
                    extra={"sid": str(sid), "error_class": type(exc).__name__},
                )

    # ── email change (F5) ────────────────────────────────────────────

    async def start_email_change(
        self, identity: Identity, *, new_email: str, lang: str, user_agent: str
    ) -> UUID:
        address = ec.normalise_email(new_email)
        if address == identity.email:
            raise AccountError("email_unchanged", 400, detail="that is already your address")
        if not _looks_like_email(address):
            raise AccountError(
                "invalid_email", 400, detail="that does not look like an email address"
            )
        # Revealing that an address is taken is acceptable here and nowhere
        # else: the caller is already authenticated, so this is not an
        # enumeration oracle — and without it the flow would silently fail
        # at confirm time with nothing the user could act on.
        if await self._identities.email_is_taken(address, excluding=identity.id):
            raise AccountError("email_in_use", 409, detail="that address is already in use")

        await self._challenges.consume_open_for_email(kind=KIND_EMAIL_CHANGE, email=address)
        challenge_id = uuid4()
        code = ec.generate_code()
        await self._challenges.open(
            challenge_id=challenge_id,
            kind=KIND_EMAIL_CHANGE,
            email=address,
            identity_id=identity.id,
            code_hash=ec.code_hash(code, challenge_id),
            expires_at=self._now() + timedelta(seconds=EMAIL_CHANGE_TTL_SECONDS),
            max_attempts=5,
            client_type="",
            ip="",
            metadata={"old_email": identity.email, "stage": "confirm"},
        )
        # To the NEW address: the point of the code is to prove that
        # mailbox is reachable before it becomes the way in.
        await self._code_sender.send_code(
            to=address,
            lang=lang,
            code=code,
            ttl_seconds=EMAIL_CHANGE_TTL_SECONDS,
            user_agent=user_agent,
        )
        _email_change_counter.add(1, {"stage": "requested"})
        return challenge_id

    async def confirm_email_change(
        self, identity: Identity, *, challenge_id: UUID, code: str, lang: str
    ) -> tuple[Identity, bool]:
        """Switch the address and arm the old one's undo. ``(identity, notified)``."""
        challenge = await self._spend_code_challenge(
            challenge_id, kind=KIND_EMAIL_CHANGE, identity=identity, code=code
        )
        old_email = str(challenge.metadata.get("old_email") or identity.email)
        new_email = challenge.email

        if await self._identities.email_is_taken(new_email, excluding=identity.id):
            # Someone claimed it between start and confirm.
            raise AccountError("email_in_use", 409, detail="that address is already in use")

        updated = await self._identities.change_email(identity.id, new_email=new_email)
        if updated is None:
            raise AccountError("not_found", 404, detail="no such account")

        # Sessions deliberately survive: the person is standing at their
        # own screen and has just proved the new mailbox. What they get
        # instead is the undo below, aimed at the address that lost access.
        token_secret = secrets.token_urlsafe(32)
        revert_id = uuid4()
        await self._challenges.open(
            challenge_id=revert_id,
            kind=KIND_EMAIL_CHANGE,
            email=old_email,
            identity_id=identity.id,
            code_hash=ec.code_hash(token_secret, revert_id),
            expires_at=self._now() + timedelta(seconds=REVERT_TTL_SECONDS),
            max_attempts=5,
            client_type="",
            ip="",
            metadata={"stage": "revert", "revert_to": old_email, "changed_to": new_email},
        )
        notified = True
        try:
            await self._notify.email_changed(
                to_old=old_email,
                lang=lang,
                new_email=new_email,
                token=revert_token(revert_id, token_secret),
                ttl_seconds=REVERT_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            notified = False
            logger.error(
                "auth.email_change.notice_failed",
                extra={"identity_id": str(identity.id), "error_class": type(exc).__name__},
            )
        _email_change_counter.add(1, {"stage": "confirmed"})
        return updated, notified

    async def revert_email(self, token: str) -> Identity:
        """The "this wasn't me" link: restore the address, end everything."""
        parsed = parse_revert_token(token)
        if parsed is None:
            raise AccountError("not_found", 404, detail="that link is not valid")
        challenge_id, secret = parsed
        challenge = await self._challenges.get(challenge_id)
        if (
            challenge is None
            or challenge.kind != KIND_EMAIL_CHANGE
            or challenge.metadata.get("stage") != "revert"
            or challenge.identity_id is None
        ):
            raise AccountError("not_found", 404, detail="that link is not valid")
        # Checked by hand rather than through `ec.evaluate`, which
        # normalises a submission to digits — right for a six-digit code,
        # wrong for a urlsafe token. Same comparison, same binding to the
        # challenge id; every failure answers 404 so the link reveals
        # nothing about which part of it was wrong.
        if challenge.consumed_at is not None or self._now() >= challenge.expires_at:
            raise AccountError("not_found", 404, detail="that link has expired")
        if not ec.hashes_match(challenge.code_hash, ec.code_hash(secret, challenge_id)):
            raise AccountError("not_found", 404, detail="that link is not valid")

        if not await self._challenges.consume(challenge_id):
            raise AccountError("not_found", 404, detail="that link has already been used")

        restore_to = str(challenge.metadata.get("revert_to") or "")
        identity = await self._identities.get(challenge.identity_id)
        if identity is None or not restore_to:
            raise AccountError("not_found", 404, detail="that link is not valid")
        if await self._identities.email_is_taken(restore_to, excluding=identity.id):
            raise AccountError("email_in_use", 409, detail="that address has since been taken")

        updated = await self._identities.change_email(identity.id, new_email=restore_to)
        # Everything, including whoever made the change: they are the
        # suspected attacker, and this is the one flow that assumes so.
        await self.revoke_other_sessions(identity, current_sid=None, reason="email_reverted")
        _email_change_counter.add(1, {"stage": "reverted"})
        logger.warning("auth.email_change.reverted", extra={"identity_id": str(identity.id)})
        assert updated is not None
        return updated

    # ── deletion (F6) ────────────────────────────────────────────────

    async def request_deletion(
        self, identity: Identity, *, lang: str
    ) -> tuple[datetime, list[UUID], bool]:
        """``(purge_after, dissolved_tenant_ids, notified)``."""
        blocking = await self._identities.sole_owner_tenants_with_members(identity.id)
        if blocking:
            _account_delete_counter.add(1, {"stage": "refused"})
            raise AccountError(
                "sole_owner_with_members",
                409,
                detail="hand these workspaces to another owner first",
                extras={
                    "tenants": [{"tenant_id": str(m.tenant_id), "name": m.name} for m in blocking]
                },
            )
        dissolved = await self._identities.request_deletion(identity.id)
        purge_after = self._now() + timedelta(days=DELETION_GRACE_DAYS)
        # Every session, the caller's included: the account is on its way
        # out and leaving a live token behind would let it keep acting.
        await self.revoke_other_sessions(identity, current_sid=None, reason="account_deleted")
        notified = True
        try:
            await self._notify.account_deletion_scheduled(
                to=identity.email, lang=lang, purge_on=purge_after
            )
        except Exception as exc:  # noqa: BLE001
            notified = False
            logger.error(
                "auth.account_delete.notice_failed",
                extra={"identity_id": str(identity.id), "error_class": type(exc).__name__},
            )
        _account_delete_counter.add(1, {"stage": "requested"})
        return purge_after, dissolved, notified


def _looks_like_email(value: str) -> bool:
    from . import compose

    return compose.looks_like_email(value)


__all__ = [
    "AccountError",
    "AccountService",
    "Membership",
    "ReauthOptions",
    "SessionRow",
    "SessionView",
    "mask_ip",
    "parse_revert_token",
    "revert_token",
]
