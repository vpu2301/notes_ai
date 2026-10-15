"""Workspace invitations (W2, ADR-0070).

Management: `/tenants/{tenant_id}/invitations` — owners/admins of the active
workspace, step-up on every write. Invitee: `/auth/invitations` — by the token
in the mail (anonymous lookup only) or by the signed-in person's own address.
Accepting is always authenticated and always checks the address.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from auth.perms import can

from .. import audit_kinds
from ..deps import current_user, get_state, requires
from ..domain import compose
from ..domain.errors import ApiError
from ..domain.identity_repository import Identity
from ..domain.invitation_repository import STATUSES
from ..domain.transport import TokenResponse
from .email_code import _resolve_ip
from .native_common import as_problem, audit, current_identity
from .tenants import (
    _require_active_tenant,
    _require_manager,
    _require_member,
    manage_step_up,
)

logger = logging.getLogger(__name__)

manage_router = APIRouter(prefix="/tenants", tags=["workspace invitations"])
invitee_router = APIRouter(prefix="/auth/invitations", tags=["workspace invitations"])

_LOOKUP_PER_MINUTE = 60


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvitationCreate(_Strict):
    email: str = Field(min_length=3, max_length=320)
    # `guest` only with `note_id` (W3): someone outside the workspace, invited to one note.
    role: Literal["admin", "member", "viewer", "guest"] = "member"
    message: str = Field(default="", max_length=500)
    lang: Literal["en", "de", "uk"] | None = None
    note_id: UUID | None = None
    note_role: Literal["view", "comment", "edit"] | None = None


class InvitationOut(_Strict):
    id: UUID
    email: str
    role: str
    note_id: UUID | None = None
    note_role: str | None = None
    status: str
    expires_at: datetime
    sent_count: int
    last_sent_at: datetime | None
    invited_by_display: str
    created_at: datetime
    # "sent" | "queued_failed" on create/resend; null when listed.
    delivery: str | None = None


class InvitationListOut(_Strict):
    items: list[InvitationOut]


class InvitationLookupOut(_Strict):
    workspace_name: str
    inviter_display: str
    role: str
    email_masked: str
    expires_at: datetime
    note_title: str | None = None


class MyInvitationOut(_Strict):
    id: UUID
    workspace_name: str
    inviter_display: str
    role: str
    expires_at: datetime


class MyInvitationListOut(_Strict):
    items: list[MyInvitationOut]


class AcceptOut(_Strict):
    tenant_id: UUID
    role: str
    # The session was switched to `tenant_id`; null only for a Keycloak-era session that cannot switch.
    token: TokenResponse | None


def _service() -> Any:
    service = getattr(get_state(), "invitation_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return service


def _out(row: Any, delivery: str | None = None) -> InvitationOut:
    return InvitationOut(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        note_id=row["note_id"],
        note_role=row["note_role"],
        status=row["status"],
        expires_at=row["expires_at"],
        sent_count=row["sent_count"],
        last_sent_at=row["last_sent_at"],
        invited_by_display=row["invited_by_display"],
        created_at=row["created_at"],
        delivery=delivery,
    )


async def _manager(tenant_id: UUID, claims: Claims) -> None:
    """404 for a workspace the caller is not in; 403 unless owner/admin of the active one."""
    role = await _require_member(tenant_id, claims)
    _require_active_tenant(tenant_id, claims)
    _require_manager(role)


# ── management ───────────────────────────────────────────────────────────


@manage_router.post(
    "/{tenant_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Invite someone to this workspace by e-mail (re-inviting resends)",
    dependencies=[Depends(manage_step_up)],
)
async def create_invitation(
    tenant_id: UUID,
    body: InvitationCreate,
    response: Response,
    claims: Annotated[Claims, Depends(current_user)],
    inviter: Annotated[Identity, Depends(current_identity)],
) -> InvitationOut:
    service = _service()
    if body.note_id is not None:
        # W3: a note's authors invite a guest to that one note without managing the workspace.
        await _require_member(tenant_id, claims)
        _require_active_tenant(tenant_id, claims)
        if not await service.can_manage_note(
            tenant_id=tenant_id, note_id=body.note_id, sub=claims.sub
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="note not found")
    else:
        if not any(can(r, "tenant.manage_members", "tenant") for r in claims.roles or ()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        await _manager(tenant_id, claims)
    workspace = await _workspace(tenant_id)
    try:
        result = await service.create(
            tenant_id=tenant_id,
            workspace_kind=workspace["kind"],
            inviter=inviter,
            email=body.email,
            role=body.role,
            message=body.message,
            lang=body.lang or inviter.locale or "en",
            note_id=body.note_id,
            note_role=body.note_role,
        )
    except ApiError as exc:
        raise as_problem(exc) from exc
    if not result.created:
        # Idempotent re-invite: the same row, a fresh link.
        response.status_code = status.HTTP_200_OK
    await audit(
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_INVITATION_CREATED,
        payload={
            "invitation_id": str(result.invitation["id"]),
            "role": body.role,
            "has_account": result.has_account,
            "note": body.note_id is not None,
            "resent": not result.created,
        },
        severity=Severity.SEC,
        actor_sub=claims.sub,
        target_id=result.invitation["id"],
    )
    return _out(result.invitation, result.delivery)


@manage_router.get(
    "/{tenant_id}/invitations",
    response_model=InvitationListOut,
    summary="This workspace's invitations by status (default: pending)",
)
async def list_invitations(
    tenant_id: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.manage_members", "tenant"))],
    status_filter: Annotated[str, Query(alias="status")] = "pending",
) -> InvitationListOut:
    await _manager(tenant_id, claims)
    if status_filter not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(STATUSES)}")
    rows = await _service().list_for_tenant(tenant_id=tenant_id, status=status_filter)
    return InvitationListOut(items=[_out(r) for r in rows])


@manage_router.post(
    "/{tenant_id}/invitations/{invitation_id}/resend",
    response_model=InvitationOut,
    summary="Send a pending invitation again (a new link; the old one stops working)",
    dependencies=[Depends(manage_step_up)],
)
async def resend_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.manage_members", "tenant"))],
) -> InvitationOut:
    await _manager(tenant_id, claims)
    try:
        result = await _service().resend(tenant_id=tenant_id, invitation_id=invitation_id)
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_INVITATION_CREATED,
        payload={
            "invitation_id": str(invitation_id),
            "role": result.invitation["role"],
            "has_account": result.has_account,
            "note": False,
            "resent": True,
        },
        severity=Severity.SEC,
        actor_sub=claims.sub,
        target_id=invitation_id,
    )
    return _out(result.invitation, result.delivery)


@manage_router.delete(
    "/{tenant_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a pending invitation",
    dependencies=[Depends(manage_step_up)],
)
async def revoke_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.manage_members", "tenant"))],
) -> Response:
    await _manager(tenant_id, claims)
    try:
        await _service().revoke(tenant_id=tenant_id, invitation_id=invitation_id, actor=claims.sub)
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_INVITATION_REVOKED,
        payload={"invitation_id": str(invitation_id)},
        severity=Severity.SEC,
        actor_sub=claims.sub,
        target_id=invitation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── the invitee ──────────────────────────────────────────────────────────


@invitee_router.get(
    "",
    response_model=MyInvitationListOut,
    summary="My open invitations (by my signed-in address)",
)
async def my_invitations(
    identity: Annotated[Identity, Depends(current_identity)],
) -> MyInvitationListOut:
    rows = await _service().mine(identity)
    return MyInvitationListOut(
        items=[
            MyInvitationOut(
                id=r["id"],
                workspace_name=r["workspace_name"],
                inviter_display=r["invited_by_display"],
                role=r["role"],
                expires_at=r["expires_at"],
            )
            for r in rows
        ]
    )


@invitee_router.get(
    "/{token}",
    response_model=InvitationLookupOut,
    summary="What an invitation link points at (anonymous; one 404 for every non-live state)",
)
async def lookup_invitation(token: str, request: Request) -> InvitationLookupOut:
    service = _service()
    limiter = getattr(get_state(), "limiter", None)
    if limiter is not None:
        decision = await limiter.allow(
            "invite-lookup:ip", _resolve_ip(request), limit=_LOOKUP_PER_MINUTE, window_seconds=60
        )
        if not decision.allowed:
            raise as_problem(
                ApiError(
                    "rate_limited", 429, detail="too many lookups", retry_after=decision.retry_after
                )
            )
    try:
        row = await service.lookup(token)
    except ApiError as exc:
        raise as_problem(exc) from exc
    return InvitationLookupOut(
        workspace_name=row["workspace_name"],
        inviter_display=row["invited_by_display"],
        role=row["role"],
        email_masked=compose.mask_email(row["email"]),
        expires_at=row["expires_at"],
    )


@invitee_router.post(
    "/{key}/accept",
    response_model=AcceptOut,
    summary="Join — by the link's token or, from the in-app list, by invitation id; only as the invited address",
)
async def accept_invitation(
    key: str,
    claims: Annotated[Claims, Depends(current_user)],
    identity: Annotated[Identity, Depends(current_identity)],
) -> AcceptOut:
    """A token is 43 urlsafe characters and never parses as a UUID, so one path serves both."""
    service = _service()
    try:
        invitation_id = UUID(key)
    except ValueError:
        invitation_id = None
    try:
        if invitation_id is not None:
            accepted = await service.accept_id(invitation_id, identity)
        else:
            accepted = await service.accept_token(key, identity)
    except ApiError as exc:
        raise as_problem(exc) from exc
    return await _joined(accepted, claims, via="in_app" if invitation_id else "link")


@invitee_router.post(
    "/{invitation_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline one of my invitations",
)
async def decline_invitation(
    invitation_id: UUID,
    claims: Annotated[Claims, Depends(current_user)],
    identity: Annotated[Identity, Depends(current_identity)],
) -> Response:
    try:
        tenant_id = await _service().decline(invitation_id, identity)
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_INVITATION_DECLINED,
        payload={"invitation_id": str(invitation_id)},
        severity=Severity.INFO,
        actor_sub=claims.sub,
        target_id=invitation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _joined(accepted: Any, claims: Claims, *, via: str) -> AcceptOut:
    """Audit, then move this session into the joined workspace and hand back its token."""
    await audit(
        tenant_id=accepted.tenant_id,
        kind=audit_kinds.TENANT_INVITATION_ACCEPTED,
        payload={
            "invitation_id": str(accepted.invitation_id),
            "role": accepted.role,
            "via": via,
            "outcome": accepted.outcome,
        },
        severity=Severity.SEC,
        actor_sub=claims.sub,
        target_id=accepted.invitation_id,
    )
    if accepted.outcome != "already_member":
        await audit(
            tenant_id=accepted.tenant_id,
            kind=audit_kinds.TENANT_MEMBER_ADDED,
            payload={"role": accepted.role, "via": "invitation"},
            severity=Severity.SEC,
            actor_sub=claims.sub,
            target_id=claims.sub,
        )
    token: TokenResponse | None = None
    sessions: Any = getattr(get_state(), "session_service", None)
    try:
        if sessions is None:
            raise ValueError("no session service")
        switched = await sessions.switch_tenant(
            session_id=UUID(claims.sid),
            identity_id=claims.sub,
            tenant_id=accepted.tenant_id,
            activate=True,
        )
        token = TokenResponse(
            access_token=switched.access_token,
            expires_in=switched.expires_in,
            tenant_id=str(switched.tenant_id),
            roles=switched.roles,
        )
    except (ApiError, ValueError, AttributeError) as exc:
        # The membership exists either way; a Keycloak-era session simply cannot switch.
        logger.info("auth.invitation.switch_skipped", extra={"error_class": type(exc).__name__})
    return AcceptOut(tenant_id=accepted.tenant_id, role=accepted.role, token=token)


async def _workspace(tenant_id: UUID) -> Any:
    from db import tenant_connection

    from .. import tenants_repository as repo

    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        row = await repo.get_tenant(conn, tenant_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    return row
