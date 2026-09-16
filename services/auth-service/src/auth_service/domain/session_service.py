"""Native sessions: start, rotate, end.

IDX-A2 specifies a ``SessionService`` with ``start``/``refresh``/
``switch_tenant``/``revoke``. IDX-A3 carried ``start`` alone, because
that was all a completed email-code verify called. IDX-M1 adds
``refresh`` and ``revoke``: a refresh token kept in a Mac's Keychain is
worth keeping only if the server can rotate it, and without rotation a
native session died one access-token lifetime after it began.

IDX-M2 adds ``switch_tenant``, the last of the four: a Mac with a
workspace switcher needs a token scoped to the workspace it switches to,
and `POST /tenants/{id}/switch` (sprint 16) is only an authorization gate
— its own docstring says the client must "re-authenticate to obtain a
token scoped to this tenant".

What ``start`` guarantees:

* a **new** ``sid`` every time (F: no session fixation — a session id
  that existed before authentication is a session id an attacker could
  have planted);
* the refresh token is generated here, returned once, and only its
  sha256 is stored, exactly like the password-reset token;
* the ``roles`` claim comes from the membership, never from the request.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .errors import ApiError
from .identity_repository import (
    Identity,
    IdentityRepository,
    Membership,
    SessionRepository,
    platform_roles_for,
)
from .token_service import TokenService

# 32 bytes of CSPRNG. The refresh token is a bearer credential with a
# month-long life; 256 bits is not where its risk lives.
logger = logging.getLogger(__name__)

_REFRESH_TOKEN_BYTES = 32

# BE-2 / ADR-0047. During the `dual` period one endpoint serves two kinds
# of refresh token, and it has to tell them apart from the value alone —
# the cookie name is the same for both (deliberately: changing it would
# need a release of every client for a period measured in weeks).
#
# A prefix rather than a length or a charset test, because the two token
# families are otherwise indistinguishable by inspection and a heuristic
# that is wrong once logs somebody out.
NATIVE_REFRESH_PREFIX = "nrt_"


def new_refresh_token() -> str:
    """A native refresh token: the prefix, then 32 random bytes, url-safe."""
    return f"{NATIVE_REFRESH_PREFIX}{secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)}"


def is_native_refresh_token(value: str) -> bool:
    """Does this refresh token belong to THIS service's session store?

    Three cases, in the order they are decided:

    1. The `nrt_` prefix — native, by construction.
    2. The JWT shape (three dot-separated segments) — Keycloak's. Its
       refresh tokens are signed JWTs; ours are opaque and never contain
       a dot, because `token_urlsafe` emits only `[A-Za-z0-9_-]`.
    3. Anything else — native. This is the pre-prefix opaque token. No
       deployment has run in native mode, so in practice there are none;
       the branch exists so that if one does turn up it is routed to the
       store that could possibly know about it, rather than proxied to
       Keycloak, which would answer 400 and end a valid session.
    """
    if value.startswith(NATIVE_REFRESH_PREFIX):
        return True
    return value.count(".") != 2

# Enough of a user agent to recognise your own laptop in the sessions
# list. Deliberately crude: this is a display label, never a check.
_DEVICE_HINTS: tuple[tuple[str, str], ...] = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Macintosh", "Mac"),
    ("Mac OS X", "Mac"),
    ("Windows", "Windows PC"),
    ("Android", "Android device"),
    ("Linux", "Linux"),
)


def device_name(user_agent: str) -> str:
    """A short, human label for the sessions screen ("Mac", "iPhone")."""
    for needle, label in _DEVICE_HINTS:
        if needle in user_agent:
            return label
    return ""


@dataclass(frozen=True, slots=True)
class StartedSession:
    session_id: UUID
    tenant_id: UUID
    roles: list[str]
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshedSession:
    """What a rotation hands back. Same shape ``start`` returns, minus the
    fields a caller can only learn at sign-in."""

    session_id: UUID
    identity_id: UUID
    tenant_id: UUID
    roles: list[str]
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


@dataclass(frozen=True, slots=True)
class SwitchedToken:
    """An access token for one of the identity's other workspaces.

    No refresh token: switching does not rotate anything. The session is
    the same session — it is only pointed somewhere else — and handing
    back a second refresh token would give the client two credentials for
    one session and a replay the next time it used the older one.
    """

    tenant_id: UUID
    roles: list[str]
    access_token: str
    expires_in: int
    activated: bool


@dataclass(frozen=True, slots=True)
class EndedSession:
    """The session a logout closed, for the audit trail and the denylist."""

    session_id: UUID
    identity_id: UUID
    tenant_id: UUID


class RefreshReplayError(ApiError):
    """The same refresh token, twice, outside the grace window.

    Carries the session it belongs to because the router has to revoke
    more than this one session: a replayed token means the chain may be
    in hostile hands, so every access token of the identity is denylisted
    too. Deciding that here would put half the response in the service
    and half in the route.
    """

    def __init__(self, *, session_id: UUID, identity_id: UUID, tenant_id: UUID) -> None:
        super().__init__(
            "auth_refresh_replay",
            401,
            detail="refresh token is no longer valid",
        )
        self.session_id = session_id
        self.identity_id = identity_id
        self.tenant_id = tenant_id


def session_expired() -> ApiError:
    """No usable session behind this token — expired, revoked, or never real.

    One code for all three on purpose: which of them it was is a fact
    about somebody else's account, and the client does the same thing in
    every case.
    """
    return ApiError("session_expired", 401, detail="session is no longer valid")


class SessionService:
    def __init__(
        self,
        *,
        tokens: TokenService,
        sessions: SessionRepository,
        refresh_ttl_seconds: int,
        identities: IdentityRepository | None = None,
        absolute_ttl_seconds: int | None = None,
        grace_seconds: int = 30,
    ) -> None:
        if refresh_ttl_seconds <= 0:
            raise ValueError("refresh_ttl_seconds must be positive")
        if absolute_ttl_seconds is not None and absolute_ttl_seconds < refresh_ttl_seconds:
            raise ValueError("absolute_ttl_seconds must not be shorter than refresh_ttl_seconds")
        self._tokens = tokens
        self._sessions = sessions
        # Only ``refresh`` needs these; ``start`` is handed its identity and
        # membership by the route that already checked them.
        self._identities = identities
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._absolute_ttl_seconds = absolute_ttl_seconds
        self._grace_seconds = grace_seconds

    async def _heal_workspace(self, identity: Identity) -> Membership | None:
        """Re-create the personal workspace for an identity that has none.

        Delegates to the repository so the transaction — tenant,
        membership and the bridge ``users`` row together — lives in one
        place and cannot be half-applied. Returns ``None`` when there is
        no repository wired (``start``-only deployments) or the identity
        turned out to have a membership after all.
        """
        if self._identities is None:
            return None
        try:
            return await self._identities.ensure_personal_workspace(
                identity.id, identity.email
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "auth.session.workspace_heal_failed",
                extra={"identity_id": str(identity.id)},
            )
            return None

    async def start(
        self,
        *,
        identity: Identity,
        membership: Membership,
        client_type: str,
        ip: str,
        user_agent: str,
        mfa: bool = False,
    ) -> StartedSession:
        """Open a session in ``membership.tenant_id`` and mint its first token.

        The caller is responsible for having checked that the membership
        belongs to the identity and is active; this signs what it is
        given. That split keeps the "which workspace may this person
        enter" decision in one place (the route) rather than half here.
        """
        refresh_token = new_refresh_token()
        session_id, expires_at = await self._sessions.create(
            identity_id=identity.id,
            tenant_id=membership.tenant_id,
            refresh_token=refresh_token,
            ttl_seconds=self._refresh_ttl_seconds,
            client_type=client_type,
            ip=ip,
            user_agent=user_agent,
            mfa=mfa,
            device_name=device_name(user_agent),
        )
        roles = platform_roles_for(membership.role, tenant_kind=membership.kind)
        minted = self._tokens.mint(
            identity_id=identity.id,
            session_id=str(session_id),
            tenant_id=membership.tenant_id,
            roles=roles,
            mfa=mfa,
            mfa_enrolled=identity.mfa_enabled,
            email=identity.email,
            name=identity.display_name or None,
        )
        return StartedSession(
            session_id=session_id,
            tenant_id=membership.tenant_id,
            roles=roles,
            access_token=minted.token,
            expires_in=minted.expires_in,
            refresh_token=refresh_token,
            refresh_expires_in=self._refresh_ttl_seconds,
            expires_at=expires_at,
        )

    # ── rotation (IDX-A2 F2, carried by IDX-M1) ──────────────────────────

    async def refresh(
        self,
        *,
        refresh_token: str,
        ip: str = "",
    ) -> RefreshedSession:
        """Exchange a refresh token for the next one and a fresh access token.

        The order of the checks is the contract:

        1. resolve the token to a session — and to which *generation* of
           that session's token it is;
        2. a retired token past its grace is a replay, and the session
           dies before anything else happens;
        3. roles are re-read from the membership, never carried over from
           the expiring token. A session that outlives someone's admin
           rights must not keep minting admin tokens for thirty days.

        A rotation that loses its race (two requests, one token) re-reads
        and tries again once: by then the token it presented is the
        retired one, so the second caller comes out through the grace
        path with a token of its own rather than a 401 it did not earn.
        """
        if self._identities is None:  # pragma: no cover - wiring error
            raise RuntimeError("SessionService.refresh needs an IdentityRepository")

        for _ in range(2):
            match = await self._sessions.find_by_refresh_token(refresh_token)
            if match is None:
                raise session_expired()
            row = match.session
            now = datetime.now(UTC)

            if row.revoked_at is not None or row.expires_at <= now:
                raise session_expired()
            if self._absolute_ttl_seconds is not None and (
                row.created_at + timedelta(seconds=self._absolute_ttl_seconds) <= now
            ):
                raise session_expired()

            if not match.is_current:
                within_grace = (
                    match.rotated_at is not None
                    and (now - match.rotated_at).total_seconds() <= self._grace_seconds
                )
                if not within_grace:
                    await self._sessions.revoke(
                        row.id, identity_id=row.identity_id, reason="replay"
                    )
                    raise RefreshReplayError(
                        session_id=row.id,
                        identity_id=row.identity_id,
                        tenant_id=row.tenant_id,
                    )

            identity = await self._identities.get(row.identity_id)
            if identity is None:
                raise session_expired()
            if identity.status != "active":
                # Disabled and deleted alike: the session outlived the
                # account it belongs to, and refusing it here is cheaper
                # than every downstream service discovering it separately.
                await self._sessions.revoke(
                    row.id, identity_id=row.identity_id, reason="account_inactive"
                )
                exc = ApiError("account_disabled", 403, detail="account is not active")
                raise exc

            memberships = await self._identities.list_memberships(identity.id)
            membership = next((m for m in memberships if m.tenant_id == row.tenant_id), None)
            if membership is None:
                # Removed from the workspace this session is scoped to.
                await self._sessions.revoke(
                    row.id, identity_id=row.identity_id, reason="membership_lost"
                )
                if not memberships:
                    # Nowhere left to go at all. BE-2 F3: rather than
                    # answering `no_workspace` and leaving the person with
                    # nothing they can act on, give them back the personal
                    # workspace every identity is entitled to. Their old
                    # notes are wherever they were — this restores a place
                    # to stand, not any content.
                    if await self._heal_workspace(identity) is None:
                        # The healer is unavailable (no repository wired)
                        # or lost a race it should have won. Answer the
                        # documented code (docs/api/error-codes.md).
                        raise ApiError(
                            "no_workspace", 409, detail="no active workspace for this account"
                        )
                    # The session was revoked above (`membership_lost`);
                    # a healed workspace does not un-revoke it. The client
                    # signs in again and lands in the new workspace, which
                    # is the honest sequence: the session it presented was
                    # scoped to a tenant it is no longer in.
                    raise session_expired()
                # Other workspaces are still open to them; signing in
                # again picks one they are a member of.
                raise session_expired()

            new_token = new_refresh_token()
            expires_at = self._next_expiry(created_at=row.created_at, now=now)
            rotated = await self._sessions.rotate(
                session_id=row.id,
                presented=refresh_token,
                new_token=new_token,
                expires_at=expires_at,
                ip=ip,
                presented_is_current=match.is_current,
            )
            if not rotated:
                # Someone rotated this session between the read and the
                # write. Look again: the token is now the retired one.
                continue

            roles = platform_roles_for(membership.role, tenant_kind=membership.kind)
            minted = self._tokens.mint(
                identity_id=identity.id,
                session_id=str(row.id),
                tenant_id=row.tenant_id,
                roles=roles,
                mfa=row.mfa,
                mfa_enrolled=identity.mfa_enabled,
                email=identity.email,
                name=identity.display_name or None,
            )
            return RefreshedSession(
                session_id=row.id,
                identity_id=identity.id,
                tenant_id=row.tenant_id,
                roles=roles,
                access_token=minted.token,
                expires_in=minted.expires_in,
                refresh_token=new_token,
                refresh_expires_in=max(int((expires_at - now).total_seconds()), 1),
            )

        raise session_expired()

    def _next_expiry(self, *, created_at: datetime, now: datetime) -> datetime:
        """The idle window, slid forward — but never past the absolute cap.

        Sliding is what makes "signed in on my Mac" true for someone who
        uses the app every week. The cap is what stops it being true
        forever: a session nobody can name is one nobody revokes.
        """
        idle = now + timedelta(seconds=self._refresh_ttl_seconds)
        if self._absolute_ttl_seconds is None:
            return idle
        return min(idle, created_at + timedelta(seconds=self._absolute_ttl_seconds))

    # ── switching workspace (IDX-A2 F3, carried by IDX-M2) ───────────────

    async def switch_tenant(
        self,
        *,
        session_id: UUID,
        identity_id: UUID,
        tenant_id: UUID,
        activate: bool = True,
    ) -> SwitchedToken:
        """Mint an access token scoped to another of this identity's workspaces.

        Two callers, one endpoint. A person choosing a workspace in the
        switcher wants the session to move with them (``activate``), so the
        next refresh — and the next launch — comes back to the same place.
        A background upload that belongs to the workspace it started in
        wants a token for that workspace and nothing else: `activate=False`
        leaves the session where the person put it.

        Every refusal here is a fact about the *caller's* standing, so
        each has its own code (``docs/api/error-codes.md``): a suspended
        membership and a dissolved workspace are things they can act on; a
        workspace they were never in is answered exactly like one that
        does not exist.
        """
        if self._identities is None:  # pragma: no cover - wiring error
            raise RuntimeError("SessionService.switch_tenant needs an IdentityRepository")

        row = await self._sessions.get(session_id)
        if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
            raise ApiError("session_revoked", 401, detail="this session is no longer live")
        if row.identity_id != identity_id:
            # The token's `sid` and `sub` disagree: not a situation any
            # honest client produces.
            raise ApiError("session_revoked", 401, detail="this session is no longer live")

        identity = await self._identities.get(identity_id)
        if identity is None or identity.status != "active":
            raise ApiError("account_disabled", 403, detail="account is not active")

        lookup = await self._identities.membership_in(identity_id, tenant_id)
        membership = lookup.membership
        if membership is None:
            raise ApiError("not_a_member", 403, detail="no membership in that workspace")
        if membership.status != "active":
            raise ApiError("membership_suspended", 403, detail="that membership is suspended")
        if not lookup.tenant_active:
            raise ApiError("tenant_dissolved", 403, detail="that workspace has been closed")

        activated = False
        if activate and row.tenant_id != tenant_id:
            # The session row is what a refresh re-mints from; moving it is
            # what makes the switch survive the access token.
            activated = await self._sessions.set_tenant(session_id, tenant_id=tenant_id)
            if not activated:
                raise ApiError("session_revoked", 401, detail="this session is no longer live")
            await self._identities.set_last_tenant(identity_id, tenant_id=tenant_id)

        roles = platform_roles_for(membership.role, tenant_kind=membership.kind)
        minted = self._tokens.mint(
            identity_id=identity.id,
            session_id=str(session_id),
            tenant_id=tenant_id,
            roles=roles,
            mfa=row.mfa,
            mfa_enrolled=identity.mfa_enabled,
            email=identity.email,
            name=identity.display_name or None,
        )
        return SwitchedToken(
            tenant_id=tenant_id,
            roles=roles,
            access_token=minted.token,
            expires_in=minted.expires_in,
            activated=activated,
        )

    async def revoke(self, *, refresh_token: str) -> EndedSession | None:
        """End the session this token belongs to. Idempotent.

        Accepts the retired token as well as the current one, with no
        grace check: a client whose rotation response was lost is still
        entitled to sign itself out, and a replayed *logout* costs the
        attacker the session rather than winning them anything.
        """
        match = await self._sessions.find_by_refresh_token(refresh_token)
        if match is None:
            return None
        row = match.session
        await self._sessions.revoke(row.id, identity_id=row.identity_id, reason="logout")
        return EndedSession(session_id=row.id, identity_id=row.identity_id, tenant_id=row.tenant_id)
