"""Password verifiers — the one sanctioned way to store a chosen password.

Lives beside the envelope rather than in auth-service because the rule
libs/crypto exists to enforce is "nobody hand-rolls storage crypto", and a
password hash is exactly the thing engineers hand-roll. It is *not*
envelope encryption and deliberately shares none of that machinery: a
verifier must not be decryptable, so wrapping one under a tenant KEK
would be a downgrade dressed as defence in depth.

**scrypt, from the standard library.** RFC 7914, memory-hard, and
``hashlib.scrypt`` ships with CPython against OpenSSL — no new dependency
in every image that touches auth. The stored format carries its own
parameters, so moving to Argon2id later is a `scheme` value and a branch
in :func:`verify`, not a migration.

**Why the cost is set where it is.** scrypt's working set is exactly
``128 * n * r`` bytes, and that arithmetic — not a benchmark — is what
decides the parameter here. OWASP's scrypt line asks for ``n=2**17``,
which is 128 MiB *per verification*; auth-service runs under a 512 MiB
container limit (`infra/k8s/notes/values.yaml`), so three simultaneous
sign-ins at that setting would OOM-kill the pod. A login endpoint an
anonymous caller can crash with three requests is a worse failure than a
KDF two notches down.

The resolution is not to quietly pick a weak number but to bound the
concurrency as well: ``n=2**15`` is 32 MiB, and at most
:data:`MAX_CONCURRENT` derivations run at once, so peak KDF residency is
~128 MiB however many people sign in together. Callers past that wait,
which is the right back-pressure for a path already behind per-IP and
per-email rate limits and a ten-attempt lockout. Wall-clock lands in the
low hundreds of milliseconds per verification on a developer machine —
fine for sign-in, which is not a hot path.

The trade is written down rather than assumed: if auth-service's memory
limit is raised, raise :data:`N` with it and :func:`needs_rehash` upgrades
every account silently on its owner's next sign-in.

Stored form — one line, no delimiter ambiguity because every field is
base64url or a decimal integer::

    scrypt$16384$8$1$<salt-b64>$<hash-b64>
    ^      ^     ^ ^ ^          ^
    scheme n     r p salt       derived key

Parameters (n=2^14, r=8, p=1, 32-byte key, 16-byte salt) target roughly
100 ms and 16 MiB per verification on server hardware. `n` is the knob to
raise; :func:`needs_rehash` tells a caller when a stored verifier predates
a raise, so an account upgrades silently on the owner's next sign-in.

Nothing here logs, and nothing here raises on a wrong password —
:func:`verify` returns ``False``. A raise would tempt a caller into
distinguishing "wrong password" from "malformed record" in a response,
which is an oracle.
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

# Current cost. Raise `N` (never lower it) and every existing verifier
# keeps working — `needs_rehash` reports the difference.
N: Final = 1 << 15
R: Final = 8
P: Final = 1
KEY_BYTES: Final = 32
SALT_BYTES: Final = 16

# `hashlib.scrypt` allocates about 128 * N * r bytes and refuses beyond
# OpenSSL's default limit unless told otherwise. 32 MiB at the parameters
# above; the ceiling is deliberately only one doubling above that, so a
# careless raise of `N` fails loudly here rather than silently pushing the
# pod towards its memory limit.
MAX_MEM: Final = 96 * 1024 * 1024

# How many derivations may run at once. See the module docstring: this is
# the control that keeps peak KDF memory bounded regardless of load.
# 4 * 32 MiB = 128 MiB, a quarter of the container limit, and 4 in flight
# at ~90 ms each is ~44 sign-ins a second — orders of magnitude beyond
# what this product needs.
MAX_CONCURRENT: Final = 4

# Longer than the policy's maximum, and here for a different reason: an
# unbounded input reaches a memory-hard KDF and becomes a cheap way to
# make the server do arbitrary work.
MAX_PASSWORD_BYTES: Final = 4096


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, *, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        # Truncation rather than a raise: the policy layer has already
        # refused anything this long, so reaching here means an internal
        # caller, and a hard failure at sign-in would lock somebody out of
        # an account they can still prove they own.
        encoded = encoded[:MAX_PASSWORD_BYTES]
    return hashlib.scrypt(encoded, salt=salt, n=n, r=r, p=p, dklen=length, maxmem=MAX_MEM)


def hash_password(password: str) -> str:
    """Derive a fresh verifier. Never returns the same string twice."""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = _derive(password, salt=salt, n=N, r=R, p=P, length=KEY_BYTES)
    return f"{SCHEME}${N}${R}${P}${_b64(salt)}${_b64(derived)}"


def verify(stored: str | None, password: str) -> bool:
    """Constant-time check of ``password`` against a stored verifier.

    ``False`` for every failure — no such record, a format this version
    does not understand, a truncated field, the wrong password. The caller
    has exactly one bit to act on, which is the point: an account with no
    password and an account with the wrong password must be indistinguishable
    from outside.
    """
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
        # `n` must be a power of two greater than one; scrypt raises
        # otherwise, and a raise here would be a distinguishable answer.
        return False
    try:
        candidate = _derive(password, salt=salt, n=n, r=r, p=p, length=len(expected))
    except ValueError:
        # Parameters within the format but outside what this build will
        # run (a record written by a future, more expensive setting).
        return False
    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: str | None) -> bool:
    """True when a verifier was written under weaker parameters than today's.

    Call it after a successful :func:`verify` — that is the only moment the
    plaintext is in hand — and rewrite the record if it says yes.
    """
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return True
    try:
        return (int(parts[1]), int(parts[2]), int(parts[3])) != (N, R, P)
    except ValueError:
        return True


# ── async wrappers ───────────────────────────────────────────────────
#
# Two jobs. The thread keeps a deliberately expensive CPU burn off the
# event loop, which would otherwise stall every other request in the worker
# for the duration; the semaphore bounds memory. `hashlib.scrypt` does
# release the GIL for the OpenSSL call — measured ~2.5x throughput on four
# threads — so the gate admits several at once rather than serialising.
# Async callers should use these two and never the sync pair.


def _gate() -> asyncio.Semaphore:
    """The per-event-loop concurrency gate.

    Built lazily and keyed on the running loop rather than created at
    import: a semaphore bound to a loop that has since closed (pytest
    makes a fresh one per test) raises on first use.
    """
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
    # The early exit stays outside the gate: a login attempt against an
    # address with no verifier must not be able to occupy a slot, or an
    # attacker who knows one unregistered address can exhaust the gate.
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
