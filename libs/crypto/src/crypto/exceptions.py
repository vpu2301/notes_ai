"""Exception hierarchy for libs/crypto; messages never carry plaintext or key bytes."""

from __future__ import annotations


class CryptoError(Exception):
    """Base class for every libs/crypto failure."""


class MasterKeyError(CryptoError):
    """The master key file is missing, malformed, or otherwise unusable."""


class MasterKeyPermissionError(MasterKeyError):
    """Master key file has overly-permissive mode (must be ≤ 0400)."""


class EnvelopeFormatError(CryptoError):
    """The serialized envelope blob is malformed (bad header, truncated, …)."""


class DecryptError(CryptoError):
    """Decryption failed: wrong key, tampered ciphertext, bad AAD or tag mismatch."""


class TenantMismatchError(CryptoError):
    """The envelope's ``tenant_id`` does not match the caller's (confused-deputy defence)."""
