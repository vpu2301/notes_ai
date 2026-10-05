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
    created_at, updated_at
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
) -> asyncpg.Record:
    return await conn.fetchrow(
        f"""
        INSERT INTO tenants
            (name, display_name, slug, legal_name, locale, timezone,
             contact_email, phone_number, website, address_line1, address_line2,
             postal_code, city, state_or_region, country, tax_id,
             registration_number, status, is_active)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, 'active', true)
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
    """Active memberships in active tenants, with role; cross-tenant, so ``tenant_writer`` only."""
    return list(
        await conn.fetch(
            f"""
            SELECT {", ".join("t." + c.strip() for c in TENANT_COLUMNS.split(","))},
                   m.role AS membership_role, m.status AS membership_status
            FROM tenant_memberships m
            JOIN tenants t ON t.id = m.tenant_id
            WHERE m.user_sub = $1
              AND m.status = 'active'
              AND t.status = 'active'
            ORDER BY t.display_name, t.id
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
    """Member roster; LEFT JOIN ``users`` so cross-tenant members still list with a null profile."""
    return list(
        await conn.fetch(
            """
            SELECT m.id, m.tenant_id, m.user_sub, m.role, m.status,
                   m.invited_by, m.created_at, m.updated_at,
                   u.email AS email, u.display_name AS display_name,
                   u.role AS platform_role, u.status AS user_status
            FROM tenant_memberships m
            LEFT JOIN users u ON u.sub = m.user_sub
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


async def resolve_sub_by_email(conn: asyncpg.Connection, *, email: str) -> UUID | None:
    """Global email → sub lookup (``tenant_writer``); oldest active match wins on a cross-tenant collision."""
    row = await conn.fetchrow(
        """
        SELECT sub FROM users
        WHERE lower(email) = lower($1)
        ORDER BY (status = 'active') DESC, created_at
        LIMIT 1
        """,
        email,
    )
    return row["sub"] if row is not None else None
