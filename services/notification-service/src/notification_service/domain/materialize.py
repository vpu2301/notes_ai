"""One domain fact to zero or more per-recipient notification rows.

Idempotent: the consumer is at-least-once, so a second call with the same event
must be a no-op that reports what the first did.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import asyncpg

from notification_events import Category, NotificationEvent

from . import render
from . import repository as repo
from .catalog import RecipientRule, spec_for
from .preferences import ChannelDecision, SuppressReason, resolve

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Created:
    """A row this call inserted; carries the recipient because fan-out is keyed by it."""

    notification_id: UUID
    recipient_user_id: UUID


@dataclass(slots=True)
class MaterializeResult:
    """What one event did; read by metrics and tests."""

    created: list[Created] = field(default_factory=list)
    # Rows that already existed (redelivery).
    duplicates: int = 0
    coalesced: int = 0
    # Outbox rows written as `suppressed`.
    suppressed: int = 0
    recipients_considered: int = 0


async def resolve_recipients(event: NotificationEvent, conn: asyncpg.Connection) -> list[UUID]:
    """Who hears about this fact; producer hints are filtered to the tenant's own members."""
    spec = spec_for(event.category)

    match spec.recipient_rule:
        case RecipientRule.TENANT_ADMINS:
            recipients = await repo.tenant_admin_ids(conn)
        case RecipientRule.NOTE_PARTICIPANTS | RecipientRule.EXPLICIT_HINTS:
            # Hints keep this service out of note-service's tables.
            recipients = await repo.filter_to_tenant_members(conn, event.recipient_hints)

    if spec.exclude_actor and event.actor_user_id is not None:
        recipients = [r for r in recipients if r != event.actor_user_id]

    # Dedupe, order-preserving.
    seen: set[UUID] = set()
    unique: list[UUID] = []
    for r in recipients:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


async def materialize(
    event: NotificationEvent,
    *,
    conn: asyncpg.Connection,
    redis: object | None = None,
    app_base_url: str,
    rate_cap: int = 0,
    rate_window_s: int = 300,
    now: datetime | None = None,
) -> MaterializeResult:
    """Turn one event into rows. Safe to call repeatedly with the same event."""
    at = now or datetime.now(UTC)
    result = MaterializeResult()
    spec = spec_for(event.category)

    recipients = await resolve_recipients(event, conn)
    result.recipients_considered = len(recipients)
    if not recipients:
        # Not an error: many facts interest nobody.
        logger.debug(
            "materialize.no_recipients",
            extra={"event_id": str(event.event_id), "category": str(event.category)},
        )
        return result

    title = render.render_title(event)
    body = render.render_body(event)
    link = render.deep_link(event, base_url=app_base_url)
    severity = render.severity_for(event)
    # Persisted so the email channel re-renders from the same allow-listed pointers.
    fields = render.safe_payload(event)

    for recipient in recipients:
        over_cap = False
        if rate_cap > 0 and redis is not None:
            over_cap = await _over_rate_cap(
                redis,
                tenant_id=event.tenant_id,
                recipient=recipient,
                category=event.category,
                cap=rate_cap,
                window_s=rate_window_s,
            )

        if over_cap:
            await _coalesce(
                conn,
                event=event,
                recipient=recipient,
                link=link,
                severity=severity,
                at=at,
            )
            result.coalesced += 1
            continue

        notification_id = await repo.insert_notification(
            conn,
            tenant_id=event.tenant_id,
            recipient_user_id=recipient,
            category=event.category,
            dedupe_key=event.dedupe_key(recipient),
            title=title,
            body_text=body,
            deep_link=link,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            severity=severity,
            render_fields=fields,
        )
        if notification_id is None:
            # Redelivery: outbox rows were written with the row; re-deriving them would double-send.
            result.duplicates += 1
            continue

        result.created.append(Created(notification_id=notification_id, recipient_user_id=recipient))
        result.suppressed += await _write_outbox(
            conn,
            event=event,
            recipient=recipient,
            notification_id=notification_id,
            at=at,
        )

    logger.info(
        "materialize.done",
        extra={
            "event_id": str(event.event_id),
            "category": str(event.category),
            # Not "created": logging reserves that LogRecord attribute and raises KeyError.
            "created_count": len(result.created),
            "duplicates": result.duplicates,
            "coalesced": result.coalesced,
            "rule": str(spec.recipient_rule),
        },
    )
    return result


