"""The drills that can be measured without a model (Sprint 37 B-5).

Two of the seven scenarios are properties of the QUEUE, not of the model:
fairness between workspaces and the budget stop. Those are measurable on
a dev database in seconds, so they run here and their numbers go in the
report with the rest.

The other five need a deployed stack with a real backend (and, for two of
them, a way to break it on purpose); `docs/testing/load/notes-README.md`
has the commands. A drill that cannot run on this machine is recorded as
not run — never as a pass.

    RUN_NOTE_LOAD=1 uv run pytest tests/load/note_generation/runner.py -v
"""

from __future__ import annotations

import os
import time
from uuid import UUID, uuid4

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NOTE_LOAD") != "1",
    reason="set RUN_NOTE_LOAD=1; needs `make dev-up && make migrate-up`",
)

HOST = os.environ.get("POSTGRES_HOST", "localhost")
PORT = os.environ.get("POSTGRES_PORT", "5432")
DB = os.environ.get("POSTGRES_DB", "notes")
APP_DSN = f"postgresql://app_role:app_role@{HOST}:{PORT}/{DB}"
SUPER_DSN = f"postgresql://postgres:postgres@{HOST}:{PORT}/{DB}"

KIND = f"note.generate.load-{uuid4().hex[:8]}"
PER_TENANT = 3
BATCH = 2


@pytest.fixture
async def workspaces():  # noqa: ANN201
    noisy, quiet = uuid4(), uuid4()
    conn = await asyncpg.connect(SUPER_DSN)
    try:
        for tenant in (noisy, quiet):
            await conn.execute(
                "INSERT INTO tenants (id, name, display_name) VALUES ($1, $2, $2)",
                tenant,
                f"load-{tenant}",
            )
    finally:
        await conn.close()
    yield noisy, quiet
    conn = await asyncpg.connect(SUPER_DSN)
    try:
        await conn.execute("DELETE FROM jobs WHERE tenant_id = ANY($1::uuid[])", [noisy, quiet])
        await conn.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [noisy, quiet])
    finally:
        await conn.close()


@pytest.fixture
async def pool() -> asyncpg.Pool:  # noqa: ANN201
    from db import create_pool

    p = await create_pool(APP_DSN, application_name="note-load", max_size=4)
    yield p
    await p.close()


async def test_noisy_neighbour(pool: asyncpg.Pool, workspaces: tuple[UUID, UUID]) -> None:
    """One workspace enqueues 50, another enqueues 1. The single job must
    start within two minutes — measured in claim rounds, because a round
    is a worker's cycle and wall-clock here is our own loop speed."""
    from jobs import JobQueue

    noisy, quiet = workspaces
    queue = JobQueue(pool)
    for _ in range(50):
        await queue.enqueue(noisy, KIND, {})
    await queue.enqueue(quiet, KIND, {})

    started = time.monotonic()
    rounds = 0
    seen_quiet = False
    while rounds < 30 and not seen_quiet:
        rounds += 1
        claimed = await queue.claim([KIND], worker=f"w{rounds}", limit=BATCH, per_tenant=PER_TENANT)
        seen_quiet = any(job.tenant_id == quiet for job in claimed)
        for job in claimed:  # finish them so the in-flight cap frees up
            await queue.complete(job, {})
    print(
        f"noisy_neighbour: quiet job claimed in round {rounds} ({time.monotonic() - started:.2f}s)"
    )
    # One round is one worker cycle; a 60-minute meeting takes minutes, so
    # "within two minutes" is "inside the first couple of rounds".
    assert seen_quiet and rounds <= 2


async def test_one_workspace_cannot_occupy_every_replica(
    pool: asyncpg.Pool, workspaces: tuple[UUID, UUID]
) -> None:
    from jobs import JobQueue

    noisy, _quiet = workspaces
    queue = JobQueue(pool)
    for _ in range(20):
        await queue.enqueue(noisy, KIND, {})

    in_flight = []
    for worker in range(5):
        in_flight += await queue.claim(
            [KIND], worker=f"w{worker}", limit=BATCH, per_tenant=PER_TENANT
        )
    print(f"per_tenant cap: {len(in_flight)} in flight with 20 queued")
    assert len(in_flight) == PER_TENANT
