"""The FND-1 issuer contract test, as a fixture every service reuses.

Every service in the fleet must prove the same four things about the
issuer list it was configured with:

===  =========================================================  ======
(a)  a Keycloak-shaped token (issuer 1)                          200
(b)  a native-shaped token (issuer 2)                            200
(c)  a token from a third issuer                                 401
(d)  ``alg=none`` and HS256-signed-with-the-public-key           401
===  =========================================================  ======

The interesting cases are (c) and (d). Selecting a verification config by
the token's *unverified* ``iss`` is only sound because the selected
config's JWKS is then the only source of keys and its audience the only
accepted audience. A service that got the wiring subtly wrong — passing a
literal issuer, or building its cache from a different list than its
dependency — would still pass (a) and (b).

The test runs entirely in process: no Keycloak, no auth-service, no
database. It builds the service's REAL issuer list from its REAL settings
object, so it fails if a service forgets ``AUTH_ISSUERS_JSON``.

Usage, in ``services/<svc>/tests/integration/test_issuer_contract.py``::

    from auth.contract import IssuerContract, assert_issuer_contract

    from note_service.config import settings
    from note_service.main_deps import auth_issuers

    async def test_issuer_contract(monkeypatch):
        contract = IssuerContract()
        monkeypatch.setattr(settings, "auth_issuers_json", contract.issuers_json)
        await assert_issuer_contract(contract, auth_issuers())
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .exceptions import AuthError
from .issuers import IssuerConfig, issuer_url_map
from .jwks import JwksCache
from .testing import TestIssuer, multi_issuer_jwks_cache
from .verifier import verify_token

__all__ = ["IssuerContract", "assert_issuer_contract"]

# Names, not real hosts: `.invalid` is reserved (RFC 2606) so a bug that
# turns the in-memory transport into a real fetch fails loudly instead of
# reaching somebody's server.
KEYCLOAK_ISSUER = "https://keycloak.contract.invalid/realms/notes"
NATIVE_ISSUER = "https://auth.contract.invalid"
THIRD_ISSUER = "https://third.contract.invalid"


def _segment(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode("ascii")


@dataclass
class IssuerContract:
    """Two trusted issuers, one untrusted one, and the tokens for each."""

    audience: str = "mdx-api"
    keycloak_issuer: str = KEYCLOAK_ISSUER
    native_issuer: str = NATIVE_ISSUER
    third_issuer: str = THIRD_ISSUER
    keycloak: TestIssuer = field(init=False)
    native: TestIssuer = field(init=False)
    third: TestIssuer = field(init=False)

    def __post_init__(self) -> None:
        self.keycloak = TestIssuer(issuer=self.keycloak_issuer, audience=self.audience)
        self.native = TestIssuer(issuer=self.native_issuer, audience=self.audience)
        self.third = TestIssuer(issuer=self.third_issuer, audience=self.audience)

    @property
    def configs(self) -> list[IssuerConfig]:
        return [
            self.keycloak.config(audience=self.audience),
            self.native.config(audience=self.audience),
        ]

    @property
    def issuers_json(self) -> str:
        """The exact ``AUTH_ISSUERS_JSON`` value to put in the service's settings."""
        return json.dumps(
            [
                {"issuer": c.issuer, "jwks_url": c.jwks_url, "audience": c.audience}
                for c in self.configs
            ]
        )

    def jwks_cache(self, issuers: list[IssuerConfig] | None = None) -> JwksCache:
        """A cache serving both trusted keys — and only those.

        ``issuers`` is the list the SERVICE resolved. Passing it is what
        makes the test meaningful: if the service's list disagrees with
        this contract's, the cache is built from the service's names and
        the tokens stop verifying.
        """
        wanted = issuers if issuers is not None else self.configs
        by_issuer = {self.keycloak.issuer: self.keycloak, self.native.issuer: self.native}
        return multi_issuer_jwks_cache([(c, by_issuer.get(c.issuer)) for c in wanted])

    # ── the four token shapes ────────────────────────────────────────────

    def keycloak_token(self, **claims: Any) -> str:
        return self.keycloak.mint(**claims)

    def native_token(self, **claims: Any) -> str:
        return self.native.mint(**claims)

    def third_issuer_token(self, **claims: Any) -> str:
        return self.third.mint(**claims)

    def alg_none_token(self) -> str:
        """An unsigned token that names a trusted issuer and a known kid."""
        now = int(time.time())
        header = _segment({"alg": "none", "typ": "JWT", "kid": self.native.kid})
        payload = _segment(
            {
                "iss": self.native_issuer,
                "aud": self.audience,
                "sub": str(uuid4()),
                "sid": str(uuid4()),
                "tid": str(uuid4()),
                "roles": ["member"],
                "iat": now,
                "exp": now + 900,
            }
        )
        return f"{header}.{payload}."

    def hs256_confusion_token(self) -> str:
        """The algorithm-confusion classic: HS256 keyed with the RSA *public* key.

        A verifier that lets the token's header choose the algorithm
        treats a public key everyone has as a shared secret. RS256 is
        asserted before any key material is loaded, so this must fail
        whatever the JWKS says.
        """
        from jose import jwt as jose_jwt

        now = int(time.time())
        token: str = jose_jwt.encode(
            {
                "iss": self.native_issuer,
                "aud": self.audience,
                "sub": str(uuid4()),
                "sid": str(uuid4()),
                "tid": str(uuid4()),
                "roles": ["member"],
                "iat": now,
                "exp": now + 900,
            },
            json.dumps(self.native.public_jwk),
            algorithm="HS256",
            headers={"kid": self.native.kid},
        )
        return token


async def assert_issuer_contract(
    contract: IssuerContract,
    issuers: list[IssuerConfig],
    *,
    clock_skew_seconds: int = 30,
) -> None:
    """Run the four cases against the issuer list a service actually resolved.

    Raises ``AssertionError`` with a message naming the case that failed.
    """
    names = [c.issuer for c in issuers]
    assert contract.keycloak_issuer in names, (
        f"service does not trust the Keycloak issuer; its list is {names}. "
        "Does its config read AUTH_ISSUERS_JSON?"
    )
    assert contract.native_issuer in names, (
        f"service does not trust the native issuer; its list is {names}"
    )
    assert contract.third_issuer not in names, "the contract's third issuer must not be trusted"
    assert issuer_url_map(issuers), "issuer list resolved to nothing"

    cache = contract.jwks_cache(issuers)

    # (a) and (b): both trusted shapes verify.
    for label, token in (
        ("keycloak-shaped", contract.keycloak_token()),
        ("native-shaped", contract.native_token()),
    ):
        claims = await verify_token(
            token, issuers=issuers, jwks_cache=cache, clock_skew_seconds=clock_skew_seconds
        )
        assert claims.iss in names, f"{label} token verified with an unexpected iss"

    # (c) and (d): everything else is rejected, each for its own reason.
    for label, token in (
        ("third-issuer", contract.third_issuer_token()),
        ("alg=none", contract.alg_none_token()),
        ("HS256 confusion", contract.hs256_confusion_token()),
    ):
        try:
            await verify_token(
                token, issuers=issuers, jwks_cache=cache, clock_skew_seconds=clock_skew_seconds
            )
        except AuthError:
            continue
        raise AssertionError(f"{label} token was ACCEPTED; it must be rejected")
