"""Envelope encryption for data at rest (ADR-0011): master KEK → tenant KEK → per-object DEK; plus password verifiers."""

from __future__ import annotations

from .envelope import (
    ENVELOPE_ALGORITHM,
    ENVELOPE_VERSION,
    Envelope,
    EnvelopeBlob,
)
from .exceptions import (
    CryptoError,
    DecryptError,
    EnvelopeFormatError,
    MasterKeyError,
    MasterKeyPermissionError,
    TenantMismatchError,
)
from .master import (
    CompositeMasterKeyProvider,
    FileMasterKeyProvider,
    KmsMasterKeyProvider,
    MasterKeyProvider,
    build_master_key_provider,
)
from .passwords import hash_password, hash_password_async, needs_rehash
from .passwords import verify as verify_password
from .passwords import verify_async as verify_password_async
from .stream import encryptor_at_offset, fresh_stream_key, fresh_stream_nonce
from .tenant_kek import TenantKekRepository
from .vault_kv import fetch_kv_secrets

__all__ = [
    "CompositeMasterKeyProvider",
    "CryptoError",
    "DecryptError",
    "ENVELOPE_ALGORITHM",
    "ENVELOPE_VERSION",
    "Envelope",
    "EnvelopeBlob",
    "EnvelopeFormatError",
    "FileMasterKeyProvider",
    "KmsMasterKeyProvider",
    "MasterKeyError",
    "MasterKeyPermissionError",
    "MasterKeyProvider",
    "TenantKekRepository",
    "TenantMismatchError",
    "build_master_key_provider",
    "encryptor_at_offset",
    "fetch_kv_secrets",
    "fresh_stream_key",
    "fresh_stream_nonce",
    "hash_password",
    "hash_password_async",
    "needs_rehash",
    "verify_password",
    "verify_password_async",
]
