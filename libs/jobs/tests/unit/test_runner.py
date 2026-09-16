"""Runner semantics against an in-memory queue: warming parks without an
attempt, auth never retries, usage flushes with the completion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from jobs import CostTable, HandlerSpec, Job, JobContext, JobRunner, JobStatus, UsageLedger
from jobs import runner as runner_mod
from models import ErrorKind, ProviderError, TranscriptionCancelledError, UsageRecord, emit


class FakeQueue:
    """Records the transitions the runner asks for; no SQL."""

    def __init__(self, jobs: list[Job]) -> None:
        self._pool = object()
        self.pending = list(jobs)
        self.calls: list[tuple[str, Any]] = []
        self.flushed: list[UsageRecord] = []

    async def claim(
        self, kinds: list[str], *, worker: str, lease_seconds: int, limit: int
    ) -> list[Job]:
        out, self.pending = self.pending[:limit], self.pending[limit:]
        return [j for j in out if j.kind in kinds]

    async def heartbeat(self, job: Job, *, lease_seconds: int) -> bool:
        return True

    async def complete(self, job: Job, result: Any = None, *, conn: Any = None) -> None:
        self.calls.append(("complete", result))

    async def fail(
        self, job: Job, *, error_kind: str, message: str, retryable: bool, conn: Any = None
    ) -> JobStatus:
        self.calls.append(("fail", (error_kind, retryable)))
        return JobStatus.QUEUED if retryable else JobStatus.FAILED

    async def wait_on_model(
        self, job: Job, *, backend: str, cold_start_seconds: int, retry_after_s: float | None = None
    ) -> JobStatus:
        self.calls.append(("wait_on_model", (backend, cold_start_seconds, retry_after_s)))
        return JobStatus.WAITING_ON_MODEL

    async def cancel(self, job: Job, *, reason: str = "") -> None:
        self.calls.append(("cancel", reason))


class _FakeConn:
    def __init__(self, sink: list[Any]) -> None:
        self._sink = sink

    async def executemany(self, sql: str, rows: list[Any]) -> None:
        self._sink.extend(rows)


def _job(kind: str = "understand", attempts: int = 1) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=uuid4(),
        tenant_id=uuid4(),
        kind=kind,
        payload={"note_id": "n1"},
        status=JobStatus.RUNNING,
        attempts=attempts,
        max_attempts=5,
        run_at=now,
        created_at=now,
        leased_by="w1",
    )


@pytest.fixture
def fake_tenant_connection(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    rows: list[Any] = []

    class _Ctx:
        def __init__(self, pool: Any, tenant_id: UUID) -> None:
            self.tenant_id = tenant_id

        async def __aenter__(self) -> _FakeConn:
            return _FakeConn(rows)

        async def __aexit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr(runner_mod, "tenant_connection", _Ctx)
    return rows


async def test_success_flushes_usage_in_completion_transaction(
    fake_tenant_connection: list[Any],
) -> None:
    async def handler(ctx: JobContext) -> dict[str, Any]:
        emit(
            UsageRecord(
                backend="hf_eu",
                model_id="m",
                operation="chat.complete",
                ok=True,
                latency_ms=100,
                input_tokens=10,
                output_tokens=5,
            )
        )
        return {"ok": True}

    job = _job()
    q = FakeQueue([job])
    ledger = UsageLedger(CostTable.empty())
    ledger.install()
    try:
        runner = JobRunner(
            q, {"understand": HandlerSpec(run=handler)}, worker_id="w1", ledger=ledger
        )  # type: ignore[arg-type]
        assert await runner.run_once() == 1
    finally:
        from models import set_usage_sink

        set_usage_sink(None)
    assert q.calls == [("complete", {"ok": True})]
    assert len(fake_tenant_connection) == 1 and fake_tenant_connection[0][0] == job.tenant_id


async def test_warming_from_probe_parks_without_running_handler() -> None:
    ran = False

    async def probe(ctx: JobContext) -> None:
        raise ProviderError(
            ErrorKind.WARMING, "HTTP 503 scaling", backend="hf_eu", retry_after_s=20
        )

    async def handler(ctx: JobContext) -> None:
        nonlocal ran
        ran = True

    q = FakeQueue([_job()])
    spec = HandlerSpec(run=handler, probe=probe, backend=lambda ctx: ("hf_eu", 300))
    status = await JobRunner(q, {"understand": spec}, worker_id="w1").run_one(q.pending.pop())  # type: ignore[arg-type]
    assert status is JobStatus.WAITING_ON_MODEL and ran is False
    assert q.calls == [("wait_on_model", ("hf_eu", 300, 20))]


async def test_warming_from_handler_parks_too() -> None:
    async def handler(ctx: JobContext) -> None:
        raise ProviderError(ErrorKind.WARMING, "scaling", backend="hf_eu_asr")

    q = FakeQueue([])
    spec = HandlerSpec(run=handler, backend=lambda ctx: ("hf_eu_asr", 240))
    status = await JobRunner(q, {"asr": spec}, worker_id="w1").run_one(_job("asr"))  # type: ignore[arg-type]
    assert status is JobStatus.WAITING_ON_MODEL
    assert q.calls == [("wait_on_model", ("hf_eu_asr", 240, None))]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (ErrorKind.AUTH, ("auth", False)),
        (ErrorKind.UNAVAILABLE, ("unavailable", True)),
        (ErrorKind.RATE_LIMITED, ("rate_limited", True)),
        (ErrorKind.TIMEOUT, ("timeout", True)),
        (ErrorKind.CONTEXT_EXCEEDED, ("context_exceeded", False)),
        (ErrorKind.SCHEMA_INVALID, ("schema_invalid", False)),
    ],
)
async def test_provider_error_classification(kind: ErrorKind, expected: tuple[str, bool]) -> None:
    async def handler(ctx: JobContext) -> None:
        raise ProviderError(kind, "x", backend="hf_eu")

    q = FakeQueue([])
    await JobRunner(q, {"understand": HandlerSpec(run=handler)}, worker_id="w1").run_one(_job())  # type: ignore[arg-type]
    assert q.calls == [("fail", expected)]


async def test_cancel_and_unhandled() -> None:
    async def cancelled(ctx: JobContext) -> None:
        raise TranscriptionCancelledError("user")

    async def boom(ctx: JobContext) -> None:
        raise ValueError("bug")

    q = FakeQueue([])
    r = JobRunner(q, {"a": HandlerSpec(run=cancelled), "b": HandlerSpec(run=boom)}, worker_id="w1")  # type: ignore[arg-type]
    assert await r.run_one(_job("a")) is JobStatus.CANCELLED
    assert await r.run_one(_job("b")) is JobStatus.QUEUED
    assert q.calls == [("cancel", "cancel requested"), ("fail", ("unhandled", True))]
