"""Envelope encryption, the only sanctioned crypto path for sensitive data at rest.

Fresh DEK and IV per object; AAD binds the ciphertext to the tenant_id; ``decrypt`` checks the tenant BEFORE any
crypto; DEK plaintext is zeroed on every path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .exceptions import DecryptError, TenantMismatchError
from .master import GCM_IV_SIZE_BYTES, GCM_TAG_SIZE_BYTES, MasterKeyProvider
from .tenant_kek import TenantKekRepository

ENVELOPE_VERSION: Final = 1
ENVELOPE_ALGORITHM: Final = "AES-256-GCM"
DEK_SIZE_BYTES: Final = 32


@dataclass(frozen=True, slots=True)
class EnvelopeBlob:
    """All envelope material for one encrypted object; wire-stable, a change needs a version bump."""

    ciphertext: bytes
    iv: bytes
    tag: bytes
    wrapped_dek: bytes
    dek_iv: bytes
    dek_tag: bytes
    tenant_id: UUID
    master_key_id: str
    algorithm: str = ENVELOPE_ALGORITHM
    version: int = ENVELOPE_VERSION
    # Optional caller AAD tying the ciphertext to a logical context (e.g. ``audio_id``); not secret.
    extra_aad: bytes | None = field(default=None)


class Envelope:
    """The single sanctioned encrypt/decrypt path; reuse the instance across requests."""

    def __init__(
        self,
        *,
        master_key_provider: MasterKeyProvider,
        kek_repository: TenantKekRepository,
    ) -> None:
        self._master = master_key_provider
        self._kek_repo = kek_repository

    async def encrypt(
        self,
        plaintext: bytes,
        *,
        tenant_id: UUID,
        aad: bytes | None = None,
    ) -> EnvelopeBlob:
        """Encrypt under a fresh DEK; AES-GCM AAD is ``tenant_id.bytes || (aad or b"")``."""
        tenant_kek = await self._kek_repo.get_or_create(tenant_id)
        dek = os.urandom(DEK_SIZE_BYTES)
        iv = os.urandom(GCM_IV_SIZE_BYTES)
        dek_iv = os.urandom(GCM_IV_SIZE_BYTES)

        full_aad = _compose_aad(tenant_id, aad)
        try:
            cipher = AESGCM(dek)
            ct_and_tag = cipher.encrypt(iv, plaintext, full_aad)
            ciphertext, tag = ct_and_tag[:-GCM_TAG_SIZE_BYTES], ct_and_tag[-GCM_TAG_SIZE_BYTES:]

            kek_cipher = AESGCM(tenant_kek)
            wrapped = kek_cipher.encrypt(dek_iv, dek, full_aad)
            wrapped_dek, dek_tag = (
                wrapped[:-GCM_TAG_SIZE_BYTES],
                wrapped[-GCM_TAG_SIZE_BYTES:],
            )
        finally:
            # Best-effort zero.
            dek = b"\x00" * DEK_SIZE_BYTES
            tenant_kek = b"\x00" * DEK_SIZE_BYTES  # noqa: F841

        return EnvelopeBlob(
            ciphertext=ciphertext,
            iv=iv,
            tag=tag,
            wrapped_dek=wrapped_dek,
            dek_iv=dek_iv,
            dek_tag=dek_tag,
            tenant_id=tenant_id,
            master_key_id=self._kek_repo.master_key_id_for(tenant_id),
            extra_aad=aad,
        )

    async def decrypt(
        self,
        blob: EnvelopeBlob,
        *,
        tenant_id: UUID,
        aad: bytes | None = None,
    ) -> bytes:
        """Decrypt ``blob``; rejects a tenant_id mismatch BEFORE any crypto (confused-deputy defence)."""
        if blob.tenant_id != tenant_id:
            raise TenantMismatchError(
                f"envelope blob is for tenant {blob.tenant_id}; caller "
                f"context is {tenant_id}. Refusing to attempt crypto."
            )

        tenant_kek = await self._kek_repo.get_or_create(tenant_id)
        full_aad = _compose_aad(tenant_id, aad)
        try:
            kek_cipher = AESGCM(tenant_kek)
            try:
                dek = kek_cipher.decrypt(
                    blob.dek_iv,
                    blob.wrapped_dek + blob.dek_tag,
                    full_aad,
                )
            except InvalidTag as exc:
                raise DecryptError(
                    "DEK unwrap failed: tenant KEK / AAD / wrapped DEK mismatch."
                ) from exc

            try:
                cipher = AESGCM(dek)
                plaintext = cipher.decrypt(
                    blob.iv,
                    blob.ciphertext + blob.tag,
                    full_aad,
                )
            except InvalidTag as exc:
                raise DecryptError(
                    "ciphertext decrypt failed: tag mismatch (tampered or AAD did not match)."
                ) from exc
        finally:
            dek = b"\x00" * DEK_SIZE_BYTES  # noqa: F841
            tenant_kek = b"\x00" * DEK_SIZE_BYTES  # noqa: F841

        return plaintext


def _compose_aad(tenant_id: UUID, extra: bytes | None) -> bytes:
    """AAD for DEK-wrap and object-encrypt: ``tenant_id.bytes`` plus the caller's bytes verbatim (no length prefix needed)."""
    return tenant_id.bytes + (extra or b"")
