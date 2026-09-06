"""Test harness for token contract tests (IDX-A2, item 5).

Any service can prove, in-process and without Keycloak, that a token minted
the way auth-service mints them is accepted by its own ``current_user``
dependency::

    issuer = TestIssuer()                       # fresh RSA key, deterministic kid
    cache = issuer.jwks_cache()                 # JwksCache served from memory
    token = issuer.mint(sub=..., tid=..., roles=["member"])
    claims = await verify_token(token, expected_audience=issuer.audience,
                                expected_issuer=issuer.issuer, jwks_cache=cache)

``mint`` builds the exact claim set :class:`auth.claims.Claims` accepts;
``mint_raw`` lets a test hand over any payload (wrong ``aud``, forbidden
claim, expired ``exp``) to assert rejection.
"""

from __future__ import annotations

import base64
import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from .issuers import IssuerConfig, issuer_url_map
from .jwks import JwksCache

DEFAULT_ISSUER = "https://auth.test.invalid"
DEFAULT_AUDIENCE = "mdx-api"


def _b64url_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass
class TestIssuer:
    """An in-memory RS256 issuer: one key, a JWKS document, a minter."""

    issuer: str = DEFAULT_ISSUER
    audience: str = DEFAULT_AUDIENCE
    key_bits: int = 2048
    kid: str = field(init=False)
    private_pem: str = field(init=False, repr=False)
    public_jwk: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        private = rsa.generate_private_key(public_exponent=65537, key_size=self.key_bits)
        public = private.public_key()
        spki = public.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.kid = hashlib.sha256(spki).hexdigest()[:12]
        self.private_pem = private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        numbers = public.public_numbers()
        self.public_jwk = {
            "kty": "RSA",
            "kid": self.kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64url_uint(numbers.n),
            "e": _b64url_uint(numbers.e),
        }

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/.well-known/jwks.json"

    def jwks_document(self) -> dict[str, Any]:
        return {"keys": [dict(self.public_jwk)]}

    def jwks_cache(self, **kwargs: Any) -> JwksCache:
        """A :class:`JwksCache` whose HTTP client answers from this issuer's key."""

        def _handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == self.jwks_url:
                return httpx.Response(200, json=self.jwks_document())
            return httpx.Response(404, json={"error": "not found"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        return JwksCache(issuer_to_url={self.issuer: self.jwks_url}, http_client=client, **kwargs)

    def jwks_cache_for(self, issuer: str, **kwargs: Any) -> JwksCache:
        """A cache that serves this key under SOMEBODY ELSE'S issuer name.

        A service verifies `iss` against its own configured value, which
        is not the harness's. Registering the test key under the name the
        service expects is what lets the real verification path run
        unchanged rather than being stubbed around.
        """
        url = f"{issuer.rstrip('/')}/.well-known/jwks.json"

        def _handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == url:
                return httpx.Response(200, json=self.jwks_document())
            return httpx.Response(404, json={"error": "not found"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        return JwksCache(issuer_to_url={issuer: url}, http_client=client, **kwargs)

    def claims(
        self,
        *,
        sub: UUID | None = None,
        tid: UUID | None = None,
        roles: list[str] | None = None,
        sid: str | None = None,
        ttl_seconds: int = 900,
        now: int | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """The payload auth-service's ``TokenService`` produces, as a dict."""
        now = int(now if now is not None else time.time())
        payload: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": str(sub or uuid4()),
            "sid": sid or str(uuid4()),
            "tid": str(tid or uuid4()),
            "roles": list(roles or ["member"]),
            "scope": "",
            "mfa": False,
            "mfa_enrolled": False,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": str(uuid4()),
            "typ": "Bearer",
            "azp": self.audience,
        }
        payload.update(extra)
        return payload

    def mint_raw(self, payload: dict[str, Any], *, kid: str | None = None) -> str:
        """Sign any payload — for negative tests (wrong aud/iss, forbidden claims)."""
        token: str = jwt.encode(
            payload,
            self.private_pem,
            algorithm="RS256",
            headers={"kid": kid or self.kid, "typ": "JWT"},
        )
        return token

    def mint(self, **kwargs: Any) -> str:
        return self.mint_raw(self.claims(**kwargs))


    def config(self, *, issuer: str | None = None, audience: str | None = None) -> IssuerConfig:
        """This key's :class:`IssuerConfig`, optionally renamed.

        ``issuer`` renames the entry the way :meth:`jwks_cache_for` does,
        for a test that must present itself as the issuer a service is
        configured to trust.
        """
        name = (issuer or self.issuer).rstrip("/")
        return IssuerConfig(
            issuer=name,
            jwks_url=f"{name}/.well-known/jwks.json",
            audience=audience or self.audience,
        )


def multi_issuer_jwks_cache(
    issuers: Sequence[tuple[IssuerConfig, TestIssuer | None]],
    **kwargs: Any,
) -> JwksCache:
    """A cache serving several issuers at once — the FND-1 fixture.

    Each pair is ``(config, signer)``. A ``None`` signer publishes an
    **empty but valid** JWKS document: that is the shape auth-service's
    endpoint has between the FND-1 fleet rollout and BE-2, and a fleet
    that cannot tolerate it cannot be rolled out in the right order.
    Verification of the other issuers' tokens must be unaffected by it,
    and tokens claiming the empty issuer must fail ``kid_not_found`` —
    not fall back to another issuer's keys.
    """
    documents = {
        config.jwks_url: (signer.jwks_document() if signer is not None else {"keys": []})
        for config, signer in issuers
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        document = documents.get(str(request.url))
        if document is None:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=document)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    return JwksCache(
        issuer_to_url=issuer_url_map([config for config, _ in issuers]),
        http_client=client,
        **kwargs,
    )


__all__ = [
    "DEFAULT_AUDIENCE",
    "DEFAULT_ISSUER",
    "TestIssuer",
    "multi_issuer_jwks_cache",
]


# ── The one-liner surface (IDX-B2 F4) ────────────────────────────────────
#
# `TestIssuer` above is the full harness. What a service's conftest
# actually wants is "give me a token for this sub/tid/roles" without
# thinking about keys — and, crucially, without generating an RSA key per
# test. A 2048-bit keygen is 50-200 ms; done per test across the fleet's
# suites that is minutes of wall clock for no benefit, since every test
# wants the same thing: a signature its own `current_user` will accept.
#
# So there is one process-wide issuer, built on first use.

_SHARED: TestIssuer | None = None


def shared_issuer() -> TestIssuer:
    """The process-wide test issuer. One RSA key for the whole session."""
    global _SHARED
    if _SHARED is None:
        _SHARED = TestIssuer()
    return _SHARED


def mint_test_token(
    *,
    sub: UUID | None = None,
    tid: UUID | None = None,
    roles: list[str] | None = None,
    sid: str | None = None,
    ttl_seconds: int = 900,
    issuer: str | None = None,
    key: TestIssuer | None = None,
    **extra: Any,
) -> str:
    """A signed token for a service test. Replaces logging in through Keycloak.

    ``issuer`` sets the ``iss`` claim — which, after FND-1, is what picks
    the verification config, so a contract test proves "Keycloak-shaped"
    and "native-shaped" by minting the same claims under two names.
    ``key`` signs with a different :class:`TestIssuer`, which is how the
    third-issuer rejection case gets a *real* signature that no
    configured JWKS contains.

    ``extra`` goes straight into the payload, so a test can assert on
    `mfa`, a `device` role, or a deliberately wrong `aud` without reaching
    for the issuer object.
    """
    signer = key or shared_issuer()
    if issuer is not None:
        extra.setdefault("iss", issuer)
    return signer.mint(sub=sub, tid=tid, roles=roles, sid=sid, ttl_seconds=ttl_seconds, **extra)


def auth_headers(**kwargs: Any) -> dict[str, str]:
    """``{"Authorization": "Bearer …"}`` for a token minted per ``mint_test_token``."""
    return {"Authorization": f"Bearer {mint_test_token(**kwargs)}"}


def test_jwks_cache(**kwargs: Any) -> JwksCache:
    """A cache serving the shared issuer's key, in process, over no network."""
    return shared_issuer().jwks_cache(**kwargs)


def install_test_issuer(state: Any, *, issuer: str | None = None) -> TestIssuer:
    """Point a service's ``ServiceState`` at the shared test issuer.

    ``issuer`` is the value the service's ``current_user`` will DEMAND —
    normally its ``settings.auth_issuer``. The cache is registered under
    that name so the service's own issuer check passes; tokens must then
    be minted with the same ``iss`` (``auth_headers(iss=…)``). Without
    this the harness would sign perfectly good tokens that every service
    rejects for the wrong issuer, which looks exactly like a broken
    verifier.

    Every service in this fleet builds `current_user` from
    ``state.jwks_cache`` plus its settings, and caches the built
    dependency on ``state._current_user_dep``. Swapping the cache alone
    would be silently ignored once that closure exists, so the stale one
    is dropped too — the bug this prevents is a test that passes because
    it is still verifying against the old key.
    """
    test_issuer = shared_issuer()
    state.jwks_cache = test_issuer.jwks_cache_for(issuer or test_issuer.issuer)
    if hasattr(state, "_current_user_dep"):
        delattr(state, "_current_user_dep")
    return test_issuer
