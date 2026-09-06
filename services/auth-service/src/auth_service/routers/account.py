"""Sessions, step-up, email change, deletion and the profile (IDX-A5 F4–F6).

Everything a person can do to their own account from the settings screen,
plus the step-up check the dangerous half of it is gated on.

The step-up rule, in one place: ``/auth/reauth`` re-stamps the session's
``last_authenticated_at``, and anything that could take the account away
from its owner — turning off the second factor, moving the login address,
deleting the account, ending every other session — carries
``Depends(recent_auth)``. An access token on its own is never enough for
those, because an unlocked laptop is an access token.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from audit import Severity
from auth import Claims

from .. import audit_kinds
from ..deps import current_user
from ..domain import copy as copy_mod
from ..domain.errors import ApiError
from ..domain.identity_repository import Identity
from ..domain.transport import IdentitySummary
from .native_common import (
    as_problem,
    audit,
    current_identity,
    native_services,
    recent_auth,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["account"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionOut(_Strict):
    sid: str
    client_type: str
    device_name: str
    user_agent: str
    ip_last: str
    created_at: datetime
    last_used_at: datetime
    last_authenticated_at: datetime
    current: bool


class RevokeOthersResponse(_Strict):
    revoked: int


class ReauthStartResponse(_Strict):
    methods: list[str]
    challenge_id: str | None = None
    expires_in: int


class ReauthRequest(_Strict):
    method: Literal["totp", "recovery_code", "email_code"]
    code: str = Field(min_length=1, max_length=64)
    challenge_id: UUID | None = None


class EmailChangeStartRequest(_Strict):
    new_email: EmailStr


class EmailChangeStartResponse(_Strict):
    challenge_id: str
    expires_in: int


class EmailChangeConfirmRequest(_Strict):
    challenge_id: UUID
    code: str = Field(min_length=1, max_length=32)


class DeleteRequest(_Strict):
    confirm: str


class DeleteResponse(_Strict):
    purge_after: datetime
    workspaces_dissolved: int


class ProfilePatch(_Strict):
    display_name: str | None = Field(default=None, max_length=120)
    locale: Literal["en", "de", "uk"] | None = None
    timezone: str | None = Field(default=None, max_length=64)


def _identity_out(identity: Identity) -> IdentitySummary:
    return IdentitySummary(
        id=str(identity.id),
        email=identity.email,
        display_name=identity.display_name,
        mfa_enabled=identity.mfa_enabled,
        has_password=identity.has_password,
        status=identity.status,
    )


def _sid(claims: Claims) -> UUID | None:
    try:
        return UUID(claims.sid)
    except (ValueError, TypeError):
        return None


# ── step-up ──────────────────────────────────────────────────────────────


@router.post(
    "/reauth/start",
    response_model=ReauthStartResponse,
    summary="Ask how to confirm it is really you",
)
async def reauth_start(
    identity: Annotated[Identity, Depends(current_identity)],
) -> ReauthStartResponse:
    services = native_services()
    options = await services.account.start_reauth(
        identity, lang=copy_mod.normalise_lang(identity.locale)
    )
    return ReauthStartResponse(
        methods=list(options.methods),
        challenge_id=str(options.challenge_id) if options.challenge_id else None,
        expires_in=options.expires_in,
    )


@router.post(
    "/reauth",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm it is really you, unlocking the sensitive endpoints",
)
async def reauth(
    body: ReauthRequest,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> Response:
    services = native_services()
    session_id = _sid(claims)
    if session_id is None:
        raise as_problem(ApiError("session_revoked", 401, detail="this session cannot be verified"))
    try:
        await services.account.complete_reauth(
            identity,
            session_id=session_id,
            method=body.method,
            code=body.code,
            challenge_id=body.challenge_id,
        )
    except ApiError as exc:
        await audit(
            tenant_id=claims.tid,
            kind=audit_kinds.AUTH_REAUTH_FAILED,
            payload={"identity_id": str(identity.id), "method": body.method},
            severity=Severity.SEC,
            actor_sub=identity.id,
            target_id=identity.id,
        )
        raise as_problem(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── sessions (F4) ────────────────────────────────────────────────────────


@router.get(
    "/sessions",
    response_model=list[SessionOut],
    summary="Where this account is currently signed in",
)
async def list_sessions(
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> list[SessionOut]:
    services = native_services()
    views = await services.account.list_sessions(identity, current_sid=_sid(claims) or UUID(int=0))
    return [
        SessionOut(
            sid=str(v.sid),
            client_type=v.client_type,
            device_name=v.device_name,
            user_agent=v.user_agent,
            ip_last=v.ip_last,
            created_at=v.created_at,
            last_used_at=v.last_used_at,
            last_authenticated_at=v.last_authenticated_at,
            current=v.current,
        )
        for v in views
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End one session",
)
async def revoke_session(
    session_id: UUID,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> Response:
    services = native_services()
    try:
        await services.account.revoke_session(identity, session_id=session_id)
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_SESSION_REVOKED,
        payload={"identity_id": str(identity.id), "sid": str(session_id), "reason": "user_revoked"},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/revoke-others",
    response_model=RevokeOthersResponse,
    dependencies=[Depends(recent_auth)],
    summary="End every session except this one",
)
async def revoke_others(
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> RevokeOthersResponse:
    services = native_services()
    revoked = await services.account.revoke_other_sessions(
        identity, current_sid=_sid(claims), reason="revoke_others"
    )
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_SESSION_REVOKED,
        payload={"identity_id": str(identity.id), "revoked": revoked, "reason": "revoke_others"},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return RevokeOthersResponse(revoked=revoked)


# ── email change (F5) ────────────────────────────────────────────────────


@router.post(
    "/email/change/start",
    response_model=EmailChangeStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(recent_auth)],
    summary="Send a code to a new address to move the login there",
)
async def email_change_start(
    body: EmailChangeStartRequest,
    request: Request,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> EmailChangeStartResponse:
    services = native_services()
    try:
        challenge_id = await services.account.start_email_change(
            identity,
            new_email=str(body.new_email),
            lang=copy_mod.normalise_lang(identity.locale),
            user_agent=request.headers.get("user-agent", ""),
        )
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_EMAIL_CHANGE_REQUESTED,
        payload={"identity_id": str(identity.id), "challenge_id": str(challenge_id)},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    from ..domain.account_service import EMAIL_CHANGE_TTL_SECONDS

    return EmailChangeStartResponse(
        challenge_id=str(challenge_id), expires_in=EMAIL_CHANGE_TTL_SECONDS
    )


@router.post(
    "/email/change/confirm",
    response_model=IdentitySummary,
    summary="Prove the new address and move the login to it",
)
async def email_change_confirm(
    body: EmailChangeConfirmRequest,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> IdentitySummary:
    services = native_services()
    try:
        updated, notified = await services.account.confirm_email_change(
            identity,
            challenge_id=body.challenge_id,
            code=body.code,
            lang=copy_mod.normalise_lang(identity.locale),
        )
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_EMAIL_CHANGED,
        # The addresses themselves stay out of the payload: the audit
        # trail records that the login moved, not what it moved to.
        payload={"identity_id": str(identity.id), "notify_failed": not notified},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return _identity_out(updated)


@router.get(
    "/email/revert/{token}",
    response_class=HTMLResponse,
    summary="Undo an email change from the notice sent to the old address",
)
async def email_revert(token: str) -> HTMLResponse:
    """A page, not a JSON endpoint: it is opened from a mail client.

    Acting on GET is a deliberate exception to the usual rule. The person
    reaching this has been locked out of their own account and is holding
    a one-shot, unguessable token; asking them to POST from a page we
    would have to render first only adds a step to an emergency.
    """
    services = native_services()
    try:
        identity = await services.account.revert_email(token)
    except ApiError as exc:
        return HTMLResponse(_revert_page(ok=False, detail=exc.detail), status_code=exc.status_code)
    await audit(
        tenant_id=identity.last_tenant_id or UUID(services.platform_tenant_id),
        kind=audit_kinds.AUTH_EMAIL_REVERTED,
        payload={"identity_id": str(identity.id)},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return HTMLResponse(_revert_page(ok=True, detail=identity.email))


def _revert_page(*, ok: bool, detail: str) -> str:
    title = "Your address has been restored" if ok else "That link cannot be used"
    body = (
        f"Your Notes AI account is back on <strong>{detail}</strong>, and every "
        "signed-in session has been ended. Sign in again to carry on — and "
        "change your email password if you think somebody else had access."
        if ok
        else f"{detail}. If you still cannot get into your account, contact us."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title></head>
<body style="margin:0;background:#E6E1D6;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:560px;margin:64px auto;background:#FAF7F0;border-radius:14px;padding:44px;">
<p style="margin:0 0 8px;font-size:13px;letter-spacing:.14em;color:#6E675C;">NOTES AI</p>
<h1 style="margin:0 0 16px;font-family:Georgia,serif;font-size:32px;line-height:38px;color:#1F1C18;">{title}</h1>
<p style="margin:0;font-size:16px;line-height:26px;color:#6E675C;">{body}</p>
</div></body></html>"""


