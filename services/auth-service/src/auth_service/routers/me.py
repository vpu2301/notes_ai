"""GET /auth/me — verified claims, the global identity, and where it can go.

S21 adds `db_user.mfa_reminder`: the open access-review request that this
user enrols a second factor. The SPA carries it as an undismissable banner
until `mfa_enrolled_at` is set, so this endpoint is what makes the reminder
"stand" rather than flash past as a notification.

Reading it here crosses no boundary — the subject learning that they were
asked to secure their own account is the whole point — but note what is NOT
returned: WHO asked. Only their role. An access-review finding is between
the reviewer and the audit log; naming them turns a security ask into an
interpersonal one.

IDX-B3 adds `identity` and `memberships`, and they are the reason this
endpoint can outlive `db_user`. A page load has no `AuthResult` to read —
the session is restored from the refresh cookie — so without them the SPA
would have to derive a person from the per-tenant `users` row, which is
exactly the table IDX-B2 deletes. Both are **null / empty in keycloak
mode**, where there are no `identities` rows to read; that is a real
deployment state and not an error, so this route stays 200 rather than
adopting the 404 posture the native-only routers take. A client must
therefore treat `identity` as optional and fall back to `db_user` until
the cut-over completes.
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
    """The global principal behind the bearer, and every workspace it holds.

    Best-effort by construction. `/auth/me` is what the SPA hydrates from
    on every page load, and an identity store that is absent (keycloak
    mode) or briefly unreachable must degrade to "no identity" rather than
    fail the whole call — the claims in the token are already enough to
    render a signed-in shell.
    """
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
        # Belt and braces on the join's `resolved_at IS NULL`: if enrolment
        # ever lands without the resolve (the UPDATE pair in mfa.py is
        # best-effort against a DB hiccup), an enrolled user must still not
        # be told to go and enrol.
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
