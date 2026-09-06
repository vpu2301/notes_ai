"""The three mails BE-0 sends, rendered and delivered inline.

Inline rather than through the outbox worker that carries password mail,
for the same reason the sign-in code is inline (`CodeMailer`): a
confirmation code is useful for ten minutes and the person is watching the
page. A queue they wait on turns a slow relay into "signup is broken" with
no error anywhere. The cost is that a relay hiccup becomes a visible
failure they can retry, which is the honest one.

The two public-path mails are a matched pair. `/auth/signup` answers the
same ``202`` whether or not the address is registered, so the mailbox is
the only place the difference exists — and that only holds if both mails
go out on the same code path, under the same timeout, with the same
failure handling. They do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..adapters.email import EmailProvider
from . import compose, mailing
from . import copy as copy_mod


class SignupMailer:
    """Implements the ``SignupMailer`` protocol in ``onboarding_service``."""

    def __init__(
        self,
        provider: EmailProvider,
        *,
        reply_to: str,
        app_base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._provider = provider
        self._reply_to = reply_to
        self._app_base_url = app_base_url
        self._timeout = timeout_seconds

    async def _send(self, kind: str, lang: str, *, to: str, fields: dict[str, Any]) -> None:
        await mailing.send_rendered(
            self._provider,
            kind,
            lang,
            to=to,
            fields=fields,
            reply_to=self._reply_to,
            timeout_seconds=self._timeout,
        )

    async def send_verify(
        self, *, to: str, code: str, lang: str, user_agent: str, ttl_seconds: int
    ) -> None:
        await self._send(
            copy_mod.KIND_SIGNUP_VERIFY,
            lang,
            to=to,
            fields=compose.signup_verify_fields(
                lang=lang,
                code=code,
                ttl_seconds=ttl_seconds,
                user_agent=user_agent,
                requested_at=datetime.now(UTC),
            ),
        )

    async def send_exists(self, *, to: str, lang: str, user_agent: str) -> None:
        await self._send(
            copy_mod.KIND_SIGNUP_EXISTS,
            lang,
            to=to,
            fields=compose.signup_exists_fields(
                lang=lang,
                app_base_url=self._app_base_url,
                user_agent=user_agent,
                requested_at=datetime.now(UTC),
            ),
        )

    async def send_concierge(
        self, *, to: str, display_name: str, temporary_password: str, lang: str
    ) -> None:
        """The one mail an operator-created account gets.

        It carries a password, which no other mail in this service does,
        and that is the whole reason the concierge path is a CLI an
        operator runs rather than an endpoint anyone can call. The
        password is generated, sent once, and never logged or shown to the
        operator — so the only copy in existence is in the recipient's
        mailbox, and the change-password link is right beside it.
        """
        await self._send(
            copy_mod.KIND_CONCIERGE_WELCOME,
            lang,
            to=to,
            fields=compose.concierge_welcome_fields(
                lang=lang,
                display_name=display_name,
                temporary_password=temporary_password,
                app_base_url=self._app_base_url,
                created_at=datetime.now(UTC),
            ),
        )
