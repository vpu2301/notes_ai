"""SQL for tenants and memberships.

``app_role`` (RLS) for reads of the active tenant; ``tenant_writer`` for lifecycle,
membership writes and the cross-tenant lookup. The router owns the pool choice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

# Columns surfaced by the tenant API (``logo_bytes`` has its own endpoint).
TENANT_COLUMNS = """
    id, name, display_name, legal_name, slug, locale, timezone, status,
    is_active, logo_url, logo_content_type, contact_email, phone_number,
    website, address_line1, address_line2, postal_code, city,
    state_or_region, country, tax_id, registration_number,
    created_at, updated_at, kind
"""

# Whitelisted columns the PATCH endpoint may set.
UPDATABLE_TENANT_COLUMNS = frozenset(
    {
        "display_name",
        "legal_name",
        "slug",
        "locale",
        "timezone",
        "status",
        "is_active",
        "logo_url",
        "contact_email",
        "phone_number",
        "website",
        "address_line1",
        "address_line2",
        "postal_code",
        "city",
        "state_or_region",
        "country",
        "tax_id",
        "registration_number",
    }
)


# ── Tenants ──────────────────────────────────────────────────────────────


async def get_tenant(conn: asyncpg.Connection, *, tenant_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(f"SELECT {TENANT_COLUMNS} FROM tenants WHERE id = $1", tenant_id)


async def create_tenant(
    conn: asyncpg.Connection,
    *,
    name: str,
    display_name: str,
    slug: str,
    legal_name: str = "",
    locale: str = "uk",
    timezone: str = "Europe/Kyiv",
    contact_email: str = "",
    phone_number: str = "",
    website: str = "",
    address_line1: str = "",
    address_line2: str = "",
    postal_code: str = "",
    city: str = "",
    state_or_region: str = "",
    country: str = "",
    tax_id: str = "",
    registration_number: str = "",
    plan: str = "legacy",
    signup_source: str = "admin",
    plan_limits: str = "{}",
) -> asyncpg.Record:
    """``kind`` is always ``team`` here: personal workspaces are created with their identity."""
    return await conn.fetchrow(
        f"""
        INSERT INTO tenants
            (name, display_name, slug, legal_name, locale, timezone,
             contact_email, phone_number, website, address_line1, address_line2,
             postal_code, city, state_or_region, country, tax_id,
             registration_number, status, is_active, kind, plan, signup_source, plan_limits)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, 'active', true, 'team', $18, $19, $20::jsonb)
        RETURNING {TENANT_COLUMNS}
        """,
        name,
        display_name,
        slug,
        legal_name,
        locale,
        timezone,
        contact_email,
        phone_number,
        website,
        address_line1,
        address_line2,
        postal_code,
        city,
        state_or_region,
        country,
        tax_id,
        registration_number,
        plan,
        signup_source,
        plan_limits,
    )


async def update_tenant(
    conn: asyncpg.Connection, *, tenant_id: UUID, fields: dict[str, Any]
) -> asyncpg.Record | None:
    """Patch a whitelist of tenant columns; callers never pass raw request keys."""
    fields = {k: v for k, v in fields.items() if k in UPDATABLE_TENANT_COLUMNS}
    if not fields:
        return await get_tenant(conn, tenant_id=tenant_id)
    sets: list[str] = []
    args: list[Any] = []
    for col, val in fields.items():
        args.append(val)
        sets.append(f"{col} = ${len(args)}")
    args.append(tenant_id)
    return await conn.fetchrow(
        f"""
        UPDATE tenants
        SET {", ".join(sets)}, updated_at = now()
        WHERE id = ${len(args)}
        RETURNING {TENANT_COLUMNS}
        """,
        *args,
    )


async def set_logo(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    logo_bytes: bytes | None,
    logo_content_type: str,
    logo_url: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""
        UPDATE tenants
        SET logo_bytes = $2, logo_content_type = $3, logo_url = $4,
            updated_at = now()
        WHERE id = $1
        RETURNING {TENANT_COLUMNS}
        """,
        tenant_id,
        logo_bytes,
        logo_content_type,
        logo_url,
    )


