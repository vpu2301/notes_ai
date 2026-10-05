"""Service-wide singletons for asr-worker."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from audit import AuditWriter
from crypto import Envelope, TenantKekRepository, build_master_key_provider
from db import create_pool
from diarization import (
    Diarizer,
    HttpDiarizer,
    LegacyEcapaDiarizer,
    PyannoteDiarizer,
    RosterGuardConfig,
)
from messaging import RedisStreamsConsumer, RedisStreamsProducer
from models import ASRProvider, Registry, build_asr_provider
from storage import EncryptedObjectStore, S3Client

from .config import settings
from .inference import WhisperEngine

logger = logging.getLogger(__name__)


@dataclass
class WorkerState:
    app_pool: asyncpg.Pool
    audit_writer_pool: asyncpg.Pool
    crypto_pool: asyncpg.Pool
    audit_writer: AuditWriter
    redis: aioredis.Redis
    producer: RedisStreamsProducer
    consumer: RedisStreamsConsumer
    s3: S3Client
    audio_store: EncryptedObjectStore
    transcript_store: EncryptedObjectStore
    envelope: Envelope
    # ASR seam (libs/models); the processor only sees the ASRProvider protocol.
    engine: ASRProvider
    # Never warmed at startup: a worker without the weights must still transcribe.
    diarizer: Diarizer
    # MDX_DIAR_SHADOW_ENGINE: labels discarded, counts only. None = off.
    shadow_diarizer: Diarizer | None = None
    # MDX_ASR_SHADOW_BACKEND: candidate ASR on a sample of jobs; numbers only. None = off.
    shadow_asr: ASRProvider | None = None
    # Silero VAD for the dual-channel analysis, built lazily.
    channel_segmenter: Any = None


DIARIZER_ENGINES = ("legacy", "pyannote", "http")


def build_diarizer(name: str) -> Diarizer:
    """Resolve an engine name; unknown names fail at startup, never on a job."""
    roster = RosterGuardConfig(
        min_speaker_speech_ms=settings.diar_min_speaker_speech_ms,
        min_speaker_share=settings.diar_min_speaker_share,
    )
    if name == "legacy":
        return LegacyEcapaDiarizer(
            model_dir=settings.diar_model_dir,
            device=settings.diar_device,
            pins={
                "embedding_model.ckpt": settings.diar_model_sha256,
                "mean_var_norm_emb.ckpt": settings.diar_meanvar_sha256,
            },
            model_repo=settings.diar_model_repo,
            model_revision=settings.diar_model_revision,
            roster=roster,
        )
    if name == "pyannote":
        return PyannoteDiarizer(
            model_dir=settings.diar_v2_model_dir,
            # Pinned by config.py (telemetry off, hub offline); the engine re-checks it.
            environ=settings.registry_environ(),
            device=settings.diar_device,
            pins=settings.diar_v2_pin_map(),
            model_repo=settings.diar_v2_model_repo,
            model_revision=settings.diar_v2_model_revision,
            batch_size=settings.diar_v2_batch_size(),
            roster=roster,
        )
    if name == "http":
        return _build_http_diarizer(roster)
    raise ValueError(f"MDX_DIAR_ENGINE={name!r} is not one of {', '.join(DIARIZER_ENGINES)}")


def _build_http_diarizer(roster: RosterGuardConfig) -> Diarizer:
    """Shape B (ADR-0052): the engine on an endpoint, resolved and validated at startup."""
    registry = Registry.load(
        settings.models_config,
        env=settings.registry_env(),
        environ=settings.registry_environ(),
        validate=False,
    )
    name = settings.diar_http_backend or registry.override_for("diarization")
    if not name:
        raise ValueError(
            "MDX_DIAR_ENGINE=http needs MDX_DIAR_HTTP_BACKEND "
            "(or a `diarization` env override in config/models.yaml)"
        )
    resolved = registry.backend(name, expect_kind="diarization")
    return HttpDiarizer(
        backend=resolved.name,
        base_url=resolved.config.base_url or "",
        model_id=resolved.model_id,
        # Bearer for the gateway, the server's own token for the container.
        auth_token=resolved.config.bearer_token(),
        server_token=settings.diar_http_token or None,
        cold_start_seconds=resolved.caps.cold_start_seconds,
        timeout_seconds=resolved.caps.timeout_seconds,
        seconds_per_audio_second=settings.diar_http_seconds_per_audio_second,
        roster=roster,
    )


def build_asr(backend_name: str) -> ASRProvider:
    """Resolve ``ASR_BACKEND`` through the registry; ``ConfigError`` before any job is claimed."""
    registry = Registry.load(
        settings.models_config,
        env=settings.registry_env(),
        environ=settings.registry_environ(),
        validate=False,  # only the ASR route matters to this worker
    )
    resolved = registry.backend(backend_name, expect_kind="asr")
    engine = WhisperEngine() if resolved.kind == "asr_inproc" else None
    return build_asr_provider(resolved, inproc_engine=engine)


async def build_state() -> WorkerState:
    app_pool = await create_pool(
        settings.db_app_role_dsn,
        application_name=f"{settings.service_name}/app",
        min_size=1,
        max_size=4,
    )
    audit_writer_pool = await create_pool(
        settings.db_audit_writer_dsn,
        application_name=f"{settings.service_name}/audit_writer",
        min_size=1,
        max_size=2,
    )
    crypto_pool = await create_pool(
        settings.db_crypto_writer_dsn,
        application_name=f"{settings.service_name}/crypto_writer",
        min_size=1,
        max_size=2,
    )
    master = build_master_key_provider(
        provider=settings.master_key_provider,
        file_path=settings.master_key_path,
        vault_addr=settings.vault_addr,
        vault_token=settings.vault_token,
        vault_transit_key=settings.vault_transit_key,
        vault_transit_mount=settings.vault_transit_mount,
    )
    await master.startup_self_check()

    kek_repo = TenantKekRepository(pool=crypto_pool, master_key_provider=master)
    envelope = Envelope(master_key_provider=master, kek_repository=kek_repo)

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    producer = RedisStreamsProducer(client=redis_client, default_stream=settings.asr_jobs_stream)
    consumer = RedisStreamsConsumer(
        client=redis_client,
        producer=producer,
        stream=settings.asr_jobs_stream,
        group=settings.asr_jobs_group,
        consumer=settings.worker_consumer_name,
        dlq_stream=settings.asr_jobs_dlq_stream,
        reclaim_idle_ms=settings.asr_jobs_idle_reclaim_ms,
        max_retries=settings.asr_jobs_max_retries,
    )

    s3 = S3Client(
        endpoint_url=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
        use_ssl=settings.s3_use_ssl,
    )
    audio_store = EncryptedObjectStore(s3=s3, bucket=settings.s3_audio_bucket, envelope=envelope)
    transcript_store = EncryptedObjectStore(
        s3=s3, bucket=settings.s3_transcripts_bucket, envelope=envelope
    )

    engine = build_asr(settings.asr_backend)
    await engine.warm_up()
    # Not warmed: a cold candidate must not hold up real jobs.
    shadow_name = settings.asr_shadow_backend.strip()
    shadow_asr = (
        build_asr(shadow_name) if shadow_name and shadow_name != settings.asr_backend else None
    )

    diarizer = build_diarizer(settings.diar_engine)
    shadow = settings.diar_shadow_engine.strip()
    shadow_diarizer = build_diarizer(shadow) if shadow and shadow != settings.diar_engine else None
    # No readiness endpoint; this line is how an operator confirms the engine.
    logger.info(
        "diarization.engine_selected",
        extra={
            "engine": diarizer.engine,
            "shadow_engine": shadow_diarizer.engine if shadow_diarizer else None,
        },
    )

    return WorkerState(
        app_pool=app_pool,
        audit_writer_pool=audit_writer_pool,
        crypto_pool=crypto_pool,
        audit_writer=AuditWriter(audit_writer_pool),
        redis=redis_client,
        producer=producer,
        consumer=consumer,
        s3=s3,
        audio_store=audio_store,
        transcript_store=transcript_store,
        envelope=envelope,
        engine=engine,
        diarizer=diarizer,
        shadow_diarizer=shadow_diarizer,
        shadow_asr=shadow_asr,
    )


async def teardown_state(state: WorkerState) -> None:
    closer = getattr(state.diarizer, "close", None)
    if closer is not None:
        closer()  # the remote engine holds a connection pool
    await state.producer.aclose()
    await state.redis.aclose()
    await state.app_pool.close()
    await state.audit_writer_pool.close()
    await state.crypto_pool.close()
    await state.s3.aclose()
