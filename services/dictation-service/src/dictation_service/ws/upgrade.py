"""WebSocket upgrade: auth, subprotocol negotiation, rate-limit.

Validated before ``accept()``; a rejection is a plain HTTP 400/401/429 and
writes ``dictation.upgrade.failed``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, WebSocket, status
from redis.asyncio import Redis

from audit import AuditWriter, Severity
from auth import Claims, JwksCache, verify_token
from auth.exceptions import (
    AuthError,
    ExpiredTokenError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    JwksFetchError,
    KidNotFoundError,
    MalformedClaimsError,
)

from .. import metrics
from ..audit_kinds import UPGRADE_FAILED
from ..config import settings
from ..main_deps import auth_issuers
from ..protocol.codec import (
    SUBPROTOCOL,
    SUBPROTOCOL_PREFERENCE,
    VERSION_BY_SUBPROTOCOL,
    negotiate_subprotocol,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UpgradeContext:
    """Everything the session handler needs once the upgrade succeeds."""

    claims: Claims
    subprotocol: str
    client_ip: str
    origin: str | None
    # The bearer is kept because conversation finalize drafts the note as the caller.
    protocol_version: int = VERSION_BY_SUBPROTOCOL[SUBPROTOCOL]
    bearer: str | None = None


class UpgradeRejected(HTTPException):
    """Raised before ``accept()`` — Starlette returns this as plain HTTP."""

    def __init__(self, status_code: int, code: str, detail: str = "") -> None:
        super().__init__(status_code=status_code, detail={"code": code, "detail": detail})
        self.code = code
        # Single choke point for every rejection, so the metric cannot drift.
        metrics.ws_upgrade_rejections.add(1, {"reason": code})


async def authorize_upgrade(
    websocket: WebSocket,
    *,
    jwks_cache: JwksCache,
    redis: Redis,
    audit_writer: AuditWriter,
) -> UpgradeContext:
    """Validate the upgrade or raise :class:`UpgradeRejected`.

    Order: rate limit, then subprotocol, then JWT (cheapest rejection first).
    """
    client_ip = _client_ip(websocket)
    origin = websocket.headers.get("origin")

    # Origin allow-list mirrors the frontend CORS list; no Origin passes in dev only.
    if (
        origin is not None
        and origin not in settings.ws_allowed_origins
        and settings.environment != "development"
    ):
        await _audit_upgrade_fail(
            audit_writer,
            tenant_id=None,
            user_sub=None,
            client_ip=client_ip,
            reason="origin_rejected",
            severity=Severity.WARN,
            origin=origin,
        )
        raise UpgradeRejected(
            status_code=status.HTTP_403_FORBIDDEN,
            code="origin_rejected",
            detail=f"origin {origin!r} is not in the allow-list",
        )

    # Per-IP rate limit.
    if not await _allow_ip(redis, client_ip):
        await _audit_upgrade_fail(
            audit_writer,
            tenant_id=None,
            user_sub=None,
            client_ip=client_ip,
            reason="rate_limited_ip",
            severity=Severity.SEC,
        )
        raise UpgradeRejected(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limited",
            detail="too many upgrade attempts from this IP",
        )

    # Subprotocol negotiation: server prefers v2 over v1 among what the client offers.
    offered = _parse_subprotocols(websocket.headers.get("sec-websocket-protocol"))
    negotiated = negotiate_subprotocol(offered)
    if negotiated is None:
        await _audit_upgrade_fail(
            audit_writer,
            tenant_id=None,
            user_sub=None,
            client_ip=client_ip,
            reason="subprotocol_missing",
            severity=Severity.WARN,
            offered=",".join(offered),
        )
        raise UpgradeRejected(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_protocol",
            detail=(
                f"client offered none of {list(SUBPROTOCOL_PREFERENCE)!r}; offered={offered!r}"
            ),
        )

    # Authorization header or ?token= (browsers cannot set headers on WS).
    bearer = _extract_bearer(websocket)
    if bearer is None:
        await _audit_upgrade_fail(
            audit_writer,
            tenant_id=None,
            user_sub=None,
            client_ip=client_ip,
            reason="auth_missing",
            severity=Severity.WARN,
        )
        raise UpgradeRejected(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth_invalid",
            detail="missing bearer token",
        )

    try:
        claims = await verify_token(
            bearer,
            jwks_cache=jwks_cache,
            # Same issuer list as the HTTP dependency.
            issuers=auth_issuers(),
            clock_skew_seconds=settings.auth_clock_skew_seconds,
        )
    except ExpiredTokenError as exc:
        await _audit_upgrade_fail(
            audit_writer,
            tenant_id=None,
            user_sub=None,
            client_ip=client_ip,
            reason="token_expired",
            severity=Severity.WARN,
        )
        raise UpgradeRejected(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth_invalid",
            detail="token expired",
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
        await _audit_upgrade_fail(
            audit_writer,
            tenant_id=None,
            user_sub=None,
            client_ip=client_ip,
            reason=f"auth_invalid:{type(exc).__name__}",
            severity=Severity.SEC,
        )
        raise UpgradeRejected(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth_invalid",
            detail=type(exc).__name__,
        ) from exc

    # Per-user rate limit.
    if not await _allow_user(redis, claims.sub):
        await _audit_upgrade_fail(
            audit_writer,
            tenant_id=claims.tid,
            user_sub=claims.sub,
            client_ip=client_ip,
            reason="rate_limited_user",
            severity=Severity.SEC,
        )
        raise UpgradeRejected(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limited",
            detail="too many upgrade attempts for this user",
        )

    return UpgradeContext(
        claims=claims,
        subprotocol=negotiated,
        client_ip=client_ip,
        origin=origin,
        protocol_version=VERSION_BY_SUBPROTOCOL[negotiated],
        bearer=bearer,
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _client_ip(websocket: WebSocket) -> str:
    """Best-effort client IP; honours leftmost X-Forwarded-For in dev only."""
    xff = websocket.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if websocket.client is None:
        return "unknown"
    return websocket.client.host


def _parse_subprotocols(header: str | None) -> list[str]:
    if not header:
        return []
    return [s.strip() for s in header.split(",") if s.strip()]


def _extract_bearer(websocket: WebSocket) -> str | None:
    auth = websocket.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # ?token= fallback for browsers (TLS only).
    token = websocket.query_params.get("token")
    return token if token else None


# ── Redis-backed rate limiters ───────────────────────────────────────


async def _allow_ip(redis: Redis, ip: str) -> bool:
    key = f"mdx:dict:rl:ip:{ip}:{int(time.time()) // 60}"
    return await _allow(redis, key, settings.upgrade_ratelimit_per_ip_per_minute, ttl=120)


async def _allow_user(redis: Redis, sub: UUID) -> bool:
    key = f"mdx:dict:rl:user:{sub}:{int(time.time()) // 3600}"
    return await _allow(redis, key, settings.upgrade_ratelimit_per_user_per_hour, ttl=3 * 3600)


async def _allow(redis: Redis, key: str, limit: int, *, ttl: int) -> bool:
    """Atomic INCR + EXPIRE; returns False once the bucket exceeds limit."""
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, ttl)
    results: list[Any] = await pipe.execute()
    current = int(results[0])
    return current <= limit


async def _audit_upgrade_fail(
    audit_writer: AuditWriter,
    *,
    tenant_id: UUID | None,
    user_sub: UUID | None,
    client_ip: str,
    reason: str,
    severity: Severity,
    **extra: object,
) -> None:
    """Write a `dictation.upgrade.failed` event; pre-auth failures (no tenant) only log."""
    payload: dict[str, object] = {
        "reason": reason,
        "client_ip": client_ip,
        **extra,
    }
    log_extra = {
        "reason": reason,
        "client_ip": client_ip,
        "tenant_id": str(tenant_id) if tenant_id else None,
        **{k: str(v) for k, v in extra.items()},
    }
    if tenant_id is None:
        logger.warning("dictation.upgrade.failed", extra=log_extra)
        return
    try:
        await audit_writer.write_event(
            tenant_id=tenant_id,
            kind=UPGRADE_FAILED,
            actor_sub=user_sub,
            target_kind="dictation_session",
            target_id=None,
            payload=payload,
            severity=severity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dictation.upgrade.failed.audit_write_failed",
            extra={"error": str(exc), "error_class": type(exc).__name__, **log_extra},
        )
