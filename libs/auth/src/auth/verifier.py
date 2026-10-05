"""``verify_token``: the single JWT verification entry point (named ``verifier`` to avoid shadowing ``jose.jwt``).

The unverified ``iss`` selects ONE trusted issuer; the token is then verified against that entry only (ADR-0047).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwk, jwt
from jose.exceptions import JWTClaimsError
from pydantic import ValidationError

from .claims import Claims
from .exceptions import (
    ExpiredTokenError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    KidNotFoundError,
    MalformedClaimsError,
)
from .issuers import IssuerConfig
from .jwks import JwksCache

_ACCEPTED_ALGORITHMS: frozenset[str] = frozenset({"RS256"})


def _resolve_issuers(
    issuers: Sequence[IssuerConfig] | None,
    expected_issuer: str | None,
    expected_audience: str | None,
) -> Sequence[IssuerConfig]:
    if issuers:
        return issuers
    if expected_issuer and expected_audience:
        # jwks_url is unused here: the legacy caller already built the cache.
        return (
            IssuerConfig(
                issuer=expected_issuer, jwks_url=expected_issuer, audience=expected_audience
            ),
        )
    raise TypeError(
        "verify_token needs either issuers=[IssuerConfig, ...] or both "
        "expected_issuer= and expected_audience="
    )


def _select(issuers: Sequence[IssuerConfig], token: str) -> IssuerConfig:
    """Pick the trusted issuer matching the UNVERIFIED ``iss``; ``jwt.decode`` re-checks it cryptographically."""
    try:
        unverified: dict[str, Any] = jwt.get_unverified_claims(token)
    except JWTError as exc:
        raise InvalidTokenError(f"malformed token payload: {exc}") from exc

    claimed = unverified.get("iss")
    if not isinstance(claimed, str) or not claimed:
        raise InvalidIssuerError("token has no iss claim")

    for config in issuers:
        if config.issuer == claimed:
            return config
    raise InvalidIssuerError(f"issuer {claimed!r} is not trusted by this service")


async def verify_token(
    token: str,
    *,
    jwks_cache: JwksCache,
    issuers: Sequence[IssuerConfig] | None = None,
    expected_audience: str | None = None,
    expected_issuer: str | None = None,
    clock_skew_seconds: int = 30,
) -> Claims:
    """Verify ``token`` against ``issuers`` (or the legacy issuer/audience pair) and return :class:`Claims`.

    Raises the matching :mod:`auth.exceptions` type for each failure mode.
    """
    trusted = _resolve_issuers(issuers, expected_issuer, expected_audience)

    # Assert alg before any key material: never let python-jose pick (algorithm confusion).
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise InvalidTokenError(f"malformed token header: {exc}") from exc

    alg = header.get("alg")
    if alg not in _ACCEPTED_ALGORITHMS:
        raise InvalidTokenError(f"unsupported alg {alg!r}; only RS256 is accepted")

    kid = header.get("kid")
    if not kid or not isinstance(kid, str):
        raise KidNotFoundError("token header has no kid")

    config = _select(trusted, token)
    expected_issuer = config.issuer
    expected_audience = config.audience

    jwk_dict = await jwks_cache.get_key(expected_issuer, kid)
    try:
        signing_key = jwk.construct(jwk_dict, algorithm="RS256")
    except Exception as exc:
        raise InvalidTokenError(f"could not construct verifier from JWK: {exc}") from exc

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key,
            algorithms=list(_ACCEPTED_ALGORITHMS),
            audience=expected_audience,
            issuer=expected_issuer,
            options={
                "leeway": clock_skew_seconds,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": False,  # iat tolerated; exp is the auth horizon
            },
        )
    except ExpiredSignatureError as exc:
        raise ExpiredTokenError(str(exc)) from exc
    except JWTClaimsError as exc:
        # python-jose lumps aud/iss errors under JWTClaimsError; discriminate by message.
        msg = str(exc).lower()
        if "audience" in msg or "aud " in msg:
            raise InvalidAudienceError(str(exc)) from exc
        if "issuer" in msg or "iss " in msg:
            raise InvalidIssuerError(str(exc)) from exc
        raise InvalidTokenError(str(exc)) from exc
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    try:
        return Claims(**payload)
    except ValidationError as exc:
        raise MalformedClaimsError(str(exc)) from exc
