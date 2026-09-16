"""The notices that go out when access to an account changes (IDX-A5).

Every mail here is sent to the address that would want to know, which is
not always the address that made the change: the email-change notice goes
to the address being *replaced*, because the person who still has that
mailbox is the one who can tell us it was not them.

Failure to send is never allowed to fail the operation. By the time these
are sent, the second factor is already gone or the address is already
changed; refusing the request at that point would leave the account in
the state the user asked to leave, and tell them it failed. The caller
records ``notify_failed`` on the audit row instead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..adapters.email import EmailProvider
from . import compose, mailing
from . import copy as copy_mod


class SecurityMailer:
    def __init__(
        self,
        provider: EmailProvider,
        *,
        reply_to: str,
        timeout_seconds: float,
        public_base_url: str,
    ) -> None:
        self._provider = provider
        self._reply_to = reply_to
        self._timeout = timeout_seconds
        self._public_base_url = public_base_url.rstrip("/")

    async def _send(self, kind: str, lang: str, *, to: str, fields: dict[str, object]) -> None:
        await mailing.send_rendered(
            self._provider,
            kind,
            lang,
            to=to,
            fields=dict(fields),
            reply_to=self._reply_to,
            timeout_seconds=self._timeout,
        )

    # ── MFA (the mfa_service.Notifier Protocol) ──────────────────────

    async def mfa_enabled(self, *, to: str, lang: str) -> None:
        await self._send(
            copy_mod.KIND_MFA_ENABLED,
            lang,
            to=to,
            fields=compose.mfa_enabled_fields(lang=lang, changed_at=datetime.now(UTC)),
        )

    async def mfa_disabled(self, *, to: str, lang: str, by_admin: bool) -> None:
        await self._send(
            copy_mod.KIND_MFA_DISABLED,
            lang,
            to=to,
            fields=compose.mfa_disabled_fields(
                lang=lang, changed_at=datetime.now(UTC), by_admin=by_admin
            ),
        )

    async def recovery_code_used(self, *, to: str, lang: str, remaining: int) -> None:
        await self._send(
            copy_mod.KIND_RECOVERY_CODE_USED,
            lang,
            to=to,
            fields=compose.recovery_code_used_fields(
                lang=lang, remaining=remaining, used_at=datetime.now(UTC)
            ),
        )

    # ── account (the account_service.AccountNotifier Protocol) ───────

    def revert_url(self, token: str) -> str:
        """Where the "this wasn't me" button points.

        At auth-service, not the SPA: the page it lands on has to act
        (restore the address, end every session) before it can show
        anything, and routing that through the app would mean the SPA
        holding a one-shot credential it has no other use for.
        """
        return f"{self._public_base_url}/auth/email/revert/{token}"

    async def email_changed(
        self, *, to_old: str, lang: str, new_email: str, token: str, ttl_seconds: int
    ) -> None:
        await self._send(
            copy_mod.KIND_EMAIL_CHANGED,
            lang,
            to=to_old,
            fields=compose.email_changed_fields(
                lang=lang,
                new_email=new_email,
                revert_url=self.revert_url(token),
                revert_ttl_seconds=ttl_seconds,
                changed_at=datetime.now(UTC),
            ),
        )

    async def account_deletion_scheduled(self, *, to: str, lang: str, purge_on: datetime) -> None:
        await self._send(
            copy_mod.KIND_ACCOUNT_DELETION,
            lang,
            to=to,
            fields=compose.account_deletion_fields(
                lang=lang, purge_on=purge_on, requested_at=datetime.now(UTC)
            ),
        )
