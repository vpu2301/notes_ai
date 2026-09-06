"""One place that turns a template kind into a sent message.

Account mail in this service is sent two ways: password recovery goes
through the durable outbox worker, and everything IDX-A3/A5 sends goes
inline. Inline, because these mails are all time-boxed — a sign-in code
lives ten minutes, a second-factor notice is only useful while the user
is still looking at the screen — and a queue the user waits on turns a
slow relay into "it's broken" with nothing in the logs.

The timeout is the whole reason this is not three lines at each call
site: without it a hung relay holds an HTTP worker until the client gives
up, and a handful of those takes the sign-in endpoint down.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from opentelemetry import metrics

from ..adapters import templates
from ..adapters.email import EmailProvider, OutboundEmail
from . import compose
from . import copy as copy_mod

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth")
_send_histogram = _meter.create_histogram(
    "mdx_auth_email_send_seconds",
    description="Wall time of an inline account-mail send",
    unit="s",
)
_failed_counter = _meter.create_counter(
    "mdx_auth_email_send_failed_total",
    description="Account mails that could not be sent",
    unit="1",
)


async def send_rendered(
    provider: EmailProvider,
    kind: str,
    lang: str,
    *,
    to: str,
    fields: dict[str, Any],
    reply_to: str,
    timeout_seconds: float,
) -> None:
    """Render ``kind`` in ``lang`` and send it, or raise.

    Raising is the contract: the caller decides whether a failed send
    aborts the operation (a sign-in code — no mail, no way in) or is
    merely noted (a "your second factor was removed" notice — the factor
    is already gone, and failing the request would leave the account in
    the state the user asked to leave).
    """
    rendered = templates.render(
        kind,
        lang,
        subject=copy_mod.subject_for(kind, lang),
        text_body=copy_mod.text_body(kind, lang, compose.text_values(kind, lang, fields, {})),
        context=fields,
    )
    started = time.perf_counter()
    try:
        await asyncio.wait_for(
            provider.send(
                OutboundEmail(
                    to_address=to,
                    subject=rendered.subject,
                    text_body=rendered.text_body,
                    html_body=rendered.html_body,
                    reply_to=reply_to,
                )
            ),
            timeout=timeout_seconds,
        )
    except Exception as exc:
        _failed_counter.add(1, {"template": kind})
        logger.error(
            "auth.mail.send_failed",
            extra={"template": kind, "error_class": type(exc).__name__},
        )
        raise
    finally:
        _send_histogram.record(time.perf_counter() - started, {"template": kind})
