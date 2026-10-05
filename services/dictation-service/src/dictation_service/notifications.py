"""Completion notification for streaming dictation sessions.

Called from the handler, not the finalizer, so failed/abandoned sessions
never emit it. Fire-and-forget (ADR-0029): a bus outage never fails finalize.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from notification_events import Category, build_event, publish_event

from .config import settings

logger = logging.getLogger(__name__)


async def emit_dictation_completed(
    redis: object,
    *,
    tenant_id: UUID,
    session_id: UUID,
    user_id: UUID,
    duration_ms: int,
    segments: int,
) -> None:
    """Tell the dictating user their session finished.

    Payload carries duration + segment count and no transcript: it is
    persisted on the notification row (ADR-0031).
    """
    if not settings.notifications_enabled:
        return

    event = build_event(
        event_id=uuid4(),
        tenant_id=tenant_id,
        category=Category.DICTATION_COMPLETED,
        # Actor is the audience; the category sets exclude_actor=False.
        actor_user_id=user_id,
        resource_type="dictation_session",
        resource_id=session_id,
        occurred_at=datetime.now(UTC),
        recipient_hints=(user_id,),
        payload={"duration_ms": duration_ms, "segments": segments},
    )
    await publish_event(redis, event)
