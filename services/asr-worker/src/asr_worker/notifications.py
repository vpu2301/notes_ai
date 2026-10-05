"""Notification emission for batch jobs; fire-and-forget, never fails a job (ADR-0029)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from notification_events import Category, build_event, publish_event

from .config import settings

logger = logging.getLogger(__name__)


async def emit_transcription_completed(
    redis: object,
    *,
    tenant_id: UUID,
    job_id: UUID,
    requester_sub: UUID,
    duration_ms: int,
    segments: int,
    language: str,
    model: str,
) -> None:
    """Tell the submitter their job produced a transcript."""
    await _emit(
        redis,
        category=Category.TRANSCRIPTION_COMPLETED,
        tenant_id=tenant_id,
        job_id=job_id,
        requester_sub=requester_sub,
        payload={
            "duration_ms": duration_ms,
            "segments": segments,
            "language": language,
            "model": model,
        },
    )


async def emit_transcription_failed(
    redis: object,
    *,
    tenant_id: UUID,
    job_id: UUID,
    requester_sub: UUID,
    error_kind: str,
) -> None:
    """Tell the submitter their job died. `error_kind` only, never the free-text detail (ADR-0031)."""
    await _emit(
        redis,
        category=Category.TRANSCRIPTION_FAILED,
        tenant_id=tenant_id,
        job_id=job_id,
        requester_sub=requester_sub,
        payload={"error_kind": error_kind},
    )


async def _emit(
    redis: object,
    *,
    category: Category,
    tenant_id: UUID,
    job_id: UUID,
    requester_sub: UUID,
    payload: dict[str, str | int | float | bool | None],
) -> None:
    if not settings.notifications_enabled:
        return

    event = build_event(
        event_id=uuid4(),
        tenant_id=tenant_id,
        category=category,
        # Submitter is both actor and audience; the catalog sets `exclude_actor=False`.
        actor_user_id=requester_sub,
        resource_type="transcription_job",
        resource_id=job_id,
        occurred_at=datetime.now(UTC),
        recipient_hints=(requester_sub,),
        payload=payload,
    )
    await publish_event(redis, event)
