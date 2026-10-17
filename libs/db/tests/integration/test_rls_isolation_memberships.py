"""RLS isolation for ``tenant_memberships`` (app_role SELECT only, writes are ``tenant_writer``). Skipped unless
``RUN_DB_INTEGRATION=1``.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

from db import create_pool, tenant_connection

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1 to run; needs `make dev-up && make migrate-up`",
)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("POSTGRES_DB", "notes")

APP_DSN = f"postgresql://app_role:app_role@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"
WRITER_DSN = f"postgresql://tenant_writer:tenant_writer@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"


@pytest.fixture
async def writer_pool() -> asyncpg.Pool:
    p = await create_pool(WRITER_DSN, application_name="rls-mem-writer")
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
async def app_pool() -> asyncpg.Pool:
    p = await create_pool(APP_DSN, application_name="rls-mem-app")
    try:
        yield p
    finally:
        await p.close()


async def _seed(writer_pool: asyncpg.Pool, tenant_id, name: str) -> None:
    async with writer_pool.acquire() as c:
        await c.execute(
            "INSERT INTO tenants (id, name, display_name, slug) VALUES ($1,$2,$3,$2)",
            tenant_id,
            name,
            name.title(),
        )
    # Membership writes are tenant_writer-only; scope via app.tenant_id.
    async with tenant_connection(writer_pool, tenant_id) as c:
        await c.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_sub, role) VALUES ($1,$2,'owner')",
            tenant_id,
            uuid4(),
        )


@pytest.mark.asyncio
async def test_memberships_isolated_across_tenants(
    app_pool: asyncpg.Pool, writer_pool: asyncpg.Pool
) -> None:
    a, b = uuid4(), uuid4()
    su_dsn = f"postgresql://postgres:postgres@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"
    try:
        await _seed(writer_pool, a, f"mem-a-{a.hex[:8]}")
        await _seed(writer_pool, b, f"mem-b-{b.hex[:8]}")

        # Tenant B's app_role connection sees zero of tenant A's memberships.
        async with tenant_connection(app_pool, b) as c:
            leaked = await c.fetch("SELECT 1 FROM tenant_memberships WHERE tenant_id = $1", a)
            assert leaked == [], "tenant B leaked tenant A memberships"

        # Tenant A sees exactly its own.
        async with tenant_connection(app_pool, a) as c:
            own = await c.fetch("SELECT tenant_id FROM tenant_memberships")
            assert {r["tenant_id"] for r in own} == {a}

        # app_role holds SELECT only — an INSERT must be refused by grants/RLS.
        async with tenant_connection(app_pool, a) as c:
            with pytest.raises(asyncpg.PostgresError):
                await c.execute(
                    "INSERT INTO tenant_memberships (tenant_id, user_sub, role) "
                    "VALUES ($1,$2,'admin')",
                    a,
                    uuid4(),
                )
    finally:
        su = await asyncpg.connect(su_dsn)
        try:
            await su.execute(
                "DELETE FROM tenant_memberships WHERE tenant_id = ANY($1::uuid[])", [a, b]
            )
            await su.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [a, b])
        finally:
            await su.close()


@pytest.mark.asyncio
async def test_invitations_writer_crosses_tenants_app_role_reads_only_its_own(
    app_pool: asyncpg.Pool, writer_pool: asyncpg.Pool
) -> None:
    """W2 (0072): `tenant_invitations` follows the membership pattern — auth-service's
    tenant_writer writes across tenants; app_role SELECTs the scoped tenant only."""
    a, b, inviter = uuid4(), uuid4(), uuid4()
    su_dsn = f"postgresql://postgres:postgres@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"
    try:
        await _seed(writer_pool, a, f"inv-a-{a.hex[:8]}")
        await _seed(writer_pool, b, f"inv-b-{b.hex[:8]}")
        async with writer_pool.acquire() as w:
            await w.execute(
                "INSERT INTO identities (id, email) VALUES ($1, $2)",
                inviter,
                f"inv-{inviter.hex[:8]}@example.test",
            )
            for tenant in (a, b):
                await w.execute(
                    "INSERT INTO tenant_invitations (tenant_id, email, role, invited_by, "
                    "token_hash, expires_at) VALUES ($1, 'x@example.test', 'member', $2, $3, "
                    "now() + interval '1 day')",
                    tenant,
                    inviter,
                    uuid4().bytes,
                )

        async with tenant_connection(app_pool, b) as c:
            rows = await c.fetch("SELECT tenant_id FROM tenant_invitations")
            assert {r["tenant_id"] for r in rows} == {b}, (
                "tenant B saw another tenant's invitations"
            )

        async with tenant_connection(app_pool, a) as c:
            with pytest.raises(asyncpg.PostgresError):
                await c.execute(
                    "UPDATE tenant_invitations SET revoked_at = now() WHERE tenant_id = $1", a
                )
    finally:
        su = await asyncpg.connect(su_dsn)
        try:
            await su.execute(
                "DELETE FROM tenant_invitations WHERE tenant_id = ANY($1::uuid[])", [a, b]
            )
            await su.execute("DELETE FROM identities WHERE id = $1", inviter)
            await su.execute(
                "DELETE FROM tenant_memberships WHERE tenant_id = ANY($1::uuid[])", [a, b]
            )
            await su.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [a, b])
        finally:
            await su.close()
