"""End-to-end RLS isolation on a temp table. Skipped unless RUN_DB_INTEGRATION=1 and the dev stack is up."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest

from db import create_pool, tenant_connection

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="RUN_DB_INTEGRATION not set — start dev stack and re-run with the flag.",
)

# Not the postgres superuser: BYPASSRLS would silently make RLS a no-op.
DSN = os.environ.get(
    "TEST_DSN",
    "postgresql://app_role:app_role@localhost:5432/notes",
)


@pytest.fixture
async def pool() -> object:
    p = await create_pool(DSN, application_name="db-integration-tests", min_size=2, max_size=4)
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
async def rls_table(pool: object) -> str:  # type: ignore[override]
    table = f"rls_test_{uuid4().hex}"
    async with pool.acquire() as c:  # type: ignore[attr-defined]
        await c.execute(
            f"""
            CREATE TABLE {table} (
                id BIGSERIAL PRIMARY KEY,
                tenant_id UUID NOT NULL,
                payload TEXT NOT NULL
            );
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            -- FORCE is required so RLS still applies if a future test (or the
            -- table owner) runs as a privileged role.
            ALTER TABLE {table} FORCE  ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
            """
        )
    try:
        yield table
    finally:
        async with pool.acquire() as c:  # type: ignore[attr-defined]
            await c.execute(f"DROP TABLE IF EXISTS {table}")


@pytest.mark.asyncio
async def test_tenants_cannot_see_each_other(pool: object, rls_table: str) -> None:  # type: ignore[override]
    a, b = uuid4(), uuid4()
    async with tenant_connection(pool, a) as conn:  # type: ignore[arg-type]
        await conn.execute(
            f"INSERT INTO {rls_table} (tenant_id, payload) VALUES ($1, $2)", a, "secret-a"
        )

    async with tenant_connection(pool, b) as conn:  # type: ignore[arg-type]
        rows = await conn.fetch(f"SELECT * FROM {rls_table}")
        assert rows == []

    async with tenant_connection(pool, a) as conn:  # type: ignore[arg-type]
        rows = await conn.fetch(f"SELECT payload FROM {rls_table}")
        assert [r["payload"] for r in rows] == ["secret-a"]


@pytest.mark.asyncio
async def test_concurrent_tenants_do_not_leak(pool: object, rls_table: str) -> None:  # type: ignore[override]
    """Run many tenants concurrently against the same pool and verify isolation."""

    async def insert_and_count(tid: UUID) -> int:
        async with tenant_connection(pool, tid) as conn:  # type: ignore[arg-type]
            await conn.execute(
                f"INSERT INTO {rls_table} (tenant_id, payload) VALUES ($1, $2)", tid, str(tid)
            )
            rows = await conn.fetch(f"SELECT count(*) AS n FROM {rls_table}")
            return int(rows[0]["n"])

    tenants = [uuid4() for _ in range(20)]
    counts = await asyncio.gather(*(insert_and_count(t) for t in tenants))
    # Each tenant must see exactly the row(s) they inserted — never another tenant's.
    assert all(c == 1 for c in counts), counts
