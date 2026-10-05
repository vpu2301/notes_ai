"""Native sessions: start, refresh, switch_tenant, revoke.

``start`` guarantees a new ``sid`` every time (no fixation), a refresh token
returned once with only its sha256 stored, and ``roles`` from the membership.
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

# 32 bytes of CSPRNG.
logger = logging.getLogger(__name__)

_REFRESH_TOKEN_BYTES = 32

# ADR-0047: in `dual` one endpoint serves two refresh-token families under the
# same cookie name; the prefix is the only reliable discriminator.
NATIVE_REFRESH_PREFIX = "nrt_"


def new_refresh_token() -> str:
    """A native refresh token: the prefix, then 32 random bytes, url-safe."""
    return f"{NATIVE_REFRESH_PREFIX}{secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)}"


def is_native_refresh_token(value: str) -> bool:
    """Native store? `nrt_` prefix → yes; JWT shape (dots) → Keycloak; anything else → native (pre-prefix tokens)."""
    if value.startswith(NATIVE_REFRESH_PREFIX):
        return True
    return value.count(".") != 2


# Display label only, never a check.
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
    """What a rotation hands back: ``start``'s shape minus the sign-in-only fields."""

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
    """An access token for another of the identity's workspaces; no refresh token (switching does not rotate)."""

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
    """The same refresh token twice, outside the grace window; carries the session so the router can denylist the identity."""

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
    """No usable session behind this token; one code for expired, revoked and never-real on purpose."""
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
        # Only ``refresh`` needs these.
        self._identities = identities
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._absolute_ttl_seconds = absolute_ttl_seconds
        self._grace_seconds = grace_seconds

    async def _heal_workspace(self, identity: Identity) -> Membership | None:
        """Re-create the personal workspace for an identity that has none; None when unwired or not needed."""
        if self._identities is None:
            return None
        try:
            return await self._identities.ensure_personal_workspace(identity.id, identity.email)
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
        """Open a session in ``membership.tenant_id`` and mint its first token; the route has checked the membership."""
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

    # ── rotation ─────────────────────────────────────────────────────────

    async def refresh(
        self,
        *,
        refresh_token: str,
        ip: str = "",
    ) -> RefreshedSession:
        """Exchange a refresh token for the next one and a fresh access token.

        Order: resolve token + generation; a retired token past grace is a replay
        (session dies first); roles are re-read from the membership. A lost race
        re-reads once and comes out through the grace path.
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
                # The session outlived its account.
                await self._sessions.revoke(
                    row.id, identity_id=row.identity_id, reason="account_inactive"
                )
                exc = ApiError("account_disabled", 403, detail="account is not active")
                raise exc

            memberships = await self._identities.list_memberships(identity.id)
            membership = next((m for m in memberships if m.tenant_id == row.tenant_id), None)
            if membership is None:
                await self._sessions.revoke(
                    row.id, identity_id=row.identity_id, reason="membership_lost"
                )
                if not memberships:
                    # Nowhere left to go: heal the personal workspace instead of `no_workspace`.
                    if await self._heal_workspace(identity) is None:
                        raise ApiError(
                            "no_workspace", 409, detail="no active workspace for this account"
                        )
                    # A healed workspace does not un-revoke the session; the client signs in again.
                    raise session_expired()
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
                # Lost the race: look again, the token is now the retired one.
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
        """The idle window slid forward, never past the absolute cap."""
        idle = now + timedelta(seconds=self._refresh_ttl_seconds)
        if self._absolute_ttl_seconds is None:
            return idle
        return min(idle, created_at + timedelta(seconds=self._absolute_ttl_seconds))

    # ── switching workspace ──────────────────────────────────────────────

    async def switch_tenant(
        self,
        *,
        session_id: UUID,
        identity_id: UUID,
        tenant_id: UUID,
        activate: bool = True,
    ) -> SwitchedToken:
        """Mint an access token for another of this identity's workspaces.

        ``activate`` moves the session there too; ``activate=False`` is for
        background work scoped to its own workspace. Refusals have their own
        codes, except "never a member", which answers like "does not exist".
        """
        if self._identities is None:  # pragma: no cover - wiring error
            raise RuntimeError("SessionService.switch_tenant needs an IdentityRepository")

        row = await self._sessions.get(session_id)
        if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
            raise ApiError("session_revoked", 401, detail="this session is no longer live")
        if row.identity_id != identity_id:
            # `sid` and `sub` disagree: no honest client produces this.
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
            # Refresh re-mints from the session row, so the switch survives the token.
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
        """End the session this token belongs to; idempotent, accepts the retired token with no grace check."""
        match = await self._sessions.find_by_refresh_token(refresh_token)
        if match is None:
            return None
        row = match.session
        await self._sessions.revoke(row.id, identity_id=row.identity_id, reason="logout")
        return EndedSession(session_id=row.id, identity_id=row.identity_id, tenant_id=row.tenant_id)
