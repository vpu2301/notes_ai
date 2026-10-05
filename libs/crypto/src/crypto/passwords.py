"""Password verifiers (scrypt, stdlib): ``scrypt$n$r$p$<salt-b64>$<hash-b64>``; never decryptable, never under a KEK.

scrypt's working set is ``128 * n * r`` bytes; ``n=2**15`` (32 MiB) × :data:`MAX_CONCURRENT` keeps peak KDF memory
~128 MiB under auth-service's 512 MiB limit. Raise :data:`N` with the limit; :func:`needs_rehash` upgrades on sign-in.
:func:`verify` returns ``False`` for every failure and never raises (a raise would be an oracle).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
from typing import Final
from weakref import WeakKeyDictionary

SCHEME: Final = "scrypt"

# Raise `N` (never lower it); existing verifiers keep working and `needs_rehash` reports the difference.
N: Final = 1 << 15
R: Final = 8
P: Final = 1
KEY_BYTES: Final = 32
SALT_BYTES: Final = 16

# Only one doubling above the 32 MiB working set, so a careless raise of `N` fails loudly here.
MAX_MEM: Final = 96 * 1024 * 1024

# Bounds peak KDF memory regardless of load (4 × 32 MiB).
MAX_CONCURRENT: Final = 4

# An unbounded input into a memory-hard KDF is a cheap way to make the server do arbitrary work.
MAX_PASSWORD_BYTES: Final = 4096


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, *, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        # Truncate, never raise: the policy layer already refused this length; a raise would lock an owner out.
        encoded = encoded[:MAX_PASSWORD_BYTES]
    return hashlib.scrypt(encoded, salt=salt, n=n, r=r, p=p, dklen=length, maxmem=MAX_MEM)


def hash_password(password: str) -> str:
    """Derive a fresh verifier. Never returns the same string twice."""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = _derive(password, salt=salt, n=N, r=R, p=P, length=KEY_BYTES)
    return f"{SCHEME}${N}${R}${P}${_b64(salt)}${_b64(derived)}"


def verify(stored: str | None, password: str) -> bool:
    """Constant-time check; ``False`` for every failure so no-password and wrong-password are indistinguishable."""
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = _unb64(parts[4])
        expected = _unb64(parts[5])
    except (ValueError, TypeError):
        return False
    if n <= 1 or n & (n - 1) or r < 1 or p < 1 or not salt or not expected:
        # scrypt would raise on a non-power-of-two `n`, and a raise is a distinguishable answer.
        return False
    try:
        candidate = _derive(password, salt=salt, n=n, r=r, p=p, length=len(expected))
    except ValueError:
        # A record written by a future, more expensive setting.
        return False
    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: str | None) -> bool:
    """True when a verifier predates today's parameters; call after a successful :func:`verify` and rewrite."""
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return True
    try:
        return (int(parts[1]), int(parts[2]), int(parts[3])) != (N, R, P)
    except ValueError:
        return True


# Async wrappers: the thread keeps the CPU burn off the event loop, the semaphore bounds memory
# (`hashlib.scrypt` releases the GIL). Async callers use these, never the sync pair.


def _gate() -> asyncio.Semaphore:
    """Per-event-loop gate, built lazily: a semaphore bound to a closed loop (pytest) raises on first use."""
    loop = asyncio.get_running_loop()
    gate = _GATES.get(loop)
    if gate is None:
        gate = asyncio.Semaphore(MAX_CONCURRENT)
        _GATES[loop] = gate
    return gate


_GATES: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakKeyDictionary()


async def hash_password_async(password: str) -> str:
    async with _gate():
        return await asyncio.to_thread(hash_password, password)


async def verify_async(stored: str | None, password: str) -> bool:
    # Outside the gate: an unregistered address must not be able to occupy a slot.
    if not stored:
        return False
    async with _gate():
        return await asyncio.to_thread(verify, stored, password)


__all__ = [
    "hash_password",
    "hash_password_async",
    "needs_rehash",
    "verify",
    "verify_async",
]
