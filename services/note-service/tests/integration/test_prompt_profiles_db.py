"""S3 against Postgres (RUN_DB_INTEGRATION=1, migration 0079 applied): workspace B can
neither list, read, activate nor point at workspace A's profiles, versions or
experiments; a saved version cannot be changed; activation is a compare-and-set.
Builds its own workspaces and deletes them; point POSTGRES_PORT at a disposable
database, not the dev one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from db import create_pool, tenant_connection
from note_service.domain import experiments
from note_service.domain import prompt_profile_repository as repo
from note_service.domain import prompt_profiles as profiles

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1; needs a migrated database",
)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("POSTGRES_DB", "notes")
SU_DSN = f"postgresql://postgres:postgres@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"
APP_DSN = f"postgresql://app_role:app_role@{POSTGRES_HOST}:{POSTGRES_PORT}/{DB_NAME}"
ADMIN = uuid4()


@pytest_asyncio.fixture
async def env() -> AsyncIterator[tuple[asyncpg.Pool, UUID, UUID]]:
    su = await asyncpg.connect(SU_DSN)
    pool = await create_pool(APP_DSN, application_name="s3-itest", min_size=1, max_size=2)
    a, b = uuid4(), uuid4()
    for tid in (a, b):
        await su.execute(
            "INSERT INTO tenants (id, name, display_name, kind, status, is_active)"
            " VALUES ($1, $2, $2, 'team', 'active', true)",
            tid,
            f"s3-{tid.hex[:6]}",
        )
    try:
        yield pool, a, b
    finally:
        for table in (
            "note_experiment_reviews", "note_experiment_runs", "note_experiments",
            "prompt_profile_activations", "prompt_profile_bindings",
            "prompt_profile_versions", "prompt_profiles",
        ):  # fmt: skip
            await su.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1)", [a, b])  # noqa: S608
        await su.execute("DELETE FROM tenants WHERE id = ANY($1)", [a, b])
        await pool.close()
        await su.close()


async def _version(pool: asyncpg.Pool, tenant: UUID) -> repo.Version:
    async with tenant_connection(pool, tenant) as conn:
        profile = await repo.create_profile(
            conn, tenant_id=tenant, name="p", description="", created_by=ADMIN
        )
        return await repo.create_version(
            conn,
            tenant_id=tenant,
            profile_id=profile.id,
            config=profiles.ProfileConfig(stages={"composition": "Short."}),
            created_by=ADMIN,
        )


async def test_another_workspace_sees_nothing(env: tuple[asyncpg.Pool, UUID, UUID]) -> None:
    pool, a, b = env
    version = await _version(pool, a)
    async with tenant_connection(pool, b) as conn:
        assert await repo.list_profiles(conn) == []
        assert await repo.list_versions(conn) == []
        assert await repo.fetch_version(conn, version_id=version.id) is None
        # B cannot point its binding at A's version: the composite foreign key refuses.
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await repo.activate(
                conn, tenant_id=b, version_id=version.id, expected_revision=0, actor=ADMIN
            )


async def test_b_cannot_write_rows_into_a(env: tuple[asyncpg.Pool, UUID, UUID]) -> None:
    pool, a, b = env
    async with tenant_connection(pool, b) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await repo.create_profile(conn, tenant_id=a, name="x", description="", created_by=ADMIN)


async def test_a_saved_version_cannot_be_changed(env: tuple[asyncpg.Pool, UUID, UUID]) -> None:
    pool, a, _b = env
    version = await _version(pool, a)
    async with tenant_connection(pool, a) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(
                "UPDATE prompt_profile_versions SET content_hash = 'x' WHERE id = $1", version.id
            )
        again = await repo.create_version(
            conn,
            tenant_id=a,
            profile_id=version.profile_id,
            config=profiles.ProfileConfig(),
            created_by=ADMIN,
        )
    assert again.version_number == 2


async def test_activation_is_a_compare_and_set(env: tuple[asyncpg.Pool, UUID, UUID]) -> None:
    pool, a, _b = env
    version = await _version(pool, a)
    async with tenant_connection(pool, a) as conn:
        moved = await repo.activate(
            conn, tenant_id=a, version_id=version.id, expected_revision=0, actor=ADMIN
        )
        assert moved.revision == 1
        with pytest.raises(repo.ActivationConflictError):
            await repo.activate(
                conn, tenant_id=a, version_id=None, expected_revision=0, actor=ADMIN
            )
        back = await repo.activate(
            conn, tenant_id=a, version_id=None, expected_revision=1, actor=ADMIN
        )
        assert back.profile_version_id is None and back.revision == 2
        assert len(await repo.history(conn)) == 2


async def test_experiments_are_per_workspace_and_idempotent(
    env: tuple[asyncpg.Pool, UUID, UUID],
) -> None:
    pool, a, b = env
    reservation = experiments.Estimate(cents=None, tokens=1000, runs=1)
    kwargs = {
        "created_by": ADMIN, "idempotency_key": "itest-key-1", "sources": [{"note_id": str(uuid4()), "transcript_rev": 1}],  # noqa: E501
        "candidates": [None], "repetitions": 1, "length": "standard", "output_language": "de",
        "budget_cap_cents": 0, "reservation": reservation, "run_snapshots": {0: {}},
    }  # fmt: skip
    async with tenant_connection(pool, a) as conn:
        first, created = await experiments.create(
            conn, experiment_id=uuid4(), tenant_id=a, **kwargs
        )
        again, created_again = await experiments.create(
            conn, experiment_id=uuid4(), tenant_id=a, **kwargs
        )
        assert created and not created_again and again.id == first.id
        with pytest.raises(experiments.ExperimentActiveError):
            await experiments.create(
                conn,
                experiment_id=uuid4(),
                tenant_id=a,
                **{**kwargs, "idempotency_key": "itest-key-2"},
            )
    async with tenant_connection(pool, b) as conn:
        assert await experiments.fetch(conn, experiment_id=first.id) is None
        assert await experiments.runs(conn, experiment_id=first.id) == []
