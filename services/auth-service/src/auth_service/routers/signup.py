"""`POST /auth/signup`, `/auth/signup/verify`, `/auth/signup/resend` (BE-0).

Self-serve account creation on the current stack. Keycloak stays the
identity provider, so a person who finishes this flow signs in with
``POST /auth/login`` on web, macOS and iOS with no client change at all —
which is the whole reason BE-0 exists ahead of the native path.

Thin, like every router in this service: deciding lives in
:mod:`auth_service.domain.onboarding_service`. Here we resolve who is
asking, translate refusals into RFC 9457 problems carrying the machine
codes ``docs/api/error-codes.md`` names, and nothing else.

── The uniform 202 ─────────────────────────────────────────────────────

`POST /auth/signup` answers ``202 {status: "verification_sent"}`` whether
or not the address already has an account, and `/resend` answers ``202``
whether or not there is anything to resend. Neither the body, the status,
nor the shape of the work distinguishes the branches — both do one lookup
and send one mail. Without that, signup is a membership oracle: point it
at a list of addresses and read off which ones are customers.

The cost is that a person who genuinely mistyped their address gets a 202
and no account. That is the right trade for an endpoint no one has to
authenticate to reach, and the mail they receive tells them which of the
two happened.

Mounted in ``keycloak`` and ``dual`` modes. Not in ``native``: there
Keycloak no longer holds credentials, and BE-3's ``/auth/email/*`` is the
way in.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ratelimit import client_ip, parse_cidrs

from ..config import settings
from ..deps import get_state
from ..domain import copy as copy_mod
from ..domain.onboarding_service import SignupError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/signup", tags=["auth"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignupRequest(_Strict):
    email: EmailStr
    # Bounded so a megabyte of "password" cannot be fed to the hasher.
    # The lower bound is deliberately NOT the policy minimum: the policy
    # answers with a field-level reason, and a 422 from Pydantic would
    # bypass it and say "string too short" instead.
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    # The interface language for the mail. There is no session to infer it
    # from — the person does not have an account yet.
    lang: Literal["en", "de", "uk"] | None = None


class SignupResponse(_Strict):
    """Identical for every address. Nothing here varies by branch."""

    status: Literal["verification_sent"] = "verification_sent"
    resend_after: int


class VerifyRequest(_Strict):
    email: EmailStr
    # Accepts the grouped form the mail shows ("482 913"); the service
    # strips separators before comparing.
    code: str = Field(min_length=1, max_length=32)


class VerifyResponse(_Strict):
    verified: Literal[True] = True


class ResendRequest(_Strict):
    email: EmailStr
    lang: Literal["en", "de", "uk"] | None = None


# ── helpers ──────────────────────────────────────────────────────────────


def _resolve_ip(request: Request) -> str:
    """The address the per-IP cap is keyed on.

    ``X-Forwarded-For`` is believed only when the peer is one of
    ``TRUSTED_PROXY_CIDRS``; otherwise it is client-supplied text and the
    cap would be a formality.
    """
    resolved: str = client_ip(
        peer=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxies=parse_cidrs(settings.trusted_proxy_cidrs),
    )
    return resolved


def _service() -> Any:
    """The wired :class:`OnboardingService`, or 404 when there is none.

    404 rather than 503, the posture the other optional routers take: a
    deployment with no mail relay, or one in native mode, should look
    like one that has no such endpoint, so a prober learns nothing about
    what is switched off.
    """
    service = getattr(get_state(), "onboarding_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return service


def _as_problem(exc: SignupError) -> HTTPException:
    http_exc = HTTPException(status_code=exc.status_code, detail=exc.detail)
    http_exc.problem_extras = {"code": exc.code, **exc.extras}  # type: ignore[attr-defined]
    if exc.retry_after is not None:
        http_exc.headers = {"Retry-After": str(exc.retry_after)}
    return http_exc


def _lang(request: Request, explicit: str | None) -> str:
    return copy_mod.normalise_lang(explicit or request.headers.get("accept-language"))


# ── routes ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=SignupResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an account; a confirmation code goes to the address",
)
async def signup(body: SignupRequest, request: Request) -> SignupResponse:
    service = _service()
    lang = _lang(request, body.lang)
    try:
        await service.signup(
            email=str(body.email),
            password=body.password,
            display_name=body.display_name,
            locale=lang,
            ip=_resolve_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            lang=lang,
        )
    except SignupError as exc:
        if exc.code == "email_taken":
            # Keycloak knew the address even though our lookup did not.
            # Answering 409 here would leak exactly what the uniform 202
            # exists to hide, so it is swallowed into the same reply. The
            # person has an account; the "you already have one" mail is
            # sent by the service on the branch it could detect, and this
            # is the narrow race where it could not.
            logger.info("auth.signup.race_existing")
            return SignupResponse(resend_after=settings.signup_resend_seconds)
        raise _as_problem(exc) from exc
    return SignupResponse(resend_after=settings.signup_resend_seconds)


@router.post(
    "/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Spend the confirmation code and enable the account",
)
async def verify(body: VerifyRequest, request: Request) -> VerifyResponse:
    service = _service()
    try:
        await service.verify(
            email=str(body.email), code=body.code, ip=_resolve_ip(request)
        )
    except SignupError as exc:
        raise _as_problem(exc) from exc
    return VerifyResponse()


@router.post(
    "/resend",
    response_model=SignupResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a fresh confirmation code",
)
async def resend(body: ResendRequest, request: Request) -> SignupResponse:
    service = _service()
    lang = _lang(request, body.lang)
    try:
        await service.resend(
            email=str(body.email),
            ip=_resolve_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            lang=lang,
        )
    except SignupError as exc:
        raise _as_problem(exc) from exc
    return SignupResponse(resend_after=settings.signup_resend_seconds)
