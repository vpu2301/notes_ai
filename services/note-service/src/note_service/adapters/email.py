"""SMTP delivery for share mail.

The same provider shape auth-service uses for account mail — an ABC, an
aiosmtplib implementation, and a mock that REFUSES TO RUN IN PRODUCTION.
The refusal is the point: a mock that silently accepts mail in production
looks exactly like a working system while every share goes nowhere, and
nothing in the metrics distinguishes the two.

``reply_to`` is set per message rather than per provider, because a share
mail's natural reply address is the colleague who sent it, not a noreply
mailbox — the recipient's first instinct is to answer the person.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Final

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Transient failure — worth another attempt later."""


class EmailPermanentError(Exception):
    """The message will never be deliverable (bad address). Do not retry."""


@dataclass(frozen=True, slots=True)
class OutboundEmail:
    to_address: str
    subject: str
    text_body: str
    html_body: str = ""
    reply_to: str = ""


@dataclass(frozen=True, slots=True)
class SendResult:
    provider_message_id: str


class EmailProvider(ABC):
    @abstractmethod
    async def send(self, message: OutboundEmail) -> SendResult: ...

    @abstractmethod
    async def aclose(self) -> None: ...


def build_mime(
    message: OutboundEmail,
    *,
    from_address: str,
    from_name: str,
    reply_to_fallback: str = "",
    message_id: str | None = None,
    date: str | None = None,
) -> EmailMessage:
    """Assemble the MIME document.

    ``message_id`` and ``date`` are injectable so tests can assert on
    exact bytes; left alone they are generated. Generating them is not
    optional: ``Date`` is a REQUIRED header (RFC 5322 §3.6) and mail
    missing either it or ``Message-ID`` is scored as suspicious by every
    major provider — the share lands in spam, or nowhere, while the
    relay reports a clean 250 and the sender is told it went out.
    """
    mime = EmailMessage()
    mime["From"] = f"{from_name} <{from_address}>" if from_name else from_address
    mime["To"] = message.to_address
    mime["Subject"] = message.subject
    mime["Message-ID"] = message_id or make_msgid(domain=from_address.rsplit("@", 1)[-1])
    mime["Date"] = date or formatdate(localtime=True)
    # The sharer's own address, or the configured mailbox when they have
    # none on file — a share mail with no reply path at all leaves the
    # recipient answering into the void.
    reply_to = message.reply_to or reply_to_fallback
    if reply_to:
        mime["Reply-To"] = reply_to
    # A share mail is sent by a person pressing "Send", so it is NOT
    # Auto-Submitted: marking it auto-generated would suppress the
    # out-of-office reply the sender genuinely wants to see.
    mime.set_content(message.text_body)
    if message.html_body:
        mime.add_alternative(message.html_body, subtype="html")
    return mime


def ehlo_hostname(from_address: str) -> str:
    """The name we announce in EHLO. Never ``socket.getfqdn()``.

    Left to itself aiosmtplib resolves the local FQDN, and
    ``socket.getfqdn()`` does a reverse DNS lookup that BLOCKS — a flat
    30 seconds per message on a machine with no PTR record. The sending
    domain is the right answer anyway: stable, matching the envelope
    sender, and preferred by any receiving MTA that compares the two.
    """
    domain = from_address.rsplit("@", 1)[-1].strip()
    return domain or "localhost"


class SmtpProvider(EmailProvider):
    """aiosmtplib against a relay — Mailpit in dev, a real relay in prod."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        from_name: str = "",
        use_tls: bool = False,
        username: str = "",
        password: str = "",
        reply_to: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._from_address = from_address
        self._from_name = from_name
        self._reply_to = reply_to
        self._use_tls = use_tls
        self._username = username
        self._password = password
        self._timeout = timeout
        self._local_hostname = ehlo_hostname(from_address)

    async def send(self, message: OutboundEmail) -> SendResult:
        import aiosmtplib

        mime = build_mime(
            message,
            from_address=self._from_address,
            from_name=self._from_name,
            reply_to_fallback=self._reply_to,
        )
        # Port 465 is implicit TLS (the socket is wrapped before the
        # greeting); everything else negotiates STARTTLS. start_tls=True
        # on 465 tries to upgrade an already-encrypted connection and
        # fails with a protocol error that reads like bad credentials.
        implicit_tls = self._port == 465
        try:
            await aiosmtplib.send(
                mime,
                hostname=self._host,
                port=self._port,
                use_tls=implicit_tls,
                start_tls=True if (self._use_tls and not implicit_tls) else None,
                username=self._username or None,
                password=self._password or None,
                timeout=self._timeout,
                local_hostname=self._local_hostname,
            )
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            # 5xx is a permanent refusal — an unknown mailbox, or an
            # authentication rejection. The caller reports that one
            # address back to the sender instead of retrying it.
            if isinstance(code, int) and 500 <= code < 600:
                raise EmailPermanentError(f"smtp permanent {code}: {exc}") from exc
            raise EmailDeliveryError(f"smtp failure: {exc}") from exc

        return SendResult(provider_message_id=str(mime.get("Message-ID") or ""))

    async def aclose(self) -> None:
        # aiosmtplib.send() opens and closes a connection per call.
        return None


class MockProvider(EmailProvider):
    """Captures mail in memory. Refuses to exist in production."""

    def __init__(self, *, is_production: bool = False) -> None:
        if is_production:
            raise RuntimeError(
                "MockProvider must never be used in production — every shared "
                "note would be silently discarded while the sender was told it "
                "went out. Set MDX_EMAIL_PROVIDER=smtp."
            )
        self.sent: list[OutboundEmail] = []

    async def send(self, message: OutboundEmail) -> SendResult:
        self.sent.append(message)
        # The subject, never the body: the body carries a live share link.
        logger.info(
            "note.email.mock_send",
            extra={"to": message.to_address, "subject": message.subject},
        )
        return SendResult(provider_message_id=f"mock-{len(self.sent)}")

    async def aclose(self) -> None:
        return None


_SMTP: Final = "smtp"
_MOCK: Final = "mock"


def build_provider(
    *,
    kind: str,
    is_production: bool,
    host: str = "",
    port: int = 25,
    from_address: str = "",
    from_name: str = "",
    use_tls: bool = False,
    username: str = "",
    password: str = "",
    reply_to: str = "",
    timeout: float = 30.0,
) -> EmailProvider:
    if kind == _SMTP:
        return SmtpProvider(
            host=host,
            port=port,
            from_address=from_address,
            from_name=from_name,
            use_tls=use_tls,
            username=username,
            password=password,
            reply_to=reply_to,
            timeout=timeout,
        )
    if kind == _MOCK:
        return MockProvider(is_production=is_production)
    raise ValueError(f"unknown email provider {kind!r}; expected 'smtp' or 'mock'")
