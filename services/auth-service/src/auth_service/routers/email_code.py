"""`POST /auth/email/start` and `POST /auth/email/verify`: one pair serves signup and login,
and the response never says which. Deciding lives in :mod:`auth_service.domain.email_code_service`."""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from audit import Severity
from ratelimit import client_ip, parse_cidrs

from .. import audit_kinds
from ..config import settings
from ..deps import get_state
from ..domain import copy as copy_mod
from ..domain.email_code_service import EmailCodeError, VerifyResult
from ..domain.identity_repository import Membership
from ..domain.transport import (
    AuthResult,
    ClientType,
    IdentitySummary,
    MembershipSummary,
    client_type_of,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/email", tags=["auth"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartRequest(_Strict):
    email: EmailStr
    # Mail language (no session to infer it from).
    lang: Literal["en", "de", "uk"] | None = None


class StartResponse(_Strict):
    """Identical in shape for every address. The only varying field is the
    opaque challenge id, which is a fresh UUID either way."""

    challenge_id: str
    expires_in: int
    resend_after: int


class VerifyRequest(_Strict):
    challenge_id: UUID
    # Accepts the grouped form the mail shows ("482 913").
    code: str = Field(min_length=1, max_length=32)


# ── helpers ──────────────────────────────────────────────────────────────


def _resolve_ip(request: Request) -> str:
    """The address the rate-limit keys use; ``X-Forwarded-For`` only from ``TRUSTED_PROXY_CIDRS`` peers."""
    resolved: str = client_ip(
        peer=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxies=parse_cidrs(settings.trusted_proxy_cidrs),
    )
    return resolved


def _service() -> Any:
    """The wired :class:`EmailCodeService`, or 404 (not 503) if this deployment has none."""
    service = getattr(get_state(), "email_code_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return service


def _as_problem(exc: EmailCodeError) -> HTTPException:
    http_exc = HTTPException(status_code=exc.status_code, detail=exc.detail)
    http_exc.problem_extras = {"code": exc.code, **exc.extras}  # type: ignore[attr-defined]
    if exc.retry_after is not None:
        http_exc.headers = {"Retry-After": str(exc.retry_after)}
    return http_exc


def _membership_out(m: Membership) -> MembershipSummary:
    return MembershipSummary(
        tenant_id=str(m.tenant_id), name=m.name, kind=m.kind, role=m.role, status=m.status
    )


async def _audit(
    state: Any,
    *,
    tenant_id: UUID | str,
    kind: str,
    payload: dict[str, Any],
    severity: Severity,
    actor_sub: UUID | None = None,
    target_id: UUID | None = None,
) -> None:
    """Best-effort audit; never blocks a sign-in, but logs loudly."""
    try:
        await state.audit_writer.write_event(
            tenant_id=tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id)),
            kind=kind,
            actor_sub=actor_sub,
            target_kind="user",
            target_id=target_id,
            payload=payload,
            severity=severity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "auth.otp.audit_write_failed",
            extra={"kind": kind, "error_class": type(exc).__name__},
        )


# ── endpoints ────────────────────────────────────────────────────────────


@router.post(
    "/start",
    response_model=StartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a one-time sign-in code by email (signup and login both)",
)
async def start(body: StartRequest, request: Request) -> StartResponse:
    service = _service()
    state = get_state()
    client_type = client_type_of(request)
    try:
        result = await service.start(
            email=str(body.email),
            ip=_resolve_ip(request),
            client_type=str(client_type),
            lang=copy_mod.normalise_lang(body.lang),
            user_agent=request.headers.get("user-agent", ""),
        )
    except EmailCodeError as exc:
        raise _as_problem(exc) from exc

    # Platform tenant: the address may belong to nobody. Never the address in the payload.
    await _audit(
        state,
        tenant_id=settings.auth_platform_tenant_id,
        kind=audit_kinds.AUTH_OTP_REQUESTED,
        payload={"challenge_id": str(result.challenge_id), "client_type": str(client_type)},
        severity=Severity.INFO,
    )
    return StartResponse(
        challenge_id=str(result.challenge_id),
        expires_in=result.expires_in,
        resend_after=result.resend_after,
    )


