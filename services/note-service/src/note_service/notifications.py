"""Sprint-12 notification emission for note lifecycle transitions.

Sits at the router layer, not in `domain/note_lifecycle.py`. The state
machine is a pure function of (conn, note_id, status) and has neither
the acting user nor the note's authors in scope; emitting from there
would mean re-reading the row and threading Redis through the domain
layer, inverting `routers → domain`.

Everything here is fire-and-forget: `publish_event` swallows its own
failures, and the callers do not await fan-out. Finalizing a note must
not fail because the notification bus is down (ADR-0029).
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
    """Publish one note lifecycle fact.

    `recipient_hints` carries the author set because note-service owns
    the `notes` row and already knows it. notification-service filters
    those ids through its own tenant's user table, so a stale or wrong
    hint can never address someone in another tenant.
    """
    if not settings.notifications_enabled:
        return

    hints: list[UUID] = []
    if primary_author_id is not None:
        hints.append(primary_author_id)
    hints.extend(co_author_ids)

    # `note_code` ONLY — never the note title. A user-authored title
    # routinely contains sensitive business content, and this payload
    # reaches an email subject line (ADR-0031).
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
    """Tell the workspace's admins that generation has stopped for money.

    Once per workspace per calendar month: the check runs on every
    enqueue, and a workspace that keeps recording would otherwise get one
    of these per meeting. The guard is a Redis key rather than a table —
    losing it costs a duplicate banner, which is the cheap failure.

    Returns whether it published, so callers can log the crossing rather
    than every attempt after it.
    """
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
