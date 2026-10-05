"""Outbound mail for account-security notifications (service-local: services may not import services).

Security mail is never unsubscribable and suppresses auto-replies. The mock refuses to run in production.
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
    """Transient failure — the caller should retry with backoff."""


class EmailPermanentError(Exception):
    """The message will never be deliverable. Do not retry."""


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
    message_id: str | None = None,
    date: str | None = None,
) -> EmailMessage:
    """Assemble the MIME document; ``message_id``/``date`` are injectable for byte-exact tests."""
    mime = EmailMessage()
    mime["From"] = f"{from_name} <{from_address}>" if from_name else from_address
    mime["To"] = message.to_address
    mime["Subject"] = message.subject
    mime["Message-ID"] = message_id or make_msgid(domain=from_address.rsplit("@", 1)[-1])
    mime["Date"] = date or formatdate(localtime=True)
    if message.reply_to:
        mime["Reply-To"] = message.reply_to

    # Suppresses the recipient's out-of-office reply.
    mime["Auto-Submitted"] = "auto-generated"

    # Deliberately NO List-Unsubscribe: a security notification cannot be opted out of.

    mime.set_content(message.text_body)
    if message.html_body:
        mime.add_alternative(message.html_body, subtype="html")
    return mime


def ehlo_hostname(from_address: str) -> str:
    """The EHLO name: the sending domain, never ``socket.getfqdn()`` (its blocking PTR lookup stalls 30 s without a PTR record)."""
    domain = from_address.rsplit("@", 1)[-1].strip()
    return domain or "localhost"


class SmtpProvider(EmailProvider):
    """aiosmtplib against a relay — Mailpit in dev, Google Workspace in prod."""

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
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._from_address = from_address
        self._from_name = from_name
        self._use_tls = use_tls
        self._username = username
        self._password = password
        self._timeout = timeout
        self._local_hostname = ehlo_hostname(from_address)

    async def send(self, message: OutboundEmail) -> SendResult:
        import aiosmtplib

        mime = build_mime(message, from_address=self._from_address, from_name=self._from_name)
        # 465 is implicit TLS; start_tls=True on it makes aiosmtplib fail with a
        # protocol error that reads like a credentials problem.
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
            # 5xx is a permanent refusal: retrying burns attempts and reputation.
            if isinstance(code, int) and 500 <= code < 600:
                raise EmailPermanentError(f"smtp permanent {code}: {exc}") from exc
            raise EmailDeliveryError(f"smtp failure: {exc}") from exc

        return SendResult(provider_message_id=str(mime.get("Message-ID") or ""))

    async def aclose(self) -> None:
        return None


class MockProvider(EmailProvider):
    """Captures mail in memory. Refuses to exist in production."""

    def __init__(self, *, is_production: bool = False) -> None:
        if is_production:
            raise RuntimeError(
                "MockProvider must never be used in production — password-reset "
                "mail would be silently discarded while every metric reported "
                "success. Set MDX_EMAIL_PROVIDER=smtp."
            )
        self.sent: list[OutboundEmail] = []

    async def send(self, message: OutboundEmail) -> SendResult:
        self.sent.append(message)
        # The subject, never the body (which carries a live credential).
        logger.info(
            "auth.email.mock_send",
            extra={"to": message.to_address, "subject": message.subject},
        )
        return SendResult(provider_message_id=f"<mock-{len(self.sent)}@notes-ai.local>")

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
        )
    if kind == _MOCK:
        return MockProvider(is_production=is_production)
    raise ValueError(f"unknown email provider {kind!r}; expected 'smtp' or 'mock'")
