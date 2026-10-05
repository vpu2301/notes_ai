"""Distinct exception classes per JWT verification failure mode, so callers can audit each differently."""

from __future__ import annotations


class AuthError(Exception):
    """Base class for every libs/auth verification failure."""


class InvalidTokenError(AuthError):
    """Token is structurally invalid, signature mismatched, or algorithm not RS256."""


class ExpiredTokenError(AuthError):
    """Token's ``exp`` claim is in the past (accounting for clock skew)."""


class InvalidIssuerError(AuthError):
    """Token's ``iss`` claim does not match the expected issuer."""


class InvalidAudienceError(AuthError):
    """Token's ``aud`` claim does not contain the expected audience."""


class KidNotFoundError(AuthError):
    """Header ``kid`` is not in JWKS (after refresh, or refresh suppressed by the rate limit)."""


class MalformedClaimsError(AuthError):
    """Token decoded but the claims payload violates the Claims schema (missing, unexpected, wrong type)."""


class JwksFetchError(AuthError):
    """Could not retrieve the JWKS document from the IdP (network / 5xx / parse)."""
