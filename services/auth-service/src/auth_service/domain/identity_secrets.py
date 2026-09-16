"""Encrypting an identity's TOTP secret at rest (IDX-A5 F1).

The pack specifies a new, small AES-256-GCM helper keyed by
``AUTH_SECRETS_KEKS_JSON``. This repo already has that job solved:
``libs/crypto`` is the ADR-0011 envelope hierarchy (master key → tenant
KEK → per-object DEK), it is tested, a CI gate (``check-no-crypto``)
forbids reaching for ``cryptography.hazmat`` anywhere else, and
``auth_service.totp`` already packs TOTP secrets through it for the
sprint-16 Keycloak store. Adding a second key hierarchy would mean two
rotation stories, two failure modes, and a gate to argue with — so this
module is a thin adapter onto the existing one instead.

The one thing that does not fit is that ``Envelope`` keys on a tenant and
an identity has none: an identity exists before it has a workspace, and
may belong to several. Identity secrets are therefore wrapped under the
**platform tenant's** KEK — the same tenant that owns identity-level
audit events, for the same reason. The tenant used is recorded per row
(``identity_totp.kek_tenant_id``) so a re-key never has to guess.

The AAD binds each ciphertext to the identity it belongs to, so a blob
copied from one row to another fails to decrypt rather than silently
becoming somebody else's second factor.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from .. import totp


class EnvelopeSecretBox:
    """The :class:`~auth_service.domain.mfa_service.SecretBox` Protocol,
    backed by ``libs/crypto``."""

    def __init__(self, *, envelope_provider: Any, kek_tenant_id: UUID) -> None:
        # A provider rather than an envelope: `ServiceState.get_envelope`
        # builds it on first use, so a deployment that never enables MFA
        # never needs the master key mounted.
        self._provider = envelope_provider
        self._kek_tenant_id = kek_tenant_id

    async def seal(self, *, secret: str, identity_id: UUID) -> tuple[str, UUID]:
        envelope = await self._provider()
        packed = await totp.encrypt_secret(
            envelope, secret=secret, tenant_id=self._kek_tenant_id, sub=identity_id
        )
        return packed, self._kek_tenant_id

    async def open(self, *, sealed: str, identity_id: UUID, kek_tenant_id: UUID) -> str:
        """Decrypt under the tenant KEK the row was written with.

        ``kek_tenant_id`` comes from the row, not from configuration: if
        the platform tenant is ever re-pointed, rows written before the
        change must still open.
        """
        envelope = await self._provider()
        return await totp.decrypt_secret(
            envelope, packed=sealed, tenant_id=kek_tenant_id, sub=identity_id
        )
