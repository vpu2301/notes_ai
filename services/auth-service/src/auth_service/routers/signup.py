"""`POST /auth/signup`, `/auth/signup/verify`, `/auth/signup/resend` (keycloak/dual modes).

Uniform 202 whether or not the address has an account; deciding lives in
:mod:`auth_service.domain.onboarding_service`.
"""

from __future__ import annotations

import asyncio
import logging
import time
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
    # Upper bound guards the hasher; the lower bound is NOT the policy minimum
    # (the policy gives a field-level reason, Pydantic would 422 first).
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    # Mail language (no session to infer it from).
    lang: Literal["en", "de", "uk"] | None = None
    # Referral code from a shared note's CTA; opaque, 12 base32 characters.
    ref: str | None = Field(default=None, pattern=r"^[a-z2-7]{12}$")


class SignupResponse(_Strict):
    """Identical for every address. Nothing here varies by branch."""

    status: Literal["verification_sent"] = "verification_sent"
    resend_after: int


class VerifyRequest(_Strict):
    email: EmailStr
    # Accepts the grouped form the mail shows ("482 913").
    code: str = Field(min_length=1, max_length=32)


class VerifyResponse(_Strict):
    verified: Literal[True] = True


class ResendRequest(_Strict):
    email: EmailStr
    lang: Literal["en", "de", "uk"] | None = None


class SignupPublicConfig(_Strict):
    """What the SPA needs to pick a form: signup, or the lead capture."""

    enabled: bool
    min_password_length: int
    disposable_domains_blocked: Literal[True] = True


# ── helpers ──────────────────────────────────────────────────────────────


def _resolve_ip(request: Request) -> str:
    """The address the per-IP cap is keyed on; ``X-Forwarded-For`` only from ``TRUSTED_PROXY_CIDRS`` peers."""
    resolved: str = client_ip(
        peer=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxies=parse_cidrs(settings.trusted_proxy_cidrs),
    )
    return resolved


def _service() -> Any:
    """The wired :class:`OnboardingService`, or 404 (not 503) when there is none."""
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
    started = time.monotonic()
    try:
        await service.signup(
            email=str(body.email),
            password=body.password,
            display_name=body.display_name,
            locale=lang,
            ip=_resolve_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            lang=lang,
            ref_code=body.ref,
        )
    except SignupError as exc:
        if exc.code == "email_taken":
            # Keycloak knew the address though our lookup did not: a 409 would leak.
            logger.info("auth.signup.race_existing")
            await _hold_until_floor(started)
            return SignupResponse(resend_after=settings.signup_resend_seconds)
        raise _as_problem(exc) from exc
    # The branches do different amounts of work; a response-time floor hides that.
    await _hold_until_floor(started)
    return SignupResponse(resend_after=settings.signup_resend_seconds)


async def _hold_until_floor(started: float) -> None:
    remaining = settings.signup_min_response_ms / 1000 - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)


@router.get("/config", response_model=SignupPublicConfig, summary="Is self-serve signup on here?")
async def signup_config() -> SignupPublicConfig:
    """Answers in every mode and never 404s: the SPA's `/join` shows the
    signup form when this says `enabled`, and the Sprint 19 lead form
    otherwise. Nothing here is secret."""
    return SignupPublicConfig(
        enabled=getattr(get_state(), "onboarding_service", None) is not None,
        min_password_length=settings.signup_min_password_length,
    )


@router.post(
    "/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Spend the confirmation code and enable the account",
)
async def verify(body: VerifyRequest, request: Request) -> VerifyResponse:
    service = _service()
    try:
        await service.verify(email=str(body.email), code=body.code, ip=_resolve_ip(request))
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