@router.post(
    "/verify",
    response_model=AuthResult,
    summary="Exchange a one-time code for a session",
)
async def verify(body: VerifyRequest, request: Request, response: Response) -> AuthResult:
    service = _service()
    state = get_state()
    client_type = client_type_of(request)
    try:
        result: VerifyResult = await service.verify(
            challenge_id=body.challenge_id,
            code=body.code,
            ip=_resolve_ip(request),
            client_type=str(client_type),
            user_agent=request.headers.get("user-agent", ""),
            # The new workspace's locale; the timezone is NOT guessed (the welcome step sets it).
            locale=copy_mod.normalise_lang(request.headers.get("accept-language")),
        )
    except EmailCodeError as exc:
        if exc.code in {"code_invalid", "challenge_expired", "too_many_attempts"}:
            await _audit(
                state,
                tenant_id=settings.auth_platform_tenant_id,
                kind=audit_kinds.AUTH_OTP_FAILED,
                payload={"challenge_id": str(body.challenge_id), "outcome": exc.code},
                severity=Severity.WARN,
            )
        raise _as_problem(exc) from exc

    if result.mfa_challenge is not None:
        # Second factor owed: nothing about the account is disclosed.
        await _audit(
            state,
            tenant_id=settings.auth_platform_tenant_id,
            kind=audit_kinds.AUTH_MFA_CHALLENGED,
            payload={
                "challenge_id": str(result.mfa_challenge.challenge_id),
                "first_factor": "email_code",
            },
            severity=Severity.INFO,
        )
        return AuthResult.mfa_required(
            challenge_id=str(result.mfa_challenge.challenge_id),
            methods=list(result.mfa_challenge.methods),
            expires_in=result.mfa_challenge.expires_in,
        )

    assert result.session is not None  # only None on the mfa branch above
    await _write_success_audit(state, result)

    if not client_type.native:
        # Browsers: HttpOnly cookie, never the body. Native: body, never a cookie.
        response.set_cookie(
            key=settings.auth_cookie_name,
            value=result.session.refresh_token,
            max_age=result.session.refresh_expires_in,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,  # type: ignore[arg-type]
            path=settings.auth_cookie_path,
        )

    identity = result.identity
    return AuthResult.authenticated(
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
        memberships=[_membership_out(m) for m in result.memberships],
        is_new_identity=result.is_new_identity,
    )


async def _write_success_audit(state: Any, result: VerifyResult) -> None:
    """Signup, reactivation and login — each on the tenant it belongs to."""
    tenant_id = result.session.tenant_id
    identity_id = result.identity.id
    if result.is_new_identity:
        # On the NEW personal tenant: the first line of that workspace's history.
        await _audit(
            state,
            tenant_id=tenant_id,
            kind=audit_kinds.AUTH_SIGNUP,
            payload={"identity_id": str(identity_id), "tenant_id": str(tenant_id)},
            severity=Severity.INFO,
            actor_sub=identity_id,
            target_id=identity_id,
        )
    if result.reactivated:
        await _audit(
            state,
            tenant_id=tenant_id,
            kind=audit_kinds.AUTH_ACCOUNT_DELETION_CANCELLED,
            payload={"identity_id": str(identity_id)},
            severity=Severity.INFO,
            actor_sub=identity_id,
            target_id=identity_id,
        )
    await _audit(
        state,
        tenant_id=tenant_id,
        kind=audit_kinds.AUTH_LOGIN,
        payload={
            "method": "email_code",
            "identity_id": str(identity_id),
            "sid": str(result.session.session_id),
        },
        severity=Severity.INFO,
        actor_sub=identity_id,
        target_id=identity_id,
    )


__all__ = ["ClientType", "router"]
