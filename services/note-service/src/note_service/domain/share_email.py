"""Sending a note to somebody's inbox: the server side of "Send" in the share
modal. Delivery is inline, not queued: a relay hiccup is a visible per-recipient
failure the sender can retry.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from opentelemetry import metrics
from redis.asyncio import Redis

from ..adapters import share_mail
from ..adapters.email import EmailPermanentError, EmailProvider, OutboundEmail

logger = logging.getLogger(__name__)

WINDOW_S = 3600

# Every send opens its own SMTP connection and a shared relay refuses bursts from one account.
_MAX_IN_FLIGHT = 4

_meter = metrics.get_meter("mdx.note.share_mail")
_sent_counter = _meter.create_counter(
    "mdx_note_share_emails_total",
    description="Share mails handed to the provider (labels: access, outcome)",
    unit="1",
)
_send_histogram = _meter.create_histogram(
    "mdx_note_share_email_send_seconds",
    description="Wall time of one inline share-mail send",
    unit="s",
)


class ShareEmailRateLimiter:
    """A rolling hourly cap per sender, counted in RECIPIENTS (batching is no way
    around it). Fails open on a Redis outage."""

    def __init__(self, redis: Redis, *, per_hour: int = 60) -> None:
        self._redis = redis
        self._per_hour = per_hour

    async def check(self, *, user_id: UUID, cost: int) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        bucket = int(time.time() // WINDOW_S)
        key = f"note:share-mail-rl:{user_id}:{bucket}"
        try:
            count = await self._redis.incrby(key, cost)
            if count == cost:
                await self._redis.expire(key, WINDOW_S + 60)
        except Exception as exc:  # noqa: BLE001 — fail open
            logger.warning("note.share_email_rate_limit_redis_error: %s", exc)
            return True, 0
        if count > self._per_hour:
            return False, WINDOW_S - int(time.time() % WINDOW_S)
        return True, 0


@dataclass(frozen=True, slots=True)
class Recipient:
    email: str
    # ``member`` | ``link`` — see adapters/share_mail_copy.
    access: str
    # A member lands on the note in the app; everyone else on their link.
    link_url: str


@dataclass(frozen=True, slots=True)
class SendOutcome:
    email: str
    access: str
    # ``sent`` | ``rejected`` (permanent, bad address) | ``failed``.
    status: str


async def send_one(
    provider: EmailProvider,
    recipient: Recipient,
    *,
    lang: str,
    sharer_name: str,
    sharer_email: str,
    note_title: str,
    message: str,
    shared_at: datetime,
    timeout_seconds: float,
) -> SendOutcome:
    """Render and deliver one share mail. Never raises: a failure is a per-recipient status."""
    rendered = share_mail.render(
        lang=lang,
        sharer_name=sharer_name,
        sharer_email=sharer_email,
        note_title=note_title,
        message=message,
        link_url=recipient.link_url,
        access=recipient.access,
        shared_at=shared_at,
    )
    started = time.perf_counter()
    try:
        await asyncio.wait_for(
            provider.send(
                OutboundEmail(
                    to_address=recipient.email,
                    subject=rendered.subject,
                    text_body=rendered.text_body,
                    html_body=rendered.html_body,
                    reply_to=sharer_email,
                )
            ),
            timeout=timeout_seconds,
        )
    except EmailPermanentError as exc:
        logger.warning(
            "note.share_mail.rejected",
            extra={"access": recipient.access, "error_class": type(exc).__name__},
        )
        _sent_counter.add(1, {"access": recipient.access, "outcome": "rejected"})
        return SendOutcome(email=recipient.email, access=recipient.access, status="rejected")
    except Exception as exc:  # noqa: BLE001
        # Deliberately no address in the log line.
        logger.error(
            "note.share_mail.send_failed",
            extra={"access": recipient.access, "error_class": type(exc).__name__},
        )
        _sent_counter.add(1, {"access": recipient.access, "outcome": "failed"})
        return SendOutcome(email=recipient.email, access=recipient.access, status="failed")
    finally:
        _send_histogram.record(time.perf_counter() - started, {"access": recipient.access})

    _sent_counter.add(1, {"access": recipient.access, "outcome": "sent"})
    return SendOutcome(email=recipient.email, access=recipient.access, status="sent")


async def send_many(
    provider: EmailProvider,
    recipients: list[Recipient],
    *,
    lang: str,
    sharer_name: str,
    sharer_email: str,
    note_title: str,
    message: str,
    shared_at: datetime,
    timeout_seconds: float,
) -> list[SendOutcome]:
    """Deliver the batch, `_MAX_IN_FLIGHT` at a time, in the order asked."""
    gate = asyncio.Semaphore(_MAX_IN_FLIGHT)

    async def one(recipient: Recipient) -> SendOutcome:
        async with gate:
            return await send_one(
                provider,
                recipient,
                lang=lang,
                sharer_name=sharer_name,
                sharer_email=sharer_email,
                note_title=note_title,
                message=message,
                shared_at=shared_at,
                timeout_seconds=timeout_seconds,
            )

    return list(await asyncio.gather(*(one(r) for r in recipients)))
