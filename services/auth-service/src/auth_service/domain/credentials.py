"""Client secrets for non-human principals (IDX-B1b F1).

Format, hashing and comparison — no database, no HTTP, so the properties
that matter are testable on their own:

    mdx_sk_<prefix8>_<43 url-safe characters>
    └──┬──┘ └───┬──┘  └──────────┬──────────┘
    tag: makes  identification   256 bits of CSPRNG. This is the secret.
    the string  only; stored in
    greppable   the clear so an
    in a leak   operator can tell
    scan        two live secrets apart

The tag exists so a secret is recognisable the moment it turns up
somewhere it should not be — a log line, a support ticket, a screenshot.
``PIISafeFilter`` redacts on it, and a leak-scanning rule can match it
without knowing any particular value.

**No KDF.** A password gets Argon2 because it comes from a small,
guessable space and an attacker with the hash can run a dictionary
against it. These secrets are 256 bits of ``secrets.token_urlsafe``:
there is no dictionary, and stretching a full-entropy input buys nothing
while costing a KDF on every device token request. sha256 is the right
tool here and the wrong one for passwords, and the difference is the
entropy of the input, not the sensitivity of the output.
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
    """sha256 hex of the whole presented string, tag and prefix included.

    Hashing the full string rather than just the random body means a
    secret cannot be re-tagged: ``mdx_sk_aaaaaaaa_<body>`` and
    ``mdx_sk_bbbbbbbb_<body>`` are different secrets, so a prefix
    collision cannot be engineered into a match.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hashes_match(stored_hex: str, candidate_hex: str) -> bool:
    return hmac.compare_digest(stored_hex.encode("ascii"), candidate_hex.encode("ascii"))


# Bounds, not a format. Anything in range reaches the hash comparison,
# which is the actual check.
MIN_PRESENTED_LEN = 12
MAX_PRESENTED_LEN = 256


def looks_like_secret(value: str) -> bool:
    """Cheap shape check before touching the database.

    Not validation — the hash comparison is. This exists so a grant
    request carrying a megabyte of attacker-chosen text does not become a
    megabyte-wide index probe.

    Deliberately a length bound rather than "starts with ``mdx_sk_``".
    The dev realm's room device authenticates with the string it has used
    since sprint 07 (``dev-room-device-secret``), and requiring the tag
    here would mean every dev config had to change on the day the token
    endpoint moved — which is exactly the kind of coupled change a
    cut-over should not need. The tag is how secrets are *generated* and
    how a leak is *recognised*; it was never meant to be an authentication
    gate, and treating it as one would also let an attacker skip the hash
    comparison for any string without it, which is a free oracle.
    """
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

# Mirrors the CHECK constraint in migration 0026. Declared here as well so
# the API refuses a bad combination with a 400 rather than letting the
# database refuse it with a 500 — and so the two can be compared in a test.
ROLES_FOR_KIND: dict[str, list[str]] = {
    KIND_SERVICE: ["service"],
    KIND_DEVICE: ["device"],
}


def roles_for(kind: str) -> list[str]:
    try:
        return list(ROLES_FOR_KIND[kind])
    except KeyError:
        raise ValueError(f"unknown credential kind {kind!r}") from None
