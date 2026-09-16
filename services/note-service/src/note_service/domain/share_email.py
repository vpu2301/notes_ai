"""Sending a note to somebody's inbox.

This is the server-side half of "Send" in the share modal. The clients
used to build a ``mailto:`` URL and hand it to the desktop mail client,
which is where two bugs lived: the mail was an unstyled draft the sender
still had to send, and on macOS the hand-off surfaces whatever Mail.app
already had open — an old draft, with an old attachment. Neither is
fixable in a ``mailto:``. Sending from here is.

Delivery is inline rather than queued, for the same reason auth-service
sends its codes inline: the person is watching the modal, and a queue
they wait on turns a slow relay into "sharing is broken" with no error
anywhere. The cost is that a relay hiccup is a visible per-recipient
failure they can retry, which is the honest one.
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

# How many mails are in flight at once. Not `len(recipients)`: every send
# opens its own SMTP connection, and a shared relay (Google Workspace,
# say) counts simultaneous connections from one account and starts
# refusing them. Four keeps a ten-recipient send inside a couple of relay
# round-trips without looking like a burst.
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
    """A rolling hourly cap per sender, counted in RECIPIENTS.

    Counting recipients rather than requests is the point: ten calls of
    one address and one call of ten addresses cost the same, so batching
    is not a way around the cap. Fails open on a Redis outage, like the
    clip limiter — a cache being down must not stop people sharing.
    """

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
    # Where this particular recipient should land. A member goes to the
    # note in the app; everyone else to the public link.
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
    """Render and deliver one share mail. Never raises.

    One bad address among five must not lose the other four, so a
    failure becomes a per-recipient status the sender can see and act
    on, not an exception that abandons the batch.
    """
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
                    # The recipient's instinct is to answer the person
                    # who shared, not a mailbox nobody reads.
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
        # Deliberately no address in the log line: the sender sees which
        # one failed in the response; the log sink does not need it.
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
    """Deliver the batch, a few at a time, in the order asked.

    Concurrent rather than sequential because five recipients should
    cost one relay round-trip's worth of latency and not five; bounded
    rather than unbounded for the reason in `_MAX_IN_FLIGHT`.
    """
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
