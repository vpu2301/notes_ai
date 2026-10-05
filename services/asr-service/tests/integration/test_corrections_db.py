"""Sprint TQ3 — the spelling overlay against the real schema (migration 0066)
and RLS: plan stored once, decisions with the rev check, recompute keeping
people's decisions, the glossary read, and another tenant seeing nothing.

Skipped unless RUN_DB_INTEGRATION=1 (needs `make dev-up && make migrate-up`).
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from asr_service.domain import corrections
from asr_service.domain.entity_unify import Proposal
from db import tenant_connection

from .test_rediarize_db import SU_DSN, _job, pytestmark, world  # noqa: F401 — fixture + skip

PLAN = [
    Proposal(
        to_text="Handala",
        from_forms=("Andala", "Handela"),
        occurrences=({"s": 5, "w": 2, "n": 1, "t": 50_800}, {"s": 7, "w": 2, "n": 1, "t": 70_800}),
        source="majority",
        confidence=0.853,
        status="accepted",
    ),
    Proposal(
        to_text="Welchering",
        from_forms=("Welcherung",),
        occurrences=({"s": 1, "w": 0, "n": 1, "t": 10_000},) * 3,
        source="majority",
        confidence=0.71,
        status="proposed",
    ),
]


async def test_a_plan_is_stored_once_and_another_tenant_sees_none_of_it(world: dict) -> None:  # noqa: F811
    pool, a, b = world["pool"], world["a"], world["b"]
    job = await _job(pool, a)
    async with tenant_connection(pool, a) as c:
        assert (await corrections.job_state(c, job_id=job)).status is None
        assert await corrections.store(c, tenant_id=a, job_id=job, status="done", proposals=PLAN)
        assert not await corrections.store(
            c, tenant_id=a, job_id=job, status="done", proposals=PLAN
        )
        rows = await corrections.list_rows(c, job_id=job)
        state = await corrections.job_state(c, job_id=job)
    assert [r.to_text for r in rows] == ["Handala", "Welchering"]
    assert (state.status, state.rev) == ("done", 1)
    assert rows[0].occurrences[0] == {"s": 5, "w": 2, "n": 1, "t": 50_800}
    # RLS probe: tenant B reads nothing and can decide nothing.
    async with tenant_connection(pool, b) as c:
        assert await corrections.list_rows(c, job_id=job) == []
        assert await corrections.job_state(c, job_id=job) is None
        assert (
            await corrections.decide(
                c,
                job_id=job,
                correction_id=rows[0].id,
                status="rejected",
                to_text=None,
                decided_by=uuid4(),
                expected_rev=1,
            )
            is None
        )
        assert await c.fetchval("SELECT count(*) FROM transcript_corrections") == 0


async def test_decisions_check_the_rev_and_are_idempotent(world: dict) -> None:  # noqa: F811
    pool, a = world["pool"], world["a"]
    job = await _job(pool, a)
    person = uuid4()
    async with tenant_connection(pool, a) as c:
        await corrections.store(c, tenant_id=a, job_id=job, status="done", proposals=PLAN)
        handala = (await corrections.list_rows(c, job_id=job))[0]
        with pytest.raises(corrections.StaleRevError):
            await corrections.decide(
                c, job_id=job, correction_id=handala.id, status="rejected",
                to_text=None, decided_by=person, expected_rev=0,
            )  # fmt: skip
        row, rev = await corrections.decide(
            c, job_id=job, correction_id=handala.id, status="rejected",
            to_text=None, decided_by=person, expected_rev=1,
        )  # fmt: skip
        assert (row.status, row.decided_by, rev) == ("rejected", person, 2)
        # The same decision again: no-op, even with an old rev.
        again, rev2 = await corrections.decide(
            c, job_id=job, correction_id=handala.id, status="rejected",
            to_text=None, decided_by=person, expected_rev=1,
        )  # fmt: skip
        assert (again.status, rev2) == ("rejected", 2)
        welch = (await corrections.list_rows(c, job_id=job))[1]
        with pytest.raises(corrections.ToTextTakenError):
            await corrections.decide(
                c, job_id=job, correction_id=welch.id, status="accepted",
                to_text="Handala", decided_by=person, expected_rev=2,
            )  # fmt: skip
        edited, _ = await corrections.decide(
            c, job_id=job, correction_id=welch.id, status="accepted",
            to_text="Peter Welchering", decided_by=person, expected_rev=2,
        )  # fmt: skip
        assert (edited.to_text, edited.source, edited.status) == (
            "Peter Welchering",
            "user",
            "accepted",
        )


async def test_recompute_refreshes_the_system_rows_and_keeps_peoples_decisions(world: dict) -> None:  # noqa: F811
    pool, a = world["pool"], world["a"]
    job = await _job(pool, a)
    async with tenant_connection(pool, a) as c:
        await corrections.store(c, tenant_id=a, job_id=job, status="done", proposals=PLAN)
        handala = (await corrections.list_rows(c, job_id=job))[0]
        await corrections.decide(
            c, job_id=job, correction_id=handala.id, status="rejected",
            to_text=None, decided_by=uuid4(), expected_rev=1,
        )  # fmt: skip
        fresh = [
            Proposal(
                "Handala",
                ("Andala",),
                ({"s": 5, "w": 2, "n": 1, "t": 50_800},),
                "glossary",
                0.95,
                "accepted",
            ),
            Proposal(
                "Welchering",
                ("Welcherung", "Welchrin"),
                PLAN[1].occurrences,
                "calendar",
                0.9,
                "accepted",
            ),
        ]
        rev = await corrections.recompute(
            c, tenant_id=a, job_id=job, status="done", proposals=fresh
        )
        rows = {r.to_text: r for r in await corrections.list_rows(c, job_id=job)}
    assert rev == 3
    assert rows["Handala"].status == "rejected", "a person's reject outlives a recompute"
    assert (rows["Welchering"].source, rows["Welchering"].status) == ("calendar", "accepted")


async def test_the_glossary_is_read_per_tenant(world: dict) -> None:  # noqa: F811
    pool, a, b = world["pool"], world["a"], world["b"]
    async with tenant_connection(pool, a) as c:
        await c.execute(
            "INSERT INTO workspace_glossary (tenant_id, term, kind, heard_as, created_by)"
            " VALUES ($1, 'Handala', 'term', ARRAY['Handler'], $2)",
            a,
            uuid4(),
        )
        assert await corrections.glossary_terms(c) == [("Handala", ["Handler"])]
    async with tenant_connection(pool, b) as c:
        assert await corrections.glossary_terms(c) == []
    su = await asyncpg.connect(SU_DSN)  # the shared teardown knows no glossary rows
    try:
        await su.execute("DELETE FROM workspace_glossary WHERE tenant_id = $1", a)
    finally:
        await su.close()