# ── deletion (F6) ────────────────────────────────────────────────────────


@router.post(
    "/account/delete",
    response_model=DeleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(recent_auth)],
    summary="Schedule this account for deletion after a 30-day grace period",
)
async def delete_account(
    body: DeleteRequest,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> DeleteResponse:
    if body.confirm != "DELETE":
        raise as_problem(
            ApiError(
                "confirm_required",
                400,
                detail="type DELETE to confirm",
            )
        )
    services = native_services()
    try:
        purge_after, dissolved, notified = await services.account.request_deletion(
            identity, lang=copy_mod.normalise_lang(identity.locale)
        )
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_ACCOUNT_DELETION_REQUESTED,
        payload={
            "identity_id": str(identity.id),
            "purge_after": purge_after.isoformat(),
            "tenants_dissolved": [str(t) for t in dissolved],
            "notify_failed": not notified,
        },
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return DeleteResponse(purge_after=purge_after, workspaces_dissolved=len(dissolved))


# ── profile ──────────────────────────────────────────────────────────────


@router.patch(
    "/me",
    response_model=IdentitySummary,
    summary="Update the display name, language or time zone",
)
async def patch_me(
    body: ProfilePatch,
    identity: Annotated[Identity, Depends(current_identity)],
) -> IdentitySummary:
    """Not gated on recent auth: nothing here can take the account away.

    A stolen session that renames somebody is vandalism, not compromise,
    and the friction of a step-up on every profile edit would train people
    to re-authenticate reflexively — which is the habit that makes the
    real prompts work.
    """
    services = native_services()
    updated = await services.identities.update_profile(
        identity.id,
        display_name=body.display_name,
        locale=body.locale,
        timezone=body.timezone,
    )
    if updated is None:
        raise as_problem(ApiError("not_found", 404, detail="no such account"))
    return _identity_out(updated)


__all__ = ["router"]
