"""Ephemeral seekable AES-256-CTR for the in-process tmpfs ring buffer: unauthenticated, NOT for data at rest
(use :class:`Envelope`). Lives here so the ``check-no-direct-crypto`` gate stays strict.
"""

from __future__ import annotations

from secrets import token_bytes
from typing import Final

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CTR_BLOCK_SIZE: Final = 16
KEY_SIZE: Final = 32  # AES-256
NONCE_SIZE: Final = 8  # 8-byte fixed nonce + 8-byte counter = 16-byte counter input


def fresh_stream_key() -> bytes:
    """Return a 32-byte AES-256 key from a CSPRNG."""
    return token_bytes(KEY_SIZE)


def fresh_stream_nonce() -> bytes:
    """Return an 8-byte stream-nonce. Caller pairs it with an 8-byte counter."""
    return token_bytes(NONCE_SIZE)


def encryptor_at_offset(*, key: bytes, nonce: bytes, byte_offset: int) -> object:
    """AES-CTR encryptor positioned at ``byte_offset`` (must be a multiple of the 16-byte block)."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"key must be {KEY_SIZE} bytes")
    if len(nonce) != NONCE_SIZE:
        raise ValueError(f"nonce must be {NONCE_SIZE} bytes")
    if byte_offset % CTR_BLOCK_SIZE != 0:
        raise ValueError(f"byte_offset {byte_offset} not aligned to {CTR_BLOCK_SIZE}-byte block")
    block_index = byte_offset // CTR_BLOCK_SIZE
    counter = nonce + block_index.to_bytes(8, "big")
    return Cipher(algorithms.AES(key), modes.CTR(counter)).encryptor()
