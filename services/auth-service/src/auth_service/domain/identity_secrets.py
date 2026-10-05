"""Encrypting an identity's TOTP secret at rest via the ``libs/crypto`` envelope (ADR-0011).

Identities have no tenant, so secrets are wrapped under the platform tenant's KEK,
recorded per row. The AAD binds each ciphertext to its identity.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from .. import totp


class EnvelopeSecretBox:
    """:class:`~auth_service.domain.mfa_service.SecretBox` backed by ``libs/crypto``."""

    def __init__(self, *, envelope_provider: Any, kek_tenant_id: UUID) -> None:
        # A provider, not an envelope: built on first use (no master key needed without MFA).
        self._provider = envelope_provider
        self._kek_tenant_id = kek_tenant_id

    async def seal(self, *, secret: str, identity_id: UUID) -> tuple[str, UUID]:
        envelope = await self._provider()
        packed = await totp.encrypt_secret(
            envelope, secret=secret, tenant_id=self._kek_tenant_id, sub=identity_id
        )
        return packed, self._kek_tenant_id

    async def open(self, *, sealed: str, identity_id: UUID, kek_tenant_id: UUID) -> str:
        """Decrypt under the tenant KEK the row was written with (from the row, not configuration)."""
        envelope = await self._provider()
        return await totp.decrypt_secret(
            envelope, packed=sealed, tenant_id=kek_tenant_id, sub=identity_id
        )
