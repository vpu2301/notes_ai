"""Dependency wiring for the template service.

Kept separate from main.py so router modules can import the dependencies
without triggering a circular import at module-load time.
"""

from auth import JwksCache, build_current_user, issuer_url_map, issuers_from_env

from .config import settings

# FND-1 / ADR-0047: the issuer list, not a single issuer string. The cache
# and the dependency are built from the same list so they cannot drift.
_issuers = issuers_from_env(
    settings.auth_issuers_json,
    issuer=settings.auth_issuer,
    jwks_url=settings.auth_jwks_url,
    audience=settings.auth_audience,
)

_jwks_cache = JwksCache(issuer_to_url=issuer_url_map(_issuers))

current_user = build_current_user(
    jwks_cache=_jwks_cache,
    issuers=_issuers,
    clock_skew_seconds=settings.auth_clock_skew_seconds,
)


async def close_auth() -> None:
    """Close the JWKS HTTP client on shutdown."""
    await _jwks_cache.aclose()
