"""Service-wide singletons."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg
from opentelemetry import metrics

from audit import AuditWriter, Severity
from auth import IssuerConfig, JwksCache, issuer_url_map, issuers_from_env
from db import create_pool

from . import audit_kinds
from .adapters.inference import InferenceClient, build_inference_client
from .config import settings
from .domain.rate_limit import InlineRateLimiter
from .domain.shown_audit import ShownAuditBuffer
from .domain.slots import SlotPool

logger = logging.getLogger(__name__)
_meter = metrics.get_meter("mdx.generation")


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

@dataclass
class ServiceState:
    jwks_cache: JwksCache
    audit_writer_pool: asyncpg.Pool
    audit_writer: AuditWriter
    redis: Any  # redis.asyncio.Redis
    # None when MDX_LAYER_C_ENABLED=false — the backend is never touched
    # (MDX_CONVERSATION_ENABLED precedent: off means never construct it).
    inference: InferenceClient | None
    slot_pool: SlotPool
    rate_limiter: InlineRateLimiter
    shown_audit: ShownAuditBuffer
    inline_latency_metric: Any
    completions_metric: Any
    # Sprint 16 pre-warm: readiness gates on this when MDX_PREWARM_ENABLED
    # (set false at startup by the lifespan, flipped true after the
    # 1-token warm completion lands).
    warmed: bool = True


async def build_state() -> ServiceState:
    issuers = auth_issuers()
    # FND-1: log what this process will actually accept. During the
    # fleet-wide rollout of AUTH_ISSUERS_JSON "did this pod get the second
    # issuer?" has to be answerable from one log line, not from a token
    # that mysteriously 401s an hour later.
    logger.info("auth.issuers", extra={"trusted_issuers": [c.issuer for c in issuers]})
    jwks_cache = JwksCache(issuer_to_url=issuer_url_map(issuers))
    audit_writer_pool = await create_pool(
        settings.db_audit_writer_dsn,
        application_name=f"{settings.service_name}/audit_writer",
        min_size=1,
        max_size=4,
    )
    audit_writer = AuditWriter(audit_writer_pool)

    from redis.asyncio import Redis

    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    inference: InferenceClient | None = None
    if settings.layer_c_enabled:
        inference = build_inference_client(settings)
    else:
        logger.warning(
            "generation-service started with MDX_LAYER_C_ENABLED=false — "
            "inline completions answer 204 and no inference backend is used"
        )

    async def _flush_shown(tenant_id: UUID, count: int) -> None:
        await audit_writer.write_event(
            tenant_id=tenant_id,
            kind=audit_kinds.LAYER_C_COMPLETION_SHOWN,
            payload={"count": count},
            severity=Severity.INFO,
        )

    shown_audit = ShownAuditBuffer(
        flush_fn=_flush_shown, flush_interval_s=settings.shown_audit_flush_s
    )
    shown_audit.start()

    # unit deliberately empty — the collector's prometheus exporter appends
    # unit names, which would break the dashboard-contract metric name
    # (…_inline_latency_ms_histogram_bucket). Values are ms; the "*latency*"
    # View in libs/observability supplies the ms bucket boundaries.
    inline_latency_metric = _meter.create_histogram(
        "mdx_layer_c_inline_latency_ms_histogram",
        description="End-to-end inline completion latency in ms (served only)",
        unit="",
    )
    completions_metric = _meter.create_counter(
        "mdx_layer_c_completions_total",
        description=(
            "Inline completion requests by outcome "
            "(served|empty|timeout|filtered|rate_limited|disabled|tenant_disabled|backend_error)"
        ),
        unit="1",
    )

    return ServiceState(
        jwks_cache=jwks_cache,
        audit_writer_pool=audit_writer_pool,
        audit_writer=audit_writer,
        redis=redis,
        inference=inference,
        slot_pool=SlotPool(settings.gen_slots),
        rate_limiter=InlineRateLimiter(
            redis,
            burst_per_second=settings.rate_burst_per_second,
            per_10s=settings.rate_per_10s,
        ),
        shown_audit=shown_audit,
        inline_latency_metric=inline_latency_metric,
        completions_metric=completions_metric,
    )


async def teardown_state(state: ServiceState) -> None:
    await state.shown_audit.stop()
    if state.inference is not None:
        await state.inference.aclose()
    await state.jwks_cache.aclose()
    await state.redis.aclose()
    await state.audit_writer_pool.close()
