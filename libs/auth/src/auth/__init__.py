"""JWT verification, JWKS caching, FastAPI integration (ADR-0006, ADR-0047)."""

from __future__ import annotations

from .claims import Claims
from .context import (
    current_claims,
    current_tenant_id,
    require_current_claims,
    reset_current_claims,
    set_current_claims,
)
from .dependencies import build_current_user, requires_mfa
from .exceptions import (
    AuthError,
    ExpiredTokenError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    JwksFetchError,
    KidNotFoundError,
    MalformedClaimsError,
)
from .issuers import (
    IssuerConfig,
    IssuerConfigError,
    issuer_url_map,
    issuers_from_env,
    parse_issuers_json,
)
from .jwks import JwksCache, JwksMetrics
from .perms import (
    ALLOW,
    KNOWN_ROLES,
    KNOWN_TARGET_KINDS,
    Action,
    AuthzDeniedError,
    Role,
    TargetKind,
    can,
    can_claims,
    check,
    check_any,
)
from .revocation import (
    RedisSessionDenylist,
    SessionDenylist,
    build_session_denylist,
)
from .verifier import verify_token

__all__ = [
    "ALLOW",
    "Action",
    "AuthError",
    "AuthzDeniedError",
    "Claims",
    "ExpiredTokenError",
    "InvalidAudienceError",
    "InvalidIssuerError",
    "InvalidTokenError",
    "IssuerConfig",
    "IssuerConfigError",
    "JwksCache",
    "JwksFetchError",
    "JwksMetrics",
    "KNOWN_ROLES",
    "KNOWN_TARGET_KINDS",
    "KidNotFoundError",
    "MalformedClaimsError",
    "RedisSessionDenylist",
    "Role",
    "SessionDenylist",
    "TargetKind",
    "build_current_user",
    "build_session_denylist",
    "can",
    "can_claims",
    "check",
    "check_any",
    "current_claims",
    "current_tenant_id",
    "issuer_url_map",
    "issuers_from_env",
    "parse_issuers_json",
    "require_current_claims",
    "requires_mfa",
    "reset_current_claims",
    "set_current_claims",
    "verify_token",
]
