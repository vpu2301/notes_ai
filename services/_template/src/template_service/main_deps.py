"""Dependency wiring, separate from main.py to avoid circular imports from routers."""

from auth import JwksCache, build_current_user, issuer_url_map, issuers_from_env

from .config import settings

# Cache and dependency share one issuer list so they cannot drift.
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
