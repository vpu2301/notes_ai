"""RS256 signing keys for the native issuer (IDX-A2, F1).

Keys come from ``AUTH_SIGNING_KEYS_JSON`` — a JSON list of
``{"kid", "private_pem", "not_after"}`` — or, on a developer machine only,
from the file named by ``AUTH_SIGNING_KEYS_FILE``. Nothing here reads the
environment; ``config.py`` hands the raw text in.

Rules (ADR-IDX-02 as summarised in the sprint pack):

* the **active** key is the one whose ``not_after`` lies furthest in the
  future and is not yet past — new tokens are signed with it;
* the JWKS publishes every key whose ``not_after + access_ttl`` is still
  in the future, so a token signed just before a key retired keeps
  verifying until it expires itself;
* ``kid`` is derived from the public key (``sha256(SPKI DER)[:12]``) by
  ``scripts/ops/gen-signing-key.py``; a configured kid that does not match
  its key is refused at load time — a mislabelled key would break every
  verifier's cache in a way that is very hard to see from the outside.

Private material never leaves this module except as the ``private_pem``
attribute the :class:`TokenService` signs with; ``public_jwk`` carries only
``kty/kid/use/alg/n/e``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

MIN_RSA_BITS = 2048


class SigningKeyError(ValueError):
    """The key configuration is unusable. Message is safe to log (no key material)."""


def _b64url_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def kid_for_public_key(public_key: rsa.RSAPublicKey) -> str:
    """``sha256(SubjectPublicKeyInfo DER)`` hex, first 12 characters."""
    spki = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class SigningKey:
    kid: str
    private_pem: bytes
    not_after: datetime
    public_jwk: dict[str, str]

    def __repr__(self) -> str:  # never print the PEM
        return f"SigningKey(kid={self.kid!r}, not_after={self.not_after.isoformat()})"


def _parse_not_after(raw: Any, kid: str) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise SigningKeyError(f"signing key {kid!r}: not_after must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SigningKeyError(f"signing key {kid!r}: not_after is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise SigningKeyError(f"signing key {kid!r}: not_after needs a timezone")
    return parsed.astimezone(UTC)


def load_signing_keys(raw_json: str) -> list[SigningKey]:
    """Parse and validate the configured key list. Raises :class:`SigningKeyError`."""
    try:
        entries = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise SigningKeyError("AUTH_SIGNING_KEYS_JSON is not valid JSON") from exc
    if not isinstance(entries, list) or not entries:
        raise SigningKeyError("AUTH_SIGNING_KEYS_JSON must be a non-empty JSON list")

    keys: list[SigningKey] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SigningKeyError(f"signing key #{i}: entry must be an object")
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid:
            raise SigningKeyError(f"signing key #{i}: kid missing")
        if kid in seen:
            raise SigningKeyError(f"signing key {kid!r}: duplicate kid")
        seen.add(kid)
        pem = entry.get("private_pem")
        if not isinstance(pem, str) or "PRIVATE KEY" not in pem:
            raise SigningKeyError(f"signing key {kid!r}: private_pem missing or not a PEM")
        try:
            private = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
        except (ValueError, TypeError) as exc:
            raise SigningKeyError(f"signing key {kid!r}: private_pem could not be parsed") from exc
        if not isinstance(private, rsa.RSAPrivateKey):
            raise SigningKeyError(f"signing key {kid!r}: only RSA keys are accepted")
        if private.key_size < MIN_RSA_BITS:
            raise SigningKeyError(f"signing key {kid!r}: RSA key must be >= {MIN_RSA_BITS} bits")
        public = private.public_key()
        expected_kid = kid_for_public_key(public)
        if kid != expected_kid:
            raise SigningKeyError(
                f"signing key {kid!r}: kid does not match its public key (expected {expected_kid!r})"
            )
        numbers = public.public_numbers()
        keys.append(
            SigningKey(
                kid=kid,
                private_pem=pem.encode("ascii"),
                not_after=_parse_not_after(entry.get("not_after"), kid),
                public_jwk={
                    "kty": "RSA",
                    "kid": kid,
                    "use": "sig",
                    "alg": "RS256",
                    "n": _b64url_uint(numbers.n),
                    "e": _b64url_uint(numbers.e),
                },
            )
        )
    return keys


class KeySet:
    """The configured keys plus the two selection rules."""

    def __init__(self, keys: list[SigningKey]) -> None:
        if not keys:
            raise SigningKeyError("at least one signing key is required")
        self._keys = list(keys)

    @classmethod
    def from_json(cls, raw_json: str) -> KeySet:
        return cls(load_signing_keys(raw_json))

    @property
    def kids(self) -> list[str]:
        return [k.kid for k in self._keys]

    def active(self, now: datetime | None = None) -> SigningKey:
        """The key new tokens are signed with: furthest ``not_after`` still ahead."""
        now = now or datetime.now(UTC)
        live = [k for k in self._keys if k.not_after > now]
        if not live:
            raise SigningKeyError("every configured signing key is past its not_after")
        return max(live, key=lambda k: k.not_after)

    def published(
        self, *, access_ttl_seconds: int, now: datetime | None = None
    ) -> list[SigningKey]:
        """Keys the JWKS advertises: retired ones stay while their tokens can be alive."""
        now = now or datetime.now(UTC)
        return [
            k
            for k in self._keys
            if (k.not_after.timestamp() + access_ttl_seconds) > now.timestamp()
        ]

    def jwks(self, *, access_ttl_seconds: int, now: datetime | None = None) -> dict[str, Any]:
        return {
            "keys": [
                dict(k.public_jwk)
                for k in self.published(access_ttl_seconds=access_ttl_seconds, now=now)
            ]
        }
