"""Service-wide singletons for nlp-service."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg
import redis.asyncio as aioredis

from audit import AuditWriter
from auth import IssuerConfig, JwksCache, issuer_url_map, issuers_from_env
from db import create_pool

from .config import settings
from .domain import repository
from .pipeline.base import Stage
from .pipeline.orchestrator import Orchestrator
from .stages import (
    AbbreviationStage,
    ConfidenceStage,
    DateNormStage,
    FieldExtractionStage,
    NumberNormStage,
    PunctuationStage,
    VoiceCommandStage,
)
from .stages.voice_command_matcher import CommandSpec

logger = logging.getLogger(__name__)


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
class RedisCacheAdapter:
    """Implements ``CacheProtocol`` over the shared aioredis client."""

    redis: aioredis.Redis
    key_prefix: str

    async def get(self, key: str) -> bytes | None:
        value: bytes | None = await self.redis.get(f"{self.key_prefix}:{key}")
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self.redis.set(f"{self.key_prefix}:{key}", value, ex=ttl_seconds)


@dataclass
class ServiceState:
    jwks_cache: JwksCache
    app_pool: asyncpg.Pool
    audit_writer_pool: asyncpg.Pool
    audit_writer: AuditWriter
    redis: aioredis.Redis
    cache: RedisCacheAdapter
    orchestrator: Orchestrator
    punctuation_stage: PunctuationStage
    voice_specs_by_language: dict[str, list[CommandSpec]]


async def build_state() -> ServiceState:
    issuers = auth_issuers()
    # FND-1: log what this process will actually accept. During the
    # fleet-wide rollout of AUTH_ISSUERS_JSON "did this pod get the second
    # issuer?" has to be answerable from one log line, not from a token
    # that mysteriously 401s an hour later.
    logger.info("auth.issuers", extra={"trusted_issuers": [c.issuer for c in issuers]})
    jwks_cache = JwksCache(issuer_to_url=issuer_url_map(issuers))
    app_pool = await create_pool(
        settings.db_app_role_dsn,
        application_name=f"{settings.service_name}/app",
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    audit_writer_pool = await create_pool(
        settings.db_audit_writer_dsn,
        application_name=f"{settings.service_name}/audit_writer",
        min_size=1,
        max_size=4,
    )
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    cache = RedisCacheAdapter(redis=redis_client, key_prefix=settings.cache_key_prefix)

    # ── Build the 7-stage pipeline ─────────────────────────────────
    voice_specs = await repository.load_voice_commands(app_pool)

    punctuation = PunctuationStage()
    await punctuation.startup()  # eagerly load the model

    # Order is the contract (ADR-0028). field_extraction sits AFTER
    # abbreviation (it reads fully normalized text) and BEFORE confidence
    # (which must see the final text; extraction adds none).
    stages: list[Stage] = [
        VoiceCommandStage(specs_by_language=voice_specs),
        punctuation,
        NumberNormStage(),
        DateNormStage(),
        AbbreviationStage(),
        FieldExtractionStage(
            confidence_threshold=settings.extraction_confidence_threshold,
        ),
        ConfidenceStage(),
    ]
    orchestrator = Orchestrator(
        stages=stages,
        cache=cache,
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )

    return ServiceState(
        jwks_cache=jwks_cache,
        app_pool=app_pool,
        audit_writer_pool=audit_writer_pool,
        audit_writer=AuditWriter(audit_writer_pool),
        redis=redis_client,
        cache=cache,
        orchestrator=orchestrator,
        punctuation_stage=punctuation,
        voice_specs_by_language=voice_specs,
    )


async def teardown_state(state: ServiceState) -> None:
    await state.jwks_cache.aclose()
    await state.redis.aclose()
    await state.app_pool.close()
    await state.audit_writer_pool.close()