async def get_logo(conn: asyncpg.Connection, *, tenant_id: UUID) -> tuple[bytes, str] | None:
    row = await conn.fetchrow(
        "SELECT logo_bytes, logo_content_type FROM tenants WHERE id = $1",
        tenant_id,
    )
    if row is None or row["logo_bytes"] is None:
        return None
    return bytes(row["logo_bytes"]), row["logo_content_type"] or "application/octet-stream"


# ── Memberships ──────────────────────────────────────────────────────────

MEMBERSHIP_COLUMNS = "id, tenant_id, user_sub, role, status, invited_by, created_at, updated_at"


async def list_tenants_for_user(
    conn: asyncpg.Connection, *, user_sub: UUID
) -> list[asyncpg.Record]:
    """Active memberships in active tenants (and archived ones the caller owns), with role; cross-tenant, so ``tenant_writer`` only."""
    return list(
        await conn.fetch(
            f"""
            SELECT {", ".join("t." + c.strip() for c in TENANT_COLUMNS.split(","))},
                   m.role AS membership_role, m.status AS membership_status
            FROM tenant_memberships m
            JOIN tenants t ON t.id = m.tenant_id
            WHERE m.user_sub = $1
              AND m.status = 'active'
              AND (t.status = 'active' OR (t.status = 'archived' AND m.role = 'owner'))
            ORDER BY (t.kind = 'personal') DESC, t.display_name, t.id
            """,
            user_sub,
        )
    )


async def get_membership(
    conn: asyncpg.Connection, *, tenant_id: UUID, user_sub: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {MEMBERSHIP_COLUMNS} FROM tenant_memberships "
        "WHERE tenant_id = $1 AND user_sub = $2",
        tenant_id,
        user_sub,
    )


async def list_members(conn: asyncpg.Connection, *, tenant_id: UUID) -> list[asyncpg.Record]:
    """Member roster with the profile from ``identities`` (``tenant_writer`` only; W1).

    LEFT JOIN so a membership whose identity is gone still lists, with a null profile.
    The platform role is computed by the caller from ``m.role``.
    """
    return list(
        await conn.fetch(
            """
            SELECT m.id, m.tenant_id, m.user_sub, m.role, m.status,
                   m.invited_by, m.created_at, m.updated_at, m.left_at,
                   i.email AS email, i.display_name AS display_name,
                   i.status AS identity_status
            FROM tenant_memberships m
            LEFT JOIN identities i ON i.id = m.user_sub
            WHERE m.tenant_id = $1
            ORDER BY m.role, m.created_at
            """,
            tenant_id,
        )
    )


async def add_member(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    user_sub: UUID,
    role: str,
    invited_by: UUID | None,
    status: str = "active",
) -> asyncpg.Record:
    return await conn.fetchrow(
        f"""
        INSERT INTO tenant_memberships (tenant_id, user_sub, role, status, invited_by)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING {MEMBERSHIP_COLUMNS}
        """,
        tenant_id,
        user_sub,
        role,
        status,
        invited_by,
    )


