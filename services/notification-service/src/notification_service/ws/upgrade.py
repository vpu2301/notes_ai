"""Upgrade-time authorization for `/ws/notifications`, decided BEFORE `accept()`.

Order: origin, subprotocol, JWT; cheapest checks first so junk never touches the JWKS cache.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from starlette.websockets import WebSocket

from auth import (
    AuthError,
    Claims,
    ExpiredTokenError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    JwksCache,
    JwksFetchError,
    KidNotFoundError,
    MalformedClaimsError,
    verify_token,
)

from ..config import settings
from ..main_deps import auth_issuers
from .protocol import SUBPROTOCOL

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UpgradeContext:
    claims: Claims
    subprotocol: str
    client_ip: str
    origin: str | None


class UpgradeRejected(HTTPException):
    """Raised before accept(); Starlette turns it into a plain HTTP reply."""

    def __init__(self, status_code: int, code: str, detail: str = "") -> None:
        super().__init__(status_code=status_code, detail={"code": code, "detail": detail})
        self.code = code


def _parse_subprotocols(header: str | None) -> list[str]:
    if not header:
        return []
    return [p.strip() for p in header.split(",") if p.strip()]


def _extract_bearer(websocket: WebSocket) -> str | None:
    """Header first, then `?token=` (browsers cannot set handshake headers)."""
    auth = websocket.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = websocket.query_params.get("token")
    return token or None


async def authorize_upgrade(websocket: WebSocket, *, jwks_cache: JwksCache) -> UpgradeContext:
    origin = websocket.headers.get("origin")
    allowed = settings.cors_origins_list
    if allowed and origin is not None and origin not in allowed:
        raise UpgradeRejected(
            status.HTTP_403_FORBIDDEN, "origin_forbidden", f"origin {origin!r} not allowed"
        )

    offered = _parse_subprotocols(websocket.headers.get("sec-websocket-protocol"))
    if SUBPROTOCOL not in offered:
        # The subprotocol is the version negotiation.
        raise UpgradeRejected(
            status.HTTP_400_BAD_REQUEST,
            "unsupported_protocol",
            f"client must offer {SUBPROTOCOL!r}; got {offered!r}",
        )

    bearer = _extract_bearer(websocket)
    if bearer is None:
        raise UpgradeRejected(status.HTTP_401_UNAUTHORIZED, "auth_invalid", "missing bearer token")

    try:
        claims = await verify_token(
            bearer,
            jwks_cache=jwks_cache,
            # Same issuer list as the HTTP dependency.
            issuers=auth_issuers(),
            clock_skew_seconds=settings.auth_clock_skew_seconds,
        )
    except ExpiredTokenError as exc:
        raise UpgradeRejected(
            status.HTTP_401_UNAUTHORIZED, "token_expired", "token expired"
        ) from exc
    except (
        InvalidTokenError,
        InvalidIssuerError,
        InvalidAudienceError,
        KidNotFoundError,
        MalformedClaimsError,
        JwksFetchError,
        AuthError,
    ) as exc:
        logger.info(
            "ws.upgrade_rejected",
            extra={"reason": type(exc).__name__},
        )
        raise UpgradeRejected(
            status.HTTP_401_UNAUTHORIZED, "auth_invalid", "token rejected"
        ) from exc

    client_ip = websocket.client.host if websocket.client else "unknown"
    return UpgradeContext(
        claims=claims, subprotocol=SUBPROTOCOL, client_ip=client_ip, origin=origin
    )


def ws_code_for_http(http_code: int) -> int:
    """Map an HTTP rejection onto an RFC 6455 close code."""
    return {
        400: 4400,
        401: 4401,
        403: 4403,
        429: 4429,
    }.get(http_code, 1008)
