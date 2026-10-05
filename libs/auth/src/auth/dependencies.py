"""FastAPI dependencies for libs/auth; failures are ``HTTPException(401)`` with a ``WWW-Authenticate: Bearer`` challenge."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from .claims import Claims
from .context import set_current_claims
from .exceptions import (
    AuthError,
    ExpiredTokenError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    KidNotFoundError,
    MalformedClaimsError,
)
from .issuers import IssuerConfig
from .jwks import JwksCache
from .revocation import SessionDenylist
from .verifier import verify_token

_WWW_AUTHENTICATE = 'Bearer realm="notes"'


def _unauthorized(detail: str, *, extra_challenge: str | None = None) -> HTTPException:
    challenge = _WWW_AUTHENTICATE
    if extra_challenge:
        challenge = f"{challenge}, {extra_challenge}"
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": challenge},
    )


def build_current_user(
    *,
    jwks_cache: JwksCache,
    issuers: Sequence[IssuerConfig] | None = None,
    expected_audience: str | None = None,
    expected_issuer: str | None = None,
    clock_skew_seconds: int = 30,
    denylist: SessionDenylist | None = None,
) -> Callable[..., Coroutine[None, None, Claims]]:
    """Return a FastAPI dependency that yields verified :class:`Claims`.

    Also sets the claims ContextVar and ``request.state.claims``. ``expected_audience`` +
    ``expected_issuer`` are the one-element shorthand for ``issuers``. ``denylist`` rejects
    revoked ``sid``/``sub`` with 401; ``None`` = no check; a down backend fails OPEN.
    """

    async def _current_user(
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> Claims:
        if authorization is None:
            raise _unauthorized("Authorization header is required")
        if not authorization.startswith("Bearer "):
            raise _unauthorized("Authorization header must use the Bearer scheme")
        token = authorization[len("Bearer ") :].strip()
        if not token:
            raise _unauthorized("Bearer token is empty")

        try:
            claims = await verify_token(
                token,
                jwks_cache=jwks_cache,
                issuers=issuers,
                expected_audience=expected_audience,
                expected_issuer=expected_issuer,
                clock_skew_seconds=clock_skew_seconds,
            )
        except ExpiredTokenError as exc:
            raise _unauthorized(f"Token expired: {exc}") from exc
        except InvalidAudienceError as exc:
            raise _unauthorized(f"Invalid audience: {exc}") from exc
        except InvalidIssuerError as exc:
            raise _unauthorized(f"Invalid issuer: {exc}") from exc
        except KidNotFoundError as exc:
            raise _unauthorized(f"Signing key not recognised: {exc}") from exc
        except MalformedClaimsError as exc:
            raise _unauthorized(f"Token claims malformed: {exc}") from exc
        except InvalidTokenError as exc:
            raise _unauthorized(f"Invalid token: {exc}") from exc
        except AuthError as exc:
            raise _unauthorized(str(exc)) from exc

        if denylist is not None and await denylist.is_revoked(sid=claims.sid, sub=str(claims.sub)):
            raise _unauthorized("Session has been revoked")

        set_current_claims(claims)
        request.state.claims = claims
        return claims

    return _current_user


def requires_mfa(claims: Claims) -> Claims:
    """Reject non-MFA tokens with 401 (no feature-flag awareness)."""
    if not claims.mfa:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA required for this endpoint",
            headers={"WWW-Authenticate": 'MFA realm="notes"'},
        )
    return claims
