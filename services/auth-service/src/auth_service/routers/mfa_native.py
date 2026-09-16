"""Second factors on the native identity (IDX-A5 F2/F3).

Route note: ``POST /auth/mfa/verify`` means the **login challenge** here —
the unauthenticated step between a passed first factor and a session.
Sprint 16 used that path to mean "complete my enrolment"; that behaviour
moved to ``POST /auth/mfa/totp/confirm``, which the pack defines anyway.
The old router still serves the old meaning in ``keycloak`` mode, so no
client breaks before the cut-over; ``main.py`` mounts exactly one of the
two.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims

from .. import audit_kinds
from ..config import settings
from ..deps import current_user
from ..domain.errors import ApiError
from ..domain.identity_repository import Identity
from ..domain.transport import (
    AuthResult,
    IdentitySummary,
    MembershipSummary,
    client_type_of,
)
from .native_common import (
    as_problem,
    audit,
    current_identity,
    native_services,
    platform_tenant,
    recent_auth,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChallengeVerifyRequest(_Strict):
    challenge_id: UUID
    method: Literal["totp", "recovery_code"]
    code: str = Field(min_length=1, max_length=64)


class EnrolResponse(_Strict):
    enrollment_id: str
    secret: str
    otpauth_uri: str
    expires_in: int


class ConfirmRequest(_Strict):
    enrollment_id: UUID
    code: str = Field(min_length=1, max_length=16)


class RecoveryCodesResponse(_Strict):
    recovery_codes: list[str]


class DisableRequest(_Strict):
    method: Literal["totp", "recovery_code"] = "totp"
    code: str = Field(min_length=1, max_length=64)


# ── the login challenge ──────────────────────────────────────────────────


@router.post(
    "/verify",
    response_model=AuthResult,
    summary="Complete a second factor and finish signing in",
)
async def verify(body: ChallengeVerifyRequest, request: Request, response: Response) -> AuthResult:
    """Unauthenticated by design: the caller has no session yet — that is
    the entire point of the challenge."""
    services = native_services()
    try:
        result = await services.mfa.verify_login_challenge(
            challenge_id=body.challenge_id, method=body.method, code=body.code
        )
    except ApiError as exc:
        await audit(
            tenant_id=platform_tenant(),
            kind=audit_kinds.AUTH_MFA_FAILED,
            payload={
                "challenge_id": str(body.challenge_id),
                "method": body.method,
                "outcome": exc.code,
            },
            severity=Severity.WARN,
        )
        raise as_problem(exc) from exc

    identity = result.identity
    if result.method == "recovery_code":
        await audit(
            tenant_id=result.session.tenant_id,
            kind=audit_kinds.AUTH_RECOVERY_CODE_USED,
            payload={
                "identity_id": str(identity.id),
                "remaining": result.recovery_codes_left,
            },
            severity=Severity.SEC,
            actor_sub=identity.id,
            target_id=identity.id,
        )
    await audit(
        tenant_id=result.session.tenant_id,
        kind=audit_kinds.AUTH_LOGIN,
        payload={
            "method": f"mfa_{result.method}",
            "identity_id": str(identity.id),
            "sid": str(result.session.session_id),
        },
        severity=Severity.INFO,
        actor_sub=identity.id,
        target_id=identity.id,
    )

    client_type = client_type_of(request)
    if not client_type.native:
        response.set_cookie(
            key=settings.auth_cookie_name,
            value=result.session.refresh_token,
            max_age=result.session.refresh_expires_in,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,  # type: ignore[arg-type]
            path=settings.auth_cookie_path,
        )
    out = AuthResult.authenticated(
        client_type=client_type,
        access_token=result.session.access_token,
        expires_in=result.session.expires_in,
        tenant_id=str(result.session.tenant_id),
        roles=result.session.roles,
        refresh_token=result.session.refresh_token,
        refresh_expires_in=result.session.refresh_expires_in,
        identity=IdentitySummary(
            id=str(identity.id),
            email=identity.email,
            display_name=identity.display_name,
            mfa_enabled=identity.mfa_enabled,
            has_password=identity.has_password,
            status=identity.status,
        ),
        memberships=[
            MembershipSummary(
                tenant_id=str(m.tenant_id),
                name=m.name,
                kind=m.kind,
                role=m.role,
                status=m.status,
            )
            for m in result.memberships
        ],
        is_new_identity=False,
    )
    if result.recovery_codes_left is not None:
        # The client shows "you have N left" and, at zero, insists on a
        # new set — the user has just spent their last way back in.
        return out.model_copy(
            update={
                "recovery_codes_left": result.recovery_codes_left,
                "recovery_codes_exhausted": result.recovery_codes_left == 0,
            }
        )
    return out


# ── enrolment ────────────────────────────────────────────────────────────


@router.post(
    "/totp/enroll",
    response_model=EnrolResponse,
    dependencies=[Depends(recent_auth)],
    summary="Begin TOTP enrolment — returns the secret and provisioning URI",
)
async def enroll(identity: Annotated[Identity, Depends(current_identity)]) -> EnrolResponse:
    """The one place the secret is ever returned.

    Over TLS, to a session that has just proved itself, and only until a
    code confirms it — after that the secret exists solely as ciphertext.
    """
    services = native_services()
    try:
        enrolment = await services.mfa.start_enrolment(identity)
    except ApiError as exc:
        raise as_problem(exc) from exc
    return EnrolResponse(
        enrollment_id=str(enrolment.enrollment_id),
        secret=enrolment.secret,
        otpauth_uri=enrolment.otpauth_uri,
        expires_in=enrolment.expires_in,
    )


@router.post(
    "/totp/confirm",
    response_model=RecoveryCodesResponse,
    summary="Finish TOTP enrolment with a first valid code",
)
async def confirm(
    body: ConfirmRequest,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> RecoveryCodesResponse:
    services = native_services()
    try:
        codes = await services.mfa.confirm_enrolment(
            identity, enrollment_id=body.enrollment_id, code=body.code
        )
    except ApiError as exc:
        raise as_problem(exc) from exc

    # Turning MFA on means every other session predates the second factor.
    # Ending them is what makes enrolment a remedy for "I think somebody
    # is in my account", rather than a lock fitted to a door left open.
    revoked = await services.account.revoke_other_sessions(
        identity, current_sid=_sid_or_none(claims), reason="mfa_change"
    )
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_MFA_ENROLLED,
        payload={"identity_id": str(identity.id), "sessions_revoked": revoked},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post(
    "/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(recent_auth)],
    summary="Turn off the second factor (needs a valid factor as well)",
)
async def disable(
    body: DisableRequest,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> Response:
    services = native_services()
    try:
        await services.mfa.disable(identity, method=body.method, code=body.code)
    except ApiError as exc:
        raise as_problem(exc) from exc
    revoked = await services.account.revoke_other_sessions(
        identity, current_sid=_sid_or_none(claims), reason="mfa_change"
    )
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_MFA_DISABLED,
        payload={"identity_id": str(identity.id), "by": "user", "sessions_revoked": revoked},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/recovery-codes",
    response_model=RecoveryCodesResponse,
    dependencies=[Depends(recent_auth)],
    summary="Issue a fresh set of recovery codes, invalidating the old ones",
)
async def recovery_codes(
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> RecoveryCodesResponse:
    services = native_services()
    try:
        codes = await services.mfa.regenerate_recovery_codes(identity)
    except ApiError as exc:
        raise as_problem(exc) from exc
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.AUTH_RECOVERY_CODES_REGENERATED,
        payload={"identity_id": str(identity.id)},
        severity=Severity.SEC,
        actor_sub=identity.id,
        target_id=identity.id,
    )
    return RecoveryCodesResponse(recovery_codes=codes)


def _sid_or_none(claims: Claims) -> UUID | None:
    try:
        return UUID(claims.sid)
    except (ValueError, TypeError):
        return None


# ── admin reset ──────────────────────────────────────────────────────────


@router.delete(
    "/{subject_sub}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(recent_auth)],
    summary="Admin-assisted MFA reset (lost device)",
)
async def admin_reset(
    subject_sub: UUID,
    claims: Annotated[Claims, Depends(current_user)],
    actor: Annotated[Identity, Depends(current_identity)],
) -> Response:
    """Remove somebody else's second factor after out-of-band verification.

    Two rules, both about the same risk. The caller must administer a
    workspace the subject is actually in — an admin of one company cannot
    strip the MFA off a stranger. And **an owner's second factor can only
    be removed by another owner**: an admin who could reset an owner's MFA
    could reset it, sign in as them (with a password reset or an emailed
    code), and promote themselves. That is a privilege-escalation path
    dressed up as a helpdesk action.
    """
    services = native_services()
    subject = await services.identities.get(subject_sub)
    if subject is None:
        raise as_problem(ApiError("not_found", 404, detail="no such account"))

    actor_memberships = {
        m.tenant_id: m for m in await services.identities.list_memberships(actor.id)
    }
    subject_memberships = {
        m.tenant_id: m for m in await services.identities.list_memberships(subject.id)
    }
    shared = set(actor_memberships) & set(subject_memberships)
    manageable = [tid for tid in shared if actor_memberships[tid].role in {"owner", "admin"}]
    if not manageable:
        raise as_problem(
            ApiError(
                "not_a_member",
                403,
                detail="you do not administer a workspace this person belongs to",
            )
        )
    subject_is_owner = any(subject_memberships[tid].role == "owner" for tid in manageable)
    actor_is_owner = any(actor_memberships[tid].role == "owner" for tid in manageable)
    if subject_is_owner and not actor_is_owner:
        raise as_problem(
            ApiError(
                "owner_reset_requires_owner",
                403,
                detail="only another owner can reset an owner's second factor",
            )
        )

    try:
        await services.mfa.disable(subject, method="totp", code="", by_admin=True)
    except ApiError as exc:
        raise as_problem(exc) from exc
    revoked = await services.account.revoke_other_sessions(
        subject, current_sid=None, reason="mfa_change"
    )
    await audit(
        tenant_id=claims.tid,
        kind=audit_kinds.USER_RESET_MFA,
        payload={
            "identity_id": str(subject.id),
            "by": "admin",
            "sessions_revoked": revoked,
        },
        severity=Severity.SEC,
        actor_sub=actor.id,
        target_id=subject.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
