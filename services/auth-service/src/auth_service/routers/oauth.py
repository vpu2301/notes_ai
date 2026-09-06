"""`POST /auth/oauth/token` — RFC 6749 §4.4 client credentials (IDX-B1b F2).

The one endpoint in this service written to somebody else's spec. Room
devices and S2S callers already speak OAuth because Keycloak spoke it, so
the wire format is form-encoded, the errors use RFC 6749's `error` field
alongside our `code`, and HTTP Basic is accepted because that is what a
client configured against Keycloak sends today. Getting this shape right
is what lets a device be re-pointed by changing a URL.

No refresh token is issued, ever. A refresh token is for a principal that
cannot re-authenticate unattended; a machine holding its own secret can
ask again whenever it likes, so a second long-lived credential would be
all risk and no benefit.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Form, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from ratelimit import client_ip, parse_cidrs

from .. import audit_kinds
from ..config import settings
from ..domain.credential_service import CredentialError
from ..domain.errors import ApiError
from .native_common import as_problem, audit, native_services, platform_tenant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


class TokenGrantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


def _basic_credentials(header: str | None) -> tuple[str, str] | None:
    """`Authorization: Basic base64(client_id:client_secret)`, or None.

    RFC 6749 §2.3.1 prefers this over form fields, and a client set up
    against Keycloak sends it, so it has to work — but a malformed header
    is treated as "no credentials here" rather than an error, so the form
    fields still get their chance.
    """
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    client_id, sep, client_secret = raw.partition(":")
    return (client_id, client_secret) if sep else None


def _resolve_ip(request: Request) -> str:
    resolved: str = client_ip(
        peer=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxies=parse_cidrs(settings.trusted_proxy_cidrs),
    )
    return resolved


@router.post(
    "/token",
    response_model=TokenGrantResponse,
    summary="OAuth 2.0 token endpoint (client_credentials only)",
)
async def token(
    request: Request,
    response: Response,
    grant_type: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    client_secret: Annotated[str, Form()] = "",
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TokenGrantResponse:
    services = native_services()
    if services.credentials is None:
        raise as_problem(ApiError("invalid_request", 404, detail="Not Found"))

    if grant_type != "client_credentials":
        raise _oauth_problem(
            "unsupported_grant_type",
            400,
            detail="only grant_type=client_credentials is supported here",
        )

    basic = _basic_credentials(authorization)
    if basic is not None:
        client_id, client_secret = basic
    if not client_id or not client_secret:
        raise _oauth_problem(
            "invalid_request", 400, detail="client_id and client_secret are required"
        )

    ip = _resolve_ip(request)
    try:
        issued = await services.credentials.issue_token(
            client_id=client_id, client_secret=client_secret, ip=ip
        )
    except CredentialError as exc:
        # Every failed grant is an audit row on the platform tenant — the
        # credential may not exist, so there is no customer chain to write
        # to, and a burst of these is the shape of somebody guessing.
        await audit(
            tenant_id=platform_tenant(),
            kind=audit_kinds.AUTH_CLIENT_CREDENTIALS_FAILED,
            payload={
                "client_id": client_id[:64],
                "reason": exc.code,
                "ip_hash": _ip_hash(ip),
            },
            severity=Severity.WARN,
        )
        if getattr(exc, "tripped_lock", False):
            await audit(
                tenant_id=platform_tenant(),
                kind=audit_kinds.AUTH_CLIENT_LOCKED,
                payload={"client_id": client_id[:64], "ip_hash": _ip_hash(ip)},
                severity=Severity.SEC,
            )
        raise _oauth_problem(
            exc.code, exc.status_code, detail=exc.detail, retry_after=exc.retry_after
        ) from exc

    # RFC 6749 §5.1: token responses must not be cached anywhere.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TokenGrantResponse(access_token=issued.access_token, expires_in=issued.expires_in)


def _oauth_problem(
    code: str, status_code: int, *, detail: str, retry_after: int | None = None
) -> HTTPException:
    """An RFC 9457 problem that also carries RFC 6749's `error` field.

    Two vocabularies in one body on purpose: an OAuth client library
    branches on `error`, and everything else in this API branches on
    `code`. Emitting only ours would make a stock client report "unknown
    error" for a wrong secret.
    """
    exc = as_problem(ApiError(code, status_code, detail=detail, retry_after=retry_after))
    extras = getattr(exc, "problem_extras", {})
    extras["error"] = _OAUTH_ERROR.get(code, "invalid_request")
    extras["error_description"] = detail
    exc.problem_extras = extras  # type: ignore[attr-defined]
    if status_code == status.HTTP_401_UNAUTHORIZED:
        headers = dict(getattr(exc, "headers", None) or {})
        headers["WWW-Authenticate"] = 'Basic realm="mdx", charset="UTF-8"'
        exc.headers = headers
    return exc


# Our machine codes → the RFC 6749 §5.2 vocabulary. `client_locked`,
# `client_rate_limited` and `try_again` have no OAuth equivalent, so they
# map to the nearest truthful one and rely on `code` for the detail.
_OAUTH_ERROR = {
    "invalid_client": "invalid_client",
    "invalid_request": "invalid_request",
    "unsupported_grant_type": "unsupported_grant_type",
    "client_locked": "invalid_client",
    "client_rate_limited": "invalid_request",
    "try_again": "temporarily_unavailable",
}


def _ip_hash(ip: str) -> str:
    from ..domain import compose

    return compose.hash_ip(ip, salt=settings.password_reset_ip_hash_salt.value())