async def update_member_role(
    conn: asyncpg.Connection, *, tenant_id: UUID, user_sub: UUID, role: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""
        UPDATE tenant_memberships
        SET role = $3, updated_at = now()
        WHERE tenant_id = $1 AND user_sub = $2
        RETURNING {MEMBERSHIP_COLUMNS}
        """,
        tenant_id,
        user_sub,
        role,
    )


async def remove_member(conn: asyncpg.Connection, *, tenant_id: UUID, user_sub: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM tenant_memberships WHERE tenant_id = $1 AND user_sub = $2",
        tenant_id,
        user_sub,
    )
    return result.endswith(" 1")


async def count_active_owners(
    conn: asyncpg.Connection, *, tenant_id: UUID, exclude_sub: UUID | None = None
) -> int:
    n = await conn.fetchval(
        """
        SELECT count(*) FROM tenant_memberships
        WHERE tenant_id = $1 AND role = 'owner' AND status = 'active'
          AND ($2::uuid IS NULL OR user_sub <> $2)
        """,
        tenant_id,
        exclude_sub,
    )
    return int(n or 0)


async def resolve_sub_by_email(
    conn: asyncpg.Connection, *, tenant_id: UUID, email: str
) -> UUID | None:
    """E-mail → identity id, only for someone who already holds a membership in ``tenant_id``.

    Scoped on purpose (W1): an address cannot be probed across the platform. Bringing
    in someone new is an invitation (W2), not a lookup.
    """
    row = await conn.fetchrow(
        """
        SELECT i.id FROM identities i
        WHERE i.email = lower($2) AND i.status <> 'deleted'
          AND EXISTS (SELECT 1 FROM tenant_memberships m
                      WHERE m.tenant_id = $1 AND m.user_sub = i.id)
        """,
        tenant_id,
        email,
    )
    return row["id"] if row is not None else None


async def seat_meter(conn: asyncpg.Connection, *, tenant_id: UUID) -> tuple[int, int | None]:
    """(active members, `plan_limits.members`) — display only (W2); None = no recorded limit."""
    row = await conn.fetchrow(
        """
        SELECT (SELECT count(*) FROM tenant_memberships
                 WHERE tenant_id = $1 AND status = 'active') AS active,
               (plan_limits ->> 'members')::int AS seat_limit
          FROM tenants WHERE id = $1
        """,
        tenant_id,
    )
    if row is None:
        return 0, None
    return int(row["active"]), row["seat_limit"]


async def leave(conn: asyncpg.Connection, *, tenant_id: UUID, user_sub: UUID) -> bool:
    """Your own row becomes `suspended` with `left_at`; the roster shows "Left" until the sweeper."""
    result = await conn.execute(
        """
        UPDATE tenant_memberships SET status = 'suspended', left_at = now()
         WHERE tenant_id = $1 AND user_sub = $2 AND status = 'active'
        """,
        tenant_id,
        user_sub,
    )
    return result.endswith(" 1")


async def dissolve(conn: asyncpg.Connection, *, tenant_id: UUID) -> None:
    """Soft: the tenant is `dissolved`, every membership `suspended` (restorable for 30 days)."""
    await conn.execute(
        "UPDATE tenants SET status = 'dissolved', is_active = false WHERE id = $1", tenant_id
    )
    await conn.execute(
        "UPDATE tenant_memberships SET status = 'suspended' WHERE tenant_id = $1", tenant_id
    )


async def archive(conn: asyncpg.Connection, *, tenant_id: UUID) -> None:
    """Closed for everyone, nothing deleted; memberships stay as they are so a restore brings everyone back."""
    await conn.execute(
        "UPDATE tenants SET status = 'archived', is_active = false WHERE id = $1", tenant_id
    )


async def unarchive(conn: asyncpg.Connection, *, tenant_id: UUID) -> None:
    await conn.execute(
        "UPDATE tenants SET status = 'active', is_active = true WHERE id = $1 AND status = 'archived'",
        tenant_id,
    )


async def count_other_active_members(
    conn: asyncpg.Connection, *, tenant_id: UUID, user_sub: UUID
) -> int:
    n = await conn.fetchval(
        """
        SELECT count(*) FROM tenant_memberships
         WHERE tenant_id = $1 AND user_sub <> $2 AND status = 'active'
        """,
        tenant_id,
        user_sub,
    )
    return int(n or 0)


async def sweep_left_members(conn: asyncpg.Connection, *, older_than_days: int = 30) -> int:
    """Remove "Left" rows past the window so an admin's roster stays honest (W2)."""
    result = await conn.execute(
        """
        DELETE FROM tenant_memberships
         WHERE left_at IS NOT NULL AND status = 'suspended'
           AND left_at < now() - ($1::int * interval '1 day')
        """,
        older_than_days,
    )
    return int(result.split()[-1])
