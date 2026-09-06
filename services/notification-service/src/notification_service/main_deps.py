"""Service state: pools, redis, auth, the socket registry, the fan-out bridge.

Kept out of main.py so routers can import the accessors without a
circular import at module-load time.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import asyncpg
from redis.asyncio import Redis
from starlette.requests import Request

from audit import AuditWriter
from auth import (
    Claims,
    IssuerConfig,
    JwksCache,
    build_current_user,
    build_session_denylist,
    issuer_url_map,
    issuers_from_env,
)
from db import create_pool

from .adapters.email import EmailProvider, build_provider
from .config import settings
from .ws.fanout import FanoutBridge
from .ws.registry import SocketRegistry

logger = logging.getLogger(__name__)

# What `auth.build_current_user` hands back: (request, authorization) -> Claims.
CurrentUserDep = Callable[[Request, str | None], Awaitable[Claims]]


def auth_issuers() -> list[IssuerConfig]:
    """The issuers this service trusts (FND-1 / ADR-0047).

    Built from ``AUTH_ISSUERS_JSON`` when it is set, otherwise from the
    single ``AUTH_ISSUER`` / ``AUTH_JWKS_URL`` / ``AUTH_AUDIENCE`` trio.
    Both the JWKS cache and ``build_current_user`` are built from THIS
    list, so the keys a token can be verified with and the issuers a
    token may claim can never drift apart.
    """
    return issuers_from_env(
        settings.auth_issuers_json,
        issuer=settings.auth_issuer,
        jwks_url=settings.auth_jwks_url,
        audience=settings.auth_audience,
    )


@dataclass(slots=True)
class ServiceState:
    app_pool: asyncpg.Pool
    audit_pool: asyncpg.Pool
    audit_writer: AuditWriter
    redis: Redis
    jwks_cache: JwksCache
    socket_registry: SocketRegistry
    fanout: FanoutBridge
    # Built once at startup rather than lazily attached to the state
    # object on first request — this dataclass uses slots, and more to
    # the point a dependency that appears mid-flight is harder to reason
    # about than one that exists from boot.
    current_user_dep: CurrentUserDep
    email_provider: EmailProvider
    # Mutable holder the ingest loop updates with the consumer-group
    # backlog, read by the mdx_notification_stream_pending gauge.
    stream_pending_ref: dict[str, int] = field(default_factory=lambda: {"value": 0})


async def build_state() -> ServiceState:
    app_pool = await create_pool(
        settings.db_app_role_dsn,
        application_name=f"{settings.service_name}/app",
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    audit_pool = await create_pool(
        settings.db_audit_writer_dsn,
        application_name=f"{settings.service_name}/audit",
        min_size=1,
        max_size=4,
    )
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    issuers = auth_issuers()
    # FND-1: log what this process will actually accept — see above.
    logger.info("auth.issuers", extra={"trusted_issuers": [c.issuer for c in issuers]})
    jwks_cache = JwksCache(issuer_to_url=issuer_url_map(issuers))

    return ServiceState(
        app_pool=app_pool,
        audit_pool=audit_pool,
        audit_writer=AuditWriter(audit_pool),
        redis=redis,
        jwks_cache=jwks_cache,
        socket_registry=SocketRegistry(),
        fanout=FanoutBridge(redis),
        email_provider=build_provider(
            kind=settings.email_provider,
            is_production=settings.is_production,
            host=settings.smtp_host,
            port=settings.smtp_port,
            from_address=settings.email_from,
            from_name=settings.email_from_name,
            use_tls=settings.smtp_use_tls,
            username=settings.smtp_username,
            password=settings.smtp_password,
        ),
        current_user_dep=build_current_user(
            jwks_cache=jwks_cache,
            # FND-1: the list, not a single string. The token's `iss`
            # picks the entry it is verified against.
            issuers=issuers,
            clock_skew_seconds=settings.auth_clock_skew_seconds,
            denylist=build_session_denylist(
                enabled=settings.session_revocation_enabled,
                redis_url=settings.redis_url,
            ),
        ),
    )


async def teardown_state(state: ServiceState) -> None:
    await state.fanout.stop()
    await state.email_provider.aclose()
    await state.jwks_cache.aclose()
    await state.redis.aclose()
    await state.app_pool.close()
    await state.audit_pool.close()


def observe(state: ServiceState) -> dict[str, Any]:
    """Snapshot for the fan-out gauges."""
    return {
        "connected_users": state.socket_registry.connected_user_count(),
        "connected_sockets": state.socket_registry.connected_socket_count(),
    }
