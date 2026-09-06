"""Mint RS256 access tokens in the exact ``libs/auth`` :class:`Claims` shape (IDX-A2, F2).

The contract is the verifier's, not ours: every claim here is a field
``Claims`` declares, and a unit test round-trips the payload through
``Claims(**payload)`` so a claim the verifier forbids can never ship.

``mint`` takes plain values rather than identity/session rows on purpose —
the A1 data model (``identities``, ``auth_sessions``, membership → role
mapping) is not in the repo yet, and the token format must not depend on
how those rows are shaped.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from jose import jwt

from .signing_keys import KeySet

TOKEN_TYPE = "Bearer"


@dataclass(frozen=True, slots=True)
class MintedToken:
    token: str
    kid: str
    jti: str
    issued_at: int
    expires_at: int

    @property
    def expires_in(self) -> int:
        return self.expires_at - self.issued_at


class TokenService:
    def __init__(
        self,
        *,
        keys: KeySet,
        issuer: str,
        audience: str,
        access_ttl_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not issuer:
            raise ValueError("issuer is required")
        if not audience:
            raise ValueError("audience is required")
        if access_ttl_seconds <= 0:
            raise ValueError("access_ttl_seconds must be positive")
        self._keys = keys
        self.issuer = issuer
        self.audience = audience
        self.access_ttl_seconds = access_ttl_seconds
        self._clock = clock or time.time

    def mint(
        self,
        *,
        identity_id: UUID,
        session_id: str,
        tenant_id: UUID,
        roles: list[str],
        scope: str = "",
        mfa: bool = False,
        mfa_enrolled: bool = False,
        email: str | None = None,
        name: str | None = None,
    ) -> MintedToken:
        """Sign an access token for ``identity_id`` in ``tenant_id``.

        Membership checks are the caller's job (``SessionService`` in the
        A1-dependent half of this sprint); this only encodes and signs.
        """
        if not roles:
            raise ValueError("a token needs at least one role")
        if not session_id:
            raise ValueError("session_id is required")
        now = int(self._clock())
        exp = now + self.access_ttl_seconds
        jti = str(uuid4())
        payload: dict[str, object] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": str(identity_id),
            "sid": session_id,
            "tid": str(tenant_id),
            "roles": list(roles),
            "scope": scope,
            "mfa": mfa,
            "mfa_enrolled": mfa_enrolled,
            "iat": now,
            "exp": exp,
            "jti": jti,
            "typ": TOKEN_TYPE,
            "azp": self.audience,
        }
        if email is not None:
            payload["email"] = email
        if name is not None:
            payload["name"] = name

        key = self._keys.active(datetime.fromtimestamp(now, tz=UTC))
        token = jwt.encode(
            payload,
            key.private_pem.decode("ascii"),
            algorithm="RS256",
            headers={"kid": key.kid, "typ": "JWT"},
        )
        return MintedToken(token=token, kid=key.kid, jti=jti, issued_at=now, expires_at=exp)
