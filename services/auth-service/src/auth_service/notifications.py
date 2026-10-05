"""MFA reminder notification producer (ADR-0029, fire-and-forget; the `mfa_reminders` row is the durable half).

The payload carries the requester's ROLE and a count, never a name.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from notification_events import Category, build_event, publish_event

from .config import settings

logger = logging.getLogger(__name__)


async def emit_mfa_reminder(
    redis: object | None,
    *,
    tenant_id: UUID,
    subject_sub: UUID,
    actor_sub: UUID,
    actor_role: str,
    reminder_count: int,
) -> None:
    """Tell one user that an access review asked them to enrol MFA; the subject is the only recipient."""
    if not settings.notifications_enabled or redis is None:
        return

    event = build_event(
        event_id=uuid4(),
        tenant_id=tenant_id,
        category=Category.SECURITY_MFA_REMINDER,
        # Actor = reviewer, audience = subject.
        actor_user_id=actor_sub,
        resource_type="user",
        resource_id=subject_sub,
        occurred_at=datetime.now(UTC),
        recipient_hints=(subject_sub,),
        payload={"requested_by_role": actor_role, "reminder_count": reminder_count},
    )
    try:
        await publish_event(redis, event)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 — the reminder row is already committed
        logger.warning("mfa_reminder.publish_failed", extra={"error": str(exc)})