async def _write_outbox(
    conn: asyncpg.Connection,
    *,
    event: NotificationEvent,
    recipient: UUID,
    notification_id: UUID,
    at: datetime,
) -> int:
    """Write one outbox row per channel. Returns the suppressed count."""
    preference = await repo.load_preference(conn, user_id=recipient, category=event.category)
    settings = await repo.load_settings(conn, user_id=recipient)
    email = await repo.user_email(conn, recipient)

    in_app_decision, email_decision = resolve(
        category=event.category,
        preference=preference,
        settings=settings,
        now=at,
        has_email_address=email is not None,
    )

    suppressed = 0
    for decision in (in_app_decision, email_decision):
        suppressed += await _write_one(
            conn,
            tenant_id=event.tenant_id,
            notification_id=notification_id,
            decision=decision,
            at=at,
        )
    return suppressed


async def _write_one(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    notification_id: UUID,
    decision: ChannelDecision,
    at: datetime,
) -> int:
    if not decision.dispatch:
        # Written, not skipped: the suppressed row is the auditable proof.
        await repo.insert_outbox(
            conn,
            tenant_id=tenant_id,
            notification_id=notification_id,
            channel=decision.channel,
            status="suppressed",
            suppressed_reason=str(decision.reason or ""),
            next_attempt_at=None,
        )
        return 1

    await repo.insert_outbox(
        conn,
        tenant_id=tenant_id,
        notification_id=notification_id,
        channel=decision.channel,
        status="pending",
        # Quiet-hours deferral keeps its reason for operators.
        suppressed_reason=(
            str(decision.reason) if decision.reason is SuppressReason.QUIET_HOURS else ""
        ),
        next_attempt_at=decision.not_before or at,
    )
    return 0


async def _coalesce(
    conn: asyncpg.Connection,
    *,
    event: NotificationEvent,
    recipient: UUID,
    link: str,
    severity: str,
    at: datetime,
) -> None:
    """Fold a storm into one row per (recipient, category, window); dedupe_key is the window."""
    bucket = int(at.timestamp())
    key = f"coalesce:{event.category}:{recipient}:{bucket // 3600}"

    existing = await repo.notification_id_for_dedupe(conn, dedupe_key=key)
    if existing is None:
        await repo.insert_notification(
            conn,
            tenant_id=event.tenant_id,
            recipient_user_id=recipient,
            category=event.category,
            dedupe_key=key,
            title=render.coalesced_title(event.category, 1),
            body_text=render.coalesced_body(1),
            deep_link=link,
            resource_type=event.resource_type,
            resource_id=None,
            severity=severity,
        )
        return

    # Count re-read from the table so it survives a worker restart.
    count = await conn.fetchval(
        "SELECT count(*) FROM notifications "
        " WHERE recipient_user_id = $1 AND category = $2 AND created_at >= $3",
        recipient,
        str(event.category),
        at.replace(minute=0, second=0, microsecond=0),
    )
    await repo.bump_coalesced(
        conn,
        notification_id=existing,
        title=render.coalesced_title(event.category, int(count) + 1),
        body_text=render.coalesced_body(int(count) + 1),
    )


async def _over_rate_cap(
    redis: object,
    *,
    tenant_id: UUID,
    recipient: UUID,
    category: Category,
    cap: int,
    window_s: int,
) -> bool:
    """Fixed-window Redis counter per (tenant, recipient, category); COUNT(*) would slow as the storm grows."""
    key = f"mdx:notif:cap:{tenant_id}:{recipient}:{category}"
    count = await redis.incr(key)  # type: ignore[attr-defined]
    if int(count) == 1:
        await redis.expire(key, window_s)  # type: ignore[attr-defined]
    return int(count) > cap


__all__ = ["Created", "MaterializeResult", "materialize", "resolve_recipients"]
