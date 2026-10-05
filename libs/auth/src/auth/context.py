"""Per-request ContextVar carrying the verified :class:`Claims` (FastAPI runs each request in its own Task)."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from .claims import Claims

_current_claims: ContextVar[Claims | None] = ContextVar("_current_claims", default=None)


def set_current_claims(claims: Claims) -> None:
    """Bind ``claims`` to the current async Task / request."""
    _current_claims.set(claims)


def reset_current_claims() -> None:
    """Clear the ContextVar (test helper / explicit logout flows)."""
    _current_claims.set(None)


def current_claims() -> Claims | None:
    """Return the claims bound to this request, or ``None`` outside a request."""
    return _current_claims.get()


def current_tenant_id() -> UUID | None:
    """Convenience: return the ``tid`` from the bound claims, if any."""
    claims = _current_claims.get()
    return claims.tid if claims is not None else None


def require_current_claims() -> Claims:
    """Return claims or raise ``RuntimeError`` (for non-handler code paths)."""
    claims = _current_claims.get()
    if claims is None:
        raise RuntimeError(
            "current_claims is unset; this code path must run inside an authenticated request scope"
        )
    return claims
