"""Client secrets for non-human principals: ``mdx_sk_<prefix8>_<43 url-safe chars>``.

The tag makes leaked secrets greppable; the prefix identifies a secret without
disclosing it. sha256, no KDF: the body is 256 bits of CSPRNG, not a guessable space.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

TAG = "mdx_sk_"
PREFIX_LEN = 8
# 32 bytes → 43 url-safe characters.
SECRET_BYTES = 32


@dataclass(frozen=True, slots=True)
class NewSecret:
    """A freshly minted secret. ``value`` is shown once and never stored."""

    value: str
    prefix: str
    hash_hex: str


def generate_secret() -> NewSecret:
    prefix = secrets.token_hex(PREFIX_LEN // 2)  # 8 hex characters
    body = secrets.token_urlsafe(SECRET_BYTES)
    value = f"{TAG}{prefix}_{body}"
    return NewSecret(value=value, prefix=prefix, hash_hex=secret_hash(value))


def secret_hash(value: str) -> str:
    """sha256 hex of the whole presented string, tag and prefix included (a secret cannot be re-tagged)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hashes_match(stored_hex: str, candidate_hex: str) -> bool:
    return hmac.compare_digest(stored_hex.encode("ascii"), candidate_hex.encode("ascii"))


# Bounds, not a format; the hash comparison is the check.
MIN_PRESENTED_LEN = 12
MAX_PRESENTED_LEN = 256


def looks_like_secret(value: str) -> bool:
    """Cheap length bound before touching the database (not a tag check: legacy dev secrets have none)."""
    return isinstance(value, str) and MIN_PRESENTED_LEN <= len(value) <= MAX_PRESENTED_LEN


def prefix_of(value: str) -> str:
    """The identification prefix, or "" if the string is not one of ours."""
    if not value.startswith(TAG):
        return ""
    rest = value[len(TAG) :]
    head, _, tail = rest.partition("_")
    return head if tail and len(head) == PREFIX_LEN else ""


# ── kinds and their fixed grants ─────────────────────────────────────────

KIND_SERVICE = "service"
KIND_DEVICE = "device"

# Mirrors the DB CHECK constraint so a bad combination is a 400, not a 500.
ROLES_FOR_KIND: dict[str, list[str]] = {
    KIND_SERVICE: ["service"],
    KIND_DEVICE: ["device"],
}


def roles_for(kind: str) -> list[str]:
    try:
        return list(ROLES_FOR_KIND[kind])
    except KeyError:
        raise ValueError(f"unknown credential kind {kind!r}") from None
