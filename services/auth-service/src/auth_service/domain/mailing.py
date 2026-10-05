"""Inline, time-boxed sending of a rendered template kind (password recovery uses the outbox instead).

The timeout is the point: a hung relay must not hold an HTTP worker.
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
    """Render ``kind`` in ``lang`` and send it, or raise; the caller decides whether that aborts."""
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
