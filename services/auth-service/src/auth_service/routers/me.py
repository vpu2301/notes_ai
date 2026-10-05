"""GET /auth/me — verified claims, the global identity, and where it can go.

`mfa_reminder` names the requester's role, never who asked. `identity` and
`memberships` are null/empty in keycloak mode (a real state, so still 200).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from auth import Claims
from db import tenant_connection

from ..deps import current_user, get_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _identity_and_memberships(
    claims: Claims,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
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


@router.get("/me", summary="Return verified claims, the identity, and its memberships")
async def me(claims: Annotated[Claims, Depends(current_user)]) -> dict[str, Any]:
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
    db_user: dict[str, Any] | None = None
    if row is not None:
        enrolled_at = row["mfa_enrolled_at"]
        # Belt and braces: an enrolled user must never be told to enrol.
        reminder: dict[str, Any] | None = None
        if row["last_reminded_at"] is not None and enrolled_at is None:
            reminder = {
                "requested_by_role": row["requested_by_role"],
                "first_reminded_at": row["first_reminded_at"].isoformat(),
                "last_reminded_at": row["last_reminded_at"].isoformat(),
                "reminder_count": row["reminder_count"],
            }
        db_user = {
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
            "mfa_reminder": reminder,
        }

    identity, memberships = await _identity_and_memberships(claims)
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
        "db_user": db_user,
    }
