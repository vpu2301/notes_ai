"""Module-level holders for the lifespan-built dependencies, wired via ``Depends(...)``."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from opentelemetry import metrics

from audit import Severity
from auth import Action, AuthzDeniedError, Claims, TargetKind, check

from .main_deps import ServiceState

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth.authz")
_authz_denied_counter = _meter.create_counter(
    "mdx_authz_denied_total",
    description="Times requires() rejected a caller",
    unit="1",
)

# Filled by lifespan; raise if a router resolves a dep before lifespan ran.
_state: ServiceState | None = None


def install_state(state: ServiceState) -> None:
    global _state
    _state = state


def get_state() -> ServiceState:
    if _state is None:
        raise RuntimeError("ServiceState not installed; this code must run after lifespan startup")
    return _state


async def current_user(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Claims:
    """The auth dep; thin wrapper over the libs/auth closure so the signature stays stable."""
    state = get_state()
    if not hasattr(state, "_current_user_dep"):
        from auth import build_current_user

        from .config import settings
        from .main_deps import auth_issuers

        state._current_user_dep = build_current_user(  # type: ignore[attr-defined]
            jwks_cache=state.jwks_cache,
            # Issuer list chosen by mode (ADR-0047).
            issuers=auth_issuers(),
            clock_skew_seconds=settings.auth_clock_skew_seconds,
            denylist=state.denylist,
        )
    dep = state._current_user_dep  # type: ignore[attr-defined]
    result: Claims = await dep(request, authorization)
    return result


def requires(
    action: Action, target_kind: TargetKind, *, scope: str | None = None
) -> Callable[..., Awaitable[Claims]]:
    """Dependency enforcing the perms matrix: 403 + best-effort ``authz.denied`` audit on deny."""

    async def dep(claims: Annotated[Claims, Depends(current_user)]) -> Claims:
        try:
            check(claims, action=action, target_kind=target_kind, scope=scope)
        except AuthzDeniedError as exc:
            await _emit_authz_denied(exc)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"deny: roles={list(claims.roles)} cannot {action!r} "
                    f"on {target_kind!r}"
                    + (
                        f"; required scope {exc.required_scope!r}"
                        if exc.reason == "scope_missing"
                        else ""
                    )
                ),
            ) from exc
        return claims

    return dep


def requires_mfa() -> Callable[..., Awaitable[Claims]]:
    """MFA gate behind ``MDX_REQUIRE_MFA`` (read per call so tests can monkeypatch).

    Token without ``mfa``: not enrolled → 403 ``mfa_enrolment_required``;
    enrolled → 401 with the MFA challenge.
    """
    from .config import settings

    async def dep(
        claims: Annotated[Claims, Depends(current_user)],
    ) -> Claims:
        if settings.require_mfa and not claims.mfa:
            if not claims.mfa_enrolled:
                exc = HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="MFA enrolment required for this endpoint",
                )
                exc.problem_extras = {"code": "mfa_enrolment_required"}  # type: ignore[attr-defined]
                raise exc
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="MFA required for this endpoint",
                headers={"WWW-Authenticate": 'MFA realm="notes"'},
            )
        return claims

    return dep


async def _emit_authz_denied(exc: AuthzDeniedError) -> None:
    """Write an ``authz.denied`` sec event; never raise (a failed audit must not become a 500)."""
    _authz_denied_counter.add(
        1,
        {
            "action": exc.action,
            "target_kind": exc.target_kind,
            "reason": exc.reason,
        },
    )
    state = _state
    if state is None:
        return
    try:
        await state.audit_writer.write_event(
            tenant_id=exc.claims.tid,
            kind="authz.denied",
            actor_sub=exc.claims.sub,
            actor_role=(exc.claims.roles[0] if exc.claims.roles else None),
            target_kind=exc.target_kind,
            target_id=None,
            payload={
                "action": exc.action,
                "target_kind": exc.target_kind,
                "reason": exc.reason,
                "required_scope": exc.required_scope,
                "roles_seen": list(exc.claims.roles),
            },
            severity=Severity.SEC,
        )
    except Exception as audit_exc:
        logger.warning(
            "authz_denied.audit_write_failed",
            extra={
                "action": exc.action,
                "target_kind": exc.target_kind,
                "error": str(audit_exc),
                "error_class": type(audit_exc).__name__,
            },
        )
