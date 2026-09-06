"""``verify_token`` — the single sanctioned entry point for JWT verification.

The function is intentionally narrow: it accepts a raw token string and the
list of issuers the caller trusts, then either returns a :class:`Claims` or
raises one of the distinct exception classes from :mod:`auth.exceptions`.
Every failure mode is mapped to its own type so callers can audit/alert
appropriately (e.g. ``InvalidTokenError`` is a sec-severity event).

FND-1 (ADR-0047) turned the single ``expected_issuer`` string into a list
of :class:`auth.issuers.IssuerConfig`. The unverified ``iss`` claim selects
**one** entry; the token is then verified against that entry's issuer,
audience and JWKS URL and nothing else. Selection is not relaxation: an
``iss`` that matches no entry is rejected before a key is fetched, and a
token signed by issuer A claiming issuer B's audience still fails.

The legacy ``expected_issuer`` / ``expected_audience`` pair is still
accepted and builds a one-element list, so every pre-FND-1 caller behaves
bit for bit as it did.

This module is named ``verifier`` rather than ``jwt`` to avoid shadowing
the ``jose.jwt`` import inside our own package.
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
        # jwks_url is unused on this path: the caller already built the
        # cache, and a legacy caller has exactly one entry in it.
        return (IssuerConfig(issuer=expected_issuer, jwks_url=expected_issuer, audience=expected_audience),)
    raise TypeError(
        "verify_token needs either issuers=[IssuerConfig, ...] or both "
        "expected_issuer= and expected_audience="
    )


def _select(issuers: Sequence[IssuerConfig], token: str) -> IssuerConfig:
    """Pick the trusted issuer whose name matches the token's own ``iss``.

    The claim is read WITHOUT verifying the signature — it has to be, the
    key to verify with is what we are looking up. Nothing else is trusted
    from this read: it decides which config to apply, and that config then
    re-checks ``iss`` cryptographically inside ``jwt.decode``.
    """
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
    """Verify ``token`` and return parsed :class:`Claims`.

    Pass ``issuers`` — the list this service trusts. ``expected_issuer`` +
    ``expected_audience`` remain accepted as the pre-FND-1 shorthand for a
    one-element list.

    Raises:
        InvalidTokenError: token is structurally malformed, signature
            does not verify, or the header algorithm is not RS256.
        ExpiredTokenError: ``exp`` is in the past (after applying
            ``clock_skew_seconds`` of leeway).
        InvalidIssuerError: ``iss`` claim matches no trusted issuer.
        InvalidAudienceError: ``aud`` does not include the selected
            issuer's audience.
        KidNotFoundError: header ``kid`` is missing or not in JWKS.
        MalformedClaimsError: claims payload violates the Claims schema
            (missing mandatory field, unexpected field, wrong type).
    """
    trusted = _resolve_issuers(issuers, expected_issuer, expected_audience)

    # Parse header without verifying signature, then assert alg upfront so
    # we never let python-jose pick an alg for us (algorithm-confusion CVE class).
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
        # python-jose lumps aud/iss errors under JWTClaimsError; discriminate
        # by message so we emit the right audit kind.
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
