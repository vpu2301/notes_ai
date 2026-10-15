"""GET /auth/me — verified claims, the global identity, and where it can go.

`mfa_reminder` names the requester's role, never who asked. `identity` and
`memberships` are null/empty in keycloak mode (a real state, so still 200).

W1 (ADR-0069): in dual/native mode `db_user` is derived from the active membership,
not read from the legacy single-tenant `users` row, so it is present in every
workspace the person switches to. It is deprecated; `active_membership` replaces it.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from auth import Claims
from db import tenant_connection

from .. import auth_metrics
from ..config import settings
from ..deps import current_user, get_state
from ..domain.identity_repository import Identity, Membership, platform_roles_for, primary_role
from ..domain.transport import client_type_of

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _lookup(claims: Claims) -> tuple[Identity | None, list[Membership]]:
    """The global principal behind the bearer and its workspaces; best-effort (degrades to "no identity")."""
    services = getattr(get_state(), "account_services", None)
    if services is None:
        return None, []
    try:
        identity = await services.identities.get(claims.sub)
        if identity is None:
            return None, []
        memberships = await services.identities.list_memberships(identity.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("auth.me.identity_lookup_failed", extra={"error_class": type(exc).__name__})
        return None, []
    return identity, memberships


def _shape(
    identity: Identity | None, memberships: list[Membership]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if identity is None:
        return None, []
    return (
        {
            "id": str(identity.id),
            "email": identity.email,
            "display_name": identity.display_name,
            "mfa_enabled": identity.mfa_enabled,
            "has_password": identity.has_password,
            "status": identity.status,
            "created_at": (identity.created_at.isoformat() if identity.created_at else None),
        },
        [
            {
                "tenant_id": str(m.tenant_id),
                "name": m.name,
                "kind": m.kind,
                "role": m.role,
                "status": m.status,
            }
            for m in memberships
        ],
    )


async def _identity_and_memberships(
    claims: Claims,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    return _shape(*await _lookup(claims))


def _reminder(row: Any, *, enrolled: bool) -> dict[str, Any] | None:
    # Belt and braces: an enrolled user must never be told to enrol.
    if row is None or row["last_reminded_at"] is None or enrolled:
        return None
    return {
        "requested_by_role": row["requested_by_role"],
        "first_reminded_at": row["first_reminded_at"].isoformat(),
        "last_reminded_at": row["last_reminded_at"].isoformat(),
        "reminder_count": row["reminder_count"],
    }


async def _derived_db_user(
    claims: Claims, identity: Identity, active: Membership
) -> dict[str, Any]:
    """The legacy `db_user` shape, computed from the identity and the active membership."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await conn.fetchrow(
            """
            SELECT requested_by_role, first_reminded_at, last_reminded_at, reminder_count
            FROM mfa_reminders
            WHERE subject_sub = $1 AND resolved_at IS NULL
            """,
            claims.sub,
        )
    enrolled_at = identity.updated_at if identity.mfa_enabled else None
    return {
        "sub": str(claims.sub),
        "tenant_id": str(claims.tid),
        "email": identity.email,
        "display_name": identity.display_name,
        "role": primary_role(set(platform_roles_for(active.role))),
        "status": active.status,
        "mfa_enrolled_at": enrolled_at.isoformat() if enrolled_at else None,
        # Sessions, not identities, know the last sign-in; the derived shape leaves it out.
        "last_login_at": None,
        "created_at": identity.created_at.isoformat() if identity.created_at else None,
        "mfa_reminder": _reminder(row, enrolled=identity.mfa_enabled),
    }


async def _legacy_db_user(claims: Claims) -> dict[str, Any] | None:
    """Keycloak mode: the home-tenant `users` row (null outside that tenant)."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await conn.fetchrow(
            """
            SELECT u.sub, u.tenant_id, u.email, u.display_name, u.role, u.status,
                   u.mfa_enrolled_at, u.last_login_at, u.created_at, u.updated_at,
                   r.requested_by_role, r.first_reminded_at, r.last_reminded_at,
                   r.reminder_count
            FROM users u
            LEFT JOIN mfa_reminders r
                   ON r.tenant_id = u.tenant_id
                  AND r.subject_sub = u.sub
                  AND r.resolved_at IS NULL
            WHERE u.sub = $1
            """,
            claims.sub,
        )
    if row is None:
        return None
    enrolled_at = row["mfa_enrolled_at"]
    return {
        "sub": str(row["sub"]),
        "tenant_id": str(row["tenant_id"]),
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "mfa_enrolled_at": (enrolled_at.isoformat() if enrolled_at else None),
        "last_login_at": (row["last_login_at"].isoformat() if row["last_login_at"] else None),
        # Lets a client show a first-run hint.
        "created_at": (row["created_at"].isoformat() if row["created_at"] else None),
        "mfa_reminder": _reminder(row, enrolled=enrolled_at is not None),
    }


@router.get("/me", summary="Return verified claims, the identity, and its memberships")
async def me(request: Request, claims: Annotated[Claims, Depends(current_user)]) -> dict[str, Any]:
    identity_row, membership_rows = await _lookup(claims)
    active = next((m for m in membership_rows if m.tenant_id == claims.tid), None)
    db_user: dict[str, Any] | None
    if settings.idp_mode != "keycloak" and identity_row is not None and active is not None:
        db_user = await _derived_db_user(claims, identity_row, active)
        source = "derived"
    else:
        db_user = await _legacy_db_user(claims)
        source = "legacy"
    if db_user is not None:
        # The W4 gate for dropping `db_user`: which clients still receive it.
        auth_metrics.me_legacy_db_user_counter.add(
            1, {"client": str(client_type_of(request)), "source": source}
        )

    identity, memberships = _shape(identity_row, membership_rows)
    personal = next((m for m in membership_rows if m.kind == "personal"), None)
    return {
        "claims": {
            "sub": str(claims.sub),
            "tid": str(claims.tid),
            "roles": claims.roles,
            "scope": claims.scope,
            "mfa": claims.mfa,
            "iss": claims.iss,
        },
        "identity": identity,
        "memberships": memberships,
        "active_membership": (
            {
                "tenant_id": str(active.tenant_id),
                "name": active.name,
                "kind": active.kind,
                "role": active.role,
                "status": active.status,
            }
            if active is not None
            else None
        ),
        "personal_tenant_id": str(personal.tenant_id) if personal is not None else None,
        # Deprecated (W1): derived from the active membership in dual/native mode; dropped in W4.
        "db_user": db_user,
    }
