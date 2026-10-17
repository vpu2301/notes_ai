"""MFA reminder notification producer (ADR-0029, fire-and-forget; the `mfa_reminders` row is the durable half).

The payload carries the requester's ROLE and a count, never a name.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
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


def workspace_notifier(redis: object | None) -> Any:
    """W2 producer for `InvitationService`: rows land where the recipient is a member (no cross-tenant read)."""

    async def notify(
        event: str,
        *,
        recipient: UUID,
        invitation: Any,
        actor: UUID,
        personal_tenant_id: UUID | None = None,
    ) -> None:
        if not settings.notifications_enabled or redis is None:
            return
        if event == "invited":
            if personal_tenant_id is None:
                return
            built = build_event(
                event_id=uuid4(),
                # The invitee's own Personal workspace: visible wherever they are.
                tenant_id=personal_tenant_id,
                category=Category.WORKSPACE_INVITED,
                actor_user_id=actor,
                resource_type="workspace_invitation",
                resource_id=invitation["id"],
                occurred_at=datetime.now(UTC),
                recipient_hints=(recipient,),
                payload={
                    "tenant_id": str(invitation["tenant_id"]),
                    "invitation_id": str(invitation["id"]),
                    "role": invitation["role"],
                },
            )
        else:
            built = build_event(
                event_id=uuid4(),
                tenant_id=invitation["tenant_id"],
                category=Category.WORKSPACE_INVITATION_ACCEPTED,
                actor_user_id=actor,
                resource_type="workspace_membership",
                resource_id=invitation["id"],
                occurred_at=datetime.now(UTC),
                recipient_hints=(recipient,),
                payload={"invitation_id": str(invitation["id"]), "role": invitation["role"]},
            )
        await publish_event(redis, built)  # type: ignore[arg-type]

    return notify


async def emit_member_removed(
    redis: object | None,
    *,
    personal_tenant_id: UUID,
    workspace_id: UUID,
    removed: UUID,
    actor: UUID,
) -> None:
    """Tell a removed person, in their Personal workspace; best-effort."""
    if not settings.notifications_enabled or redis is None:
        return
    event = build_event(
        event_id=uuid4(),
        tenant_id=personal_tenant_id,
        category=Category.WORKSPACE_MEMBER_REMOVED,
        actor_user_id=actor,
        resource_type="workspace",
        resource_id=workspace_id,
        occurred_at=datetime.now(UTC),
        recipient_hints=(removed,),
        payload={"tenant_id": str(workspace_id)},
    )
    try:
        await publish_event(redis, event)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 — the removal is already committed
        logger.warning("member_removed.publish_failed", extra={"error": str(exc)})
