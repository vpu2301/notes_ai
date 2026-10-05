"""The reaper collects what a dead worker left behind, and never a job that finished
between the scan and the write. The DB is faked at the repository boundary."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from asr_models import JobErrorKind
from asr_service.domain import reaper, repository

_TENANT = uuid4()


class _FakeConn:
    def __init__(self, tenants: list[UUID]) -> None:
        self._tenants = tenants

    async def fetch(self, _sql: str, *_args: Any) -> list[dict[str, UUID]]:
        return [{"tenant_id": t} for t in self._tenants]


class _FakePool:
    def __init__(self, tenants: list[UUID]) -> None:
        self._conn = _FakeConn(tenants)

    @contextlib.asynccontextmanager
    async def acquire(self) -> Any:
        yield self._conn


class _FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _state(tenants: list[UUID]) -> Any:
    return SimpleNamespace(app_pool=_FakePool(tenants), audit_writer=_FakeAuditWriter())


def _stale(status: str) -> repository.StaleJobRow:
    return repository.StaleJobRow(id=uuid4(), status=status, requester_sub=uuid4(), started_at=None)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the two repository calls the reaper makes."""
    state: dict[str, Any] = {
        "candidates": [],
        "failed": [],
        "fail_result": True,
        "rediarize": [],
        "rediarize_failed": [],
    }

    async def fake_list(_conn: Any, **_kwargs: Any) -> list[repository.StaleJobRow]:
        return list(state["candidates"])

    async def fake_fail(
        _conn: Any,
        *,
        job_id: UUID,
        error_kind: str,
        error_detail: str,
        only_if_status: tuple[str, ...] = ("queued", "running"),
    ) -> bool:
        state["failed"].append(
            {
                "job_id": job_id,
                "error_kind": error_kind,
                "detail": error_detail,
                "only_if_status": only_if_status,
            }
        )
        return bool(state["fail_result"])

    async def fake_list_rediarize(_conn: Any, **_kwargs: Any) -> list[Any]:
        return list(state["rediarize"])

    async def fake_fail_rediarize(
        _conn: Any, *, job_id: UUID, error: str, only_if_status: str, older_than_seconds: float
    ) -> bool:
        state["rediarize_failed"].append(
            {"job_id": job_id, "error": error, "only_if_status": only_if_status}
        )
        state["rediarize_grace"] = older_than_seconds
        return bool(state["fail_result"])

    monkeypatch.setattr(repository, "list_stale_jobs", fake_list)
    monkeypatch.setattr(repository, "fail_job", fake_fail)
    monkeypatch.setattr(repository, "list_stale_rediarize", fake_list_rediarize)
    monkeypatch.setattr(repository, "fail_rediarize", fake_fail_rediarize)

    @contextlib.asynccontextmanager
    async def fake_tenant_connection(_pool: Any, _tenant_id: UUID) -> Any:
        yield object()

    monkeypatch.setattr(reaper, "tenant_connection", fake_tenant_connection)
    return state


async def test_running_job_is_reaped_as_worker_lost(db: dict[str, Any]) -> None:
    db["candidates"] = [_stale("running")]
    state = _state([_TENANT])

    assert await reaper.sweep_once(state) == 1
    assert db["failed"][0]["error_kind"] == str(JobErrorKind.WORKER_LOST)
    # Conditional on the status we scanned.
    assert db["failed"][0]["only_if_status"] == ("running",)


async def test_queued_job_is_reaped_as_queue_lost(db: dict[str, Any]) -> None:
    db["candidates"] = [_stale("queued")]
    state = _state([_TENANT])

    assert await reaper.sweep_once(state) == 1
    assert db["failed"][0]["error_kind"] == str(JobErrorKind.QUEUE_LOST)
    assert db["failed"][0]["only_if_status"] == ("queued",)


async def test_a_job_that_finished_first_is_not_counted(db: dict[str, Any]) -> None:
    # The conditional UPDATE matched nothing: the job keeps its outcome, not audited.
    db["candidates"] = [_stale("running")]
    db["fail_result"] = False
    state = _state([_TENANT])

    assert await reaper.sweep_once(state) == 0
    assert state.audit_writer.events == []


async def test_reaped_job_is_audited(db: dict[str, Any]) -> None:
    row = _stale("running")
    db["candidates"] = [row]
    state = _state([_TENANT])

    await reaper.sweep_once(state)

    event = state.audit_writer.events[0]
    assert event["target_id"] == str(row.id)
    assert event["payload"]["actor"] == "reaper"
    assert event["payload"]["prior_status"] == "running"


async def test_one_bad_tenant_does_not_stop_the_sweep(
    db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    other = uuid4()
    db["candidates"] = [_stale("running")]
    state = _state([_TENANT, other])
    calls: list[UUID] = []
    real_reap = reaper.reap_tenant

    async def flaky(state_: Any, tenant_id: UUID, **kwargs: Any) -> int:
        calls.append(tenant_id)
        if tenant_id == _TENANT:
            raise RuntimeError("connection reset")
        return await real_reap(state_, tenant_id, **kwargs)

    monkeypatch.setattr(reaper, "reap_tenant", flaky)

    assert await reaper.sweep_once(state) == 1
    assert calls == [_TENANT, other]


# ── Stranded speaker re-runs ──────────────────────────────────────────


def _stale_rerun(status: str) -> repository.StaleRediarizeRow:
    return repository.StaleRediarizeRow(
        id=uuid4(), diarization_status=status, requester_sub=uuid4()
    )


async def test_a_stranded_rerun_fails_as_stranded_and_leaves_the_job(db: dict[str, Any]) -> None:
    row = _stale_rerun("running")
    db["rediarize"] = [row]
    state = _state([_TENANT])

    assert await reaper.sweep_once(state) == 1
    assert db["rediarize_failed"] == [
        {"job_id": row.id, "error": "stranded", "only_if_status": "running"}
    ]
    assert db["failed"] == [], "the job itself is complete and stays so"
    # Conditional on still being past the grace window, not only on status.
    assert db["rediarize_grace"] > 0
    event = state.audit_writer.events[0]
    assert event["kind"] == "asr.rediarize_failed"
    assert event["payload"] == {"error_kind": "stranded", "actor": "reaper"}


async def test_a_rerun_that_finished_first_is_not_reaped(db: dict[str, Any]) -> None:
    db["rediarize"] = [_stale_rerun("queued")]
    db["fail_result"] = False
    state = _state([_TENANT])

    assert await reaper.sweep_once(state) == 0
    assert state.audit_writer.events == []
