"""Workspace invitations (W2, ADR-0070): one entity, an authenticated accept, auto-accept at sign-up.

Nothing is ever granted to whoever holds a link: accepting checks that the
signed-in identity's address IS the invited address. The token in the mail
only lets its holder *see* the invitation.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from .. import auth_metrics
from . import compose
from . import email_code as ec
from .errors import ApiError
from .identity_repository import Identity, Membership
from .invitation_repository import InvitationRepository, new_token

logger = logging.getLogger(__name__)

INVITABLE_ROLES: frozenset[str] = frozenset({"admin", "member", "viewer"})
# W3: a guest is invited to one note, with a per-note role.
NOTE_ROLES: frozenset[str] = frozenset({"view", "comment", "edit"})
TTL = timedelta(days=14)

# FixedWindowLimiter scopes (prefix `mdx:auth:rl`); `invite:*` fail closed (Level 3: mail to strangers).
SCOPE_INVITE_TENANT = "invite:tenant"
SCOPE_INVITE_IDENTITY = "invite:identity"
SCOPE_RESEND = "resend:invitation"
_DAY = 86400


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
    ) -> Any: ...


class InvitationMailer(Protocol):
    async def send_invitation(self, *, to: str, lang: str, fields: dict[str, Any]) -> None: ...


# (event, invitee identity id, personal tenant id, invitation row) → publish; best-effort.
Notify = Callable[..., Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Created:
    invitation: asyncpg.Record
    created: bool
    # "sent" or "queued_failed" (the row exists; the pending list offers Resend).
    delivery: str
    has_account: bool


@dataclass(frozen=True, slots=True)
class Accepted:
    tenant_id: UUID
    role: str
    invitation_id: UUID
    # joined | rejoined | already_member
    outcome: str


class InvitationService:
    def __init__(
        self,
        *,
        repo: InvitationRepository,
        mailer: InvitationMailer,
        limiter: Limiter | None,
        app_base_url: str,
        notify: Notify | None = None,
    ) -> None:
        self._repo = repo
        self._mailer = mailer
        self._limiter = limiter
        self._app_base_url = app_base_url
        self._notify = notify

    # ── management ───────────────────────────────────────────────────

    async def create(
        self,
        *,
        tenant_id: UUID,
        workspace_kind: str,
        inviter: Identity,
        email: str,
        role: str,
        message: str,
        lang: str,
        note_id: UUID | None = None,
        note_role: str | None = None,
    ) -> Created:
        address = ec.normalise_email(email)
        if not compose.looks_like_email(address) or len(address) > 320:
            raise ApiError("invalid_email", 422, detail="that does not look like an email address")
        if note_id is None and role not in INVITABLE_ROLES:
            raise ApiError(
                "invalid_role", 422, detail=f"role must be one of {sorted(INVITABLE_ROLES)}"
            )
        if note_id is not None and (role != "guest" or note_role not in NOTE_ROLES):
            raise ApiError(
                "invalid_role",
                422,
                detail="a note invitation is role `guest` with note_role view|comment|edit",
            )
        if workspace_kind == "personal":
            raise ApiError(
                "personal_workspace", 422, detail="nobody can be invited into a personal workspace"
            )
        if await self._repo.is_active_member(tenant_id=tenant_id, email=address):
            raise ApiError("already_member", 409, detail="that person is already in this workspace")
        await self._limit(SCOPE_INVITE_TENANT, str(tenant_id), 50)
        await self._limit(SCOPE_INVITE_IDENTITY, str(inviter.id), 100)

        token, token_hash = new_token()
        row, created = await self._repo.upsert_live(
            tenant_id=tenant_id,
            email=address,
            role=role,
            invited_by=inviter.id,
            message=message.strip()[:500],
            lang=lang,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + TTL,
            note_id=note_id,
            note_role=note_role,
        )
        invitee_id = await self._repo.identity_id_for(address)
        row, delivery = await self._send(row, token)
        action = "created" if created else "resent"
        auth_metrics.invitation_counter.add(
            1, {"action": action, "has_account": str(invitee_id is not None).lower()}
        )
        if invitee_id is not None:
            await self._emit("invited", invitee_id=invitee_id, invitation=row, actor=inviter.id)
        logger.info(
            "auth.invitation.created",
            extra={
                "invitation_id": str(row["id"]),
                "tenant_id": str(tenant_id),
                "inviter_sub": str(inviter.id),
                "result": action,
            },
        )
        return Created(
            invitation=row, created=created, delivery=delivery, has_account=invitee_id is not None
        )

    async def resend(self, *, tenant_id: UUID, invitation_id: UUID) -> Created:
        await self._limit(SCOPE_RESEND, str(invitation_id), 3, fail_open=True)
        token, token_hash = new_token()
        row = await self._repo.rearm(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + TTL,
        )
        if row is None:
            if await self._repo.get(tenant_id=tenant_id, invitation_id=invitation_id) is None:
                raise ApiError("invitation_not_found", 404, detail="no such invitation")
            raise ApiError("not_pending", 409, detail="this invitation is no longer pending")
        row, delivery = await self._send(row, token)
        has_account = await self._repo.identity_id_for(row["email"]) is not None
        auth_metrics.invitation_counter.add(
            1, {"action": "resent", "has_account": str(has_account).lower()}
        )
        return Created(invitation=row, created=False, delivery=delivery, has_account=has_account)

    async def revoke(self, *, tenant_id: UUID, invitation_id: UUID, actor: UUID) -> None:
        row = await self._repo.revoke(
            tenant_id=tenant_id, invitation_id=invitation_id, revoked_by=actor
        )
        if row is None:
            if await self._repo.get(tenant_id=tenant_id, invitation_id=invitation_id) is None:
                raise ApiError("invitation_not_found", 404, detail="no such invitation")
            raise ApiError("not_pending", 409, detail="this invitation is no longer pending")
        auth_metrics.invitation_counter.add(1, {"action": "revoked", "has_account": "unknown"})

    async def can_manage_note(self, *, tenant_id: UUID, note_id: UUID, sub: UUID) -> bool:
        return await self._repo.can_manage_note(tenant_id=tenant_id, note_id=note_id, sub=sub)

    async def revoke_all_for_tenant(self, tenant_id: UUID, *, actor: UUID) -> int:
        """Dissolve: every open invitation of the workspace stops working."""
        return await self._repo.revoke_all_for_tenant(tenant_id, revoked_by=actor)

    async def revoke_sent_by(self, identity_id: UUID) -> int:
        """Account deletion: invitations the person sent stop working."""
        return await self._repo.revoke_sent_by(identity_id)

    async def sweep(self) -> int:
        return await self._repo.sweep()

    # ── the invitee ──────────────────────────────────────────────────

    async def lookup(self, token: str) -> asyncpg.Record:
        row = await self._repo.find_live_by_token(token)
        if row is None:
            raise _not_found()
        return row

    async def accept_token(self, token: str, identity: Identity) -> Accepted:
        row = await self._repo.find_live_by_token(token)
        if row is None:
            raise _not_found()
        if row["email"] != ec.normalise_email(identity.email):
            auth_metrics.invitation_counter.add(1, {"action": "mismatch", "has_account": "true"})
            raise ApiError(
                "invitation_email_mismatch",
                403,
                detail="this invitation was sent to a different address",
            )
        return await self._accept(row, identity, action="accepted")

    async def accept_id(self, invitation_id: UUID, identity: Identity) -> Accepted:
        # The caller's own address is the proof: the row is selected by it.
        row = await self._repo.get_live_for_email(invitation_id, ec.normalise_email(identity.email))
        if row is None:
            raise _not_found()
        return await self._accept(row, identity, action="accepted")

    async def decline(self, invitation_id: UUID, identity: Identity) -> UUID:
        """Decline one of my invitations; returns its workspace (for the audit trail)."""
        email = ec.normalise_email(identity.email)
        row = await self._repo.get_live_for_email(invitation_id, email)
        if row is None or not await self._repo.decline(
            invitation_id=invitation_id, email=email, identity_id=identity.id
        ):
            raise _not_found()
        auth_metrics.invitation_counter.add(1, {"action": "declined", "has_account": "true"})
        tenant_id: UUID = row["tenant_id"]
        return tenant_id

    async def list_for_tenant(self, *, tenant_id: UUID, status: str) -> list[asyncpg.Record]:
        return await self._repo.list_for_tenant(tenant_id=tenant_id, status=status)

    async def mine(self, identity: Identity) -> list[asyncpg.Record]:
        return await self._repo.list_live_for_email(ec.normalise_email(identity.email))

    async def accept_all_open(self, identity: Identity) -> list[Membership]:
        """Sign-up: every open invitation for the new address, each in its own transaction."""
        joined: list[Membership] = []
        for row in await self.mine(identity):
            try:
                accepted = await self._accept(row, identity, action="auto_accepted")
            except Exception as exc:  # noqa: BLE001 — one failure leaves that invitation pending
                logger.warning(
                    "invitation.auto_accept_failed",
                    extra={"invitation_id": str(row["id"]), "error_class": type(exc).__name__},
                )
                continue
            joined.append(
                Membership(
                    tenant_id=accepted.tenant_id,
                    name=row["workspace_name"],
                    kind=row["workspace_kind"],
                    role=accepted.role,
                    status="active",
                )
            )
        return joined

    async def _accept(self, row: asyncpg.Record, identity: Identity, *, action: str) -> Accepted:
        result = await self._repo.accept(invitation_id=row["id"], identity_id=identity.id)
        if result is None:
            # Lost a race with a revoke, or it expired in between.
            raise _not_found()
        membership, outcome = result
        auth_metrics.invitation_counter.add(1, {"action": action, "has_account": "true"})
        await self._emit(
            "accepted", invitee_id=row["invited_by"], invitation=row, actor=identity.id
        )
        logger.info(
            "auth.invitation.accepted",
            extra={
                "invitation_id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "result": outcome,
            },
        )
        return Accepted(
            tenant_id=membership["tenant_id"],
            role=membership["role"],
            invitation_id=row["id"],
            outcome=outcome,
        )

    # ── helpers ──────────────────────────────────────────────────────

    async def _send(self, row: asyncpg.Record, token: str) -> tuple[asyncpg.Record, str]:
        """Mail the link; a relay failure keeps the row (`queued_failed`) for a Resend."""
        lang = row["lang"]
        fields = compose.invitation_fields(
            lang=lang,
            workspace_name=row["workspace_name"],
            inviter_display=row["invited_by_display"],
            role=row["role"],
            message=row["message"],
            invite_url=compose.invite_url(app_base_url=self._app_base_url, token=token),
            expires_at=row["expires_at"],
        )
        try:
            await self._mailer.send_invitation(to=row["email"], lang=lang, fields=fields)
        except Exception as exc:  # noqa: BLE001 — the invitation exists; only the mail failed
            logger.warning(
                "auth.invitation.mail_failed",
                extra={"invitation_id": str(row["id"]), "error_class": type(exc).__name__},
            )
            auth_metrics.invitation_counter.add(
                1, {"action": "mail_failed", "has_account": "unknown"}
            )
            return row, "queued_failed"
        return await self._repo.mark_sent(row["id"]), "sent"

    async def _limit(
        self, scope: str, subject: str, limit: int, *, fail_open: bool = False
    ) -> None:
        if self._limiter is None:
            if fail_open:
                return
            raise ApiError(
                "invite_unavailable", 503, detail="invitations are unavailable right now"
            )
        decision = await self._limiter.allow(
            scope, subject, limit=limit, window_seconds=_DAY, fail_open=fail_open
        )
        if decision.allowed:
            return
        if getattr(decision, "degraded", False):
            raise ApiError(
                "invite_unavailable", 503, detail="invitations are unavailable right now"
            )
        raise ApiError(
            "rate_limited",
            429,
            detail="too many invitations today; try again tomorrow",
            retry_after=decision.retry_after,
        )

    async def _emit(
        self, event: str, *, invitee_id: UUID, invitation: asyncpg.Record, actor: UUID
    ) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(
                event,
                recipient=invitee_id,
                invitation=invitation,
                actor=actor,
                personal_tenant_id=(
                    await self._repo.personal_tenant_of(invitee_id) if event == "invited" else None
                ),
            )
        except Exception as exc:  # noqa: BLE001 — a notification never fails the write
            logger.warning(
                "auth.invitation.notify_failed", extra={"error_class": type(exc).__name__}
            )


def _not_found() -> ApiError:
    # One shape for unknown, revoked, expired and accepted: the token says nothing more.
    return ApiError("invitation_not_found", 404, detail="this invitation is no longer valid")
