"""Shared plumbing for the native account routers: problem mapping, identity resolution, the step-up gate.

The gate is a dependency so "requires recent auth" is readable from the route declaration.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status

from audit import Severity
from auth import Claims

from ..config import settings
from ..deps import current_user, get_state
from ..domain.errors import ApiError
from ..domain.identity_repository import Identity

logger = logging.getLogger(__name__)


def as_problem(exc: ApiError) -> HTTPException:
    """Domain refusal → the problem body the API contract documents."""
    http_exc = HTTPException(status_code=exc.status_code, detail=exc.detail)
    http_exc.problem_extras = {"code": exc.code, **exc.extras}  # type: ignore[attr-defined]
    if exc.retry_after is not None:
        http_exc.headers = {"Retry-After": str(exc.retry_after)}
    return http_exc


def native_services() -> Any:
    """The native service bundle, or 404 (not 503) when this deployment has none."""
    state = get_state()
    services = getattr(state, "account_services", None)
    if services is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return services


async def current_identity(
    claims: Annotated[Claims, Depends(current_user)],
) -> Identity:
    """The identity behind the bearer token, read fresh on every request (never trusted from claims)."""
    services = native_services()
    identity: Identity | None = await services.identities.get(claims.sub)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no such identity")
    if identity.status in {"disabled", "deleted"}:
        exc = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account disabled")
        exc.problem_extras = {"code": "account_disabled"}  # type: ignore[attr-defined]
        raise exc
    return identity


async def recent_auth(
    claims: Annotated[Claims, Depends(current_user)],
) -> Claims:
    """Refuse unless this session proved itself inside the step-up window (``dependencies=[Depends(recent_auth)]``)."""
    services = native_services()
    try:
        await services.account.require_recent_auth(session_id=UUID(claims.sid))
    except ApiError as exc:
        raise as_problem(exc) from exc
    except ValueError as exc:
        # A native `sid` is always a UUID; anything else is Keycloak-era.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="this session cannot be verified"
        ) from exc
    return claims


async def audit(
    *,
    tenant_id: UUID | str,
    kind: str,
    payload: dict[str, Any],
    severity: Severity,
    actor_sub: UUID | None = None,
    target_id: UUID | None = None,
) -> None:
    """Best-effort audit. Never blocks the operation it describes."""
    state = get_state()
    try:
        await state.audit_writer.write_event(
            tenant_id=tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id)),
            kind=kind,
            actor_sub=actor_sub,
            target_kind="user",
            target_id=target_id,
            payload=payload,
            severity=severity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "auth.account.audit_write_failed",
            extra={"kind": kind, "error_class": type(exc).__name__},
        )


def platform_tenant() -> str:
    return settings.auth_platform_tenant_id
