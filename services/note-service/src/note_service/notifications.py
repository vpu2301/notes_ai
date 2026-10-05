"""Notification emission for note lifecycle transitions, at the router layer.
Fire-and-forget: a note write must not fail because the bus is down (ADR-0029).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from notification_events import Category, build_event, publish_event

from .config import settings

logger = logging.getLogger(__name__)


async def emit_note_event(
    redis: object,
    *,
    category: Category,
    tenant_id: UUID,
    note_id: UUID,
    note_code: str,
    actor_user_id: UUID | None,
    primary_author_id: UUID | None = None,
    co_author_ids: tuple[UUID, ...] = (),
    version_id: UUID | None = None,
    extra_payload: dict[str, str | int | float | bool | None] | None = None,
) -> None:
    """Publish one note lifecycle fact. notification-service filters `recipient_hints`
    through its own tenant's users, so a wrong hint cannot address another tenant."""
    if not settings.notifications_enabled:
        return

    hints: list[UUID] = []
    if primary_author_id is not None:
        hints.append(primary_author_id)
    hints.extend(co_author_ids)

    # `note_code` ONLY, never the title: this payload reaches an email subject (ADR-0031).
    payload: dict[str, str | int | float | bool | None] = {"note_code": note_code}
    if extra_payload:
        payload.update(extra_payload)

    event = build_event(
        event_id=uuid4(),
        tenant_id=tenant_id,
        category=category,
        actor_user_id=actor_user_id,
        resource_type="note",
        resource_id=note_id,
        resource_version_id=version_id,
        occurred_at=datetime.now(UTC),
        recipient_hints=tuple(hints),
        payload=payload,
    )
    await publish_event(redis, event)


async def emit_budget_reached(
    redis: Any,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    spent_cents: int,
    budget_cents: int,
) -> bool:
    """Tell the workspace's admins that generation has stopped for money, once per
    workspace per month (Redis guard; losing it costs a duplicate banner). Returns
    whether it published."""
    if not settings.notifications_enabled:
        return False

    month = datetime.now(UTC).strftime("%Y-%m")
    try:
        first = await redis.set(f"ai:budget:{tenant_id}:{month}", b"1", nx=True, ex=40 * 86400)
    except Exception:  # noqa: BLE001 — a Redis outage must not stop the note
        logger.warning("ai_budget.guard_unavailable", extra={"tenant": str(tenant_id)})
        first = True
    if not first:
        return False

    await publish_event(
        redis,
        build_event(
            event_id=uuid4(),
            tenant_id=tenant_id,
            category=Category.AI_BUDGET_REACHED,
            actor_user_id=actor_user_id,
            resource_type="tenant",
            resource_id=tenant_id,
            occurred_at=datetime.now(UTC),
            recipient_hints=(),
            # Numbers only — never a note, never a meeting title.
            payload={"spent_cents": spent_cents, "budget_cents": budget_cents},
        ),
    )
    return True
