"""Signed OAuth ``state`` for the calendar connect flow (0019).

Google sends the user back to ``/v1/calendar/google/callback`` with the
``state`` we gave it. That request carries no bearer token — it is a
plain browser navigation — so the state itself has to say who started
the flow and where to send them afterwards. It is an HMAC-signed,
short-lived record of (tenant, user, return_to, nonce): the callback
trusts nothing about the caller that the signature does not vouch for.

Stateless on purpose: no Redis row to expire, no session to look up,
and the same handler works whether the flow began in the web app or
the Mac app (they differ only in ``return_to``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from uuid import UUID

# A sign-in that takes longer than this is a stale tab, not a user.
STATE_TTL_SECONDS = 15 * 60


class InvalidStateError(ValueError):
    """The state is missing, malformed, tampered with, or expired."""


@dataclass(frozen=True, slots=True)
class ConnectState:
    tenant_id: UUID
    user_sub: UUID
    return_to: str
    provider: str
    issued_at: int
    nonce: str


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload: bytes, *, key_hex: str) -> bytes:
    return hmac.new(bytes.fromhex(key_hex), payload, hashlib.sha256).digest()


def issue_state(
    *,
    tenant_id: UUID,
    user_sub: UUID,
    return_to: str,
    provider: str = "google",
    key_hex: str,
    now: float | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    doc = {
        "t": str(tenant_id),
        "u": str(user_sub),
        "r": return_to,
        "p": provider,
        "i": issued_at,
        "n": secrets.token_urlsafe(12),
    }
    payload = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{_b64(payload)}.{_b64(_sign(payload, key_hex=key_hex))}"


def verify_state(
    state: str | None,
    *,
    key_hex: str,
    now: float | None = None,
    ttl_seconds: int = STATE_TTL_SECONDS,
) -> ConnectState:
    if not state or "." not in state or len(state) > 2048:
        raise InvalidStateError("missing or malformed state")
    body, _, signature = state.partition(".")
    try:
        payload = _unb64(body)
        given = _unb64(signature)
    except (ValueError, TypeError) as exc:
        raise InvalidStateError("state is not base64") from exc
    if not hmac.compare_digest(given, _sign(payload, key_hex=key_hex)):
        raise InvalidStateError("state signature mismatch")
    try:
        doc = json.loads(payload.decode("utf-8"))
        parsed = ConnectState(
            tenant_id=UUID(doc["t"]),
            user_sub=UUID(doc["u"]),
            return_to=str(doc["r"]),
            provider=str(doc["p"]),
            issued_at=int(doc["i"]),
            nonce=str(doc["n"]),
        )
    except (KeyError, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise InvalidStateError("state payload is invalid") from exc
    current = now if now is not None else time.time()
    if parsed.issued_at > current + 60 or current - parsed.issued_at > ttl_seconds:
        raise InvalidStateError("state expired")
    return parsed
