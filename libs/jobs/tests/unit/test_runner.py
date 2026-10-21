"""Runner semantics against an in-memory queue: warming parks without an
attempt, auth never retries, usage flushes with the completion."""

from __future__ import annotations

import asyncio
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


async def test_on_dead_fires_when_the_job_will_not_run_again() -> None:
    """A probe that never passes must not leave the handler's own state
    'queued' behind a dead job: the last attempt (and a non-retryable
    error) settle it through `on_dead`; a retry does not."""
    told: list[tuple[str, str]] = []

    async def probe(ctx: JobContext) -> None:
        raise ProviderError(ErrorKind.UNAVAILABLE, "connection refused", backend="dev_mac")

    async def handler(ctx: JobContext) -> None:
        raise AssertionError("never reached")

    async def on_dead(ctx: JobContext, error_kind: str) -> None:
        told.append((str(ctx.job.id), error_kind))

    class _Queue(FakeQueue):
        async def fail(
            self, job: Job, *, error_kind: str, message: str, retryable: bool, conn: Any = None
        ) -> JobStatus:  # type: ignore[override]
            self.calls.append(("fail", (error_kind, retryable)))
            if not retryable:
                return JobStatus.FAILED
            return JobStatus.QUEUED if job.attempts < job.max_attempts else JobStatus.DEAD

    q = _Queue([])
    r = JobRunner(
        q, {"understand": HandlerSpec(run=handler, probe=probe, on_dead=on_dead)}, worker_id="w1"
    )  # type: ignore[arg-type]

    assert await r.run_one(_job(attempts=1)) is JobStatus.QUEUED
    assert told == []
    last = _job(attempts=5)
    assert await r.run_one(last) is JobStatus.DEAD
    assert told == [(str(last.id), "unavailable")]


async def test_on_dead_fires_for_non_retryable_and_unhandled_and_never_raises() -> None:
    told: list[str] = []

    async def auth(ctx: JobContext) -> None:
        raise ProviderError(ErrorKind.AUTH, "revoked", backend="hf_eu")

    async def boom(ctx: JobContext) -> None:
        raise ValueError("bug")

    async def on_dead(ctx: JobContext, error_kind: str) -> None:
        told.append(error_kind)
        raise RuntimeError("the hook itself is broken")

    class _Queue(FakeQueue):
        async def fail(
            self, job: Job, *, error_kind: str, message: str, retryable: bool, conn: Any = None
        ) -> JobStatus:  # type: ignore[override]
            self.calls.append(("fail", (error_kind, retryable)))
            return JobStatus.DEAD if retryable else JobStatus.FAILED

    q = _Queue([])
    r = JobRunner(
        q,
        {"a": HandlerSpec(run=auth, on_dead=on_dead), "b": HandlerSpec(run=boom, on_dead=on_dead)},
        worker_id="w1",
    )  # type: ignore[arg-type]
    assert await r.run_one(_job("a")) is JobStatus.FAILED
    assert await r.run_one(_job("b")) is JobStatus.DEAD
    assert told == ["auth", "unhandled"]


async def test_the_runner_installs_its_ledger_as_the_usage_sink() -> None:
    """Task 4: the worker never called ``install()``; every provider record went to the
    log sink and the ledger table stayed empty. The runner installs it itself now."""
    from models import UsageRecord, emit, set_usage_sink

    ledger = UsageLedger(CostTable.empty())
    try:
        JobRunner(
            FakeQueue([]), {"understand": HandlerSpec(run=None)}, worker_id="w1", ledger=ledger
        )  # type: ignore[arg-type]
        ledger.begin()
        emit(
            UsageRecord(
                backend="b", model_id="m", operation="chat.complete", ok=False,
                latency_ms=1, error_kind="rate_limited", attempts=2,
            )
        )  # fmt: skip
        [rec] = ledger.drain()
    finally:
        set_usage_sink(None)
    assert rec.error_kind == "rate_limited" and rec.attempts == 2


async def test_the_poll_loop_reaps_expired_leases_before_claiming() -> None:
    """Task 5 step 0 (Q3): an expired lease is reaped (the job re-queued) once per poll."""

    class ReapingQueue(FakeQueue):
        def __init__(self, jobs: list[Job]) -> None:
            super().__init__(jobs)
            self.reaped = 0
            # Leased by a dead worker: not claimable until reaped.
            self.stale, self.pending = list(jobs), []

        async def reap_stale_leases(self, *, grace_seconds: float = 30.0) -> int:
            self.reaped += 1
            requeued, self.stale = self.stale, []
            self.pending.extend(requeued)
            return len(requeued)

    ran: list[str] = []

    async def handler(ctx: JobContext) -> dict[str, Any]:
        ran.append(str(ctx.job.id))
        return {"ok": True}

    job = _job()
    q = ReapingQueue([job])
    runner = JobRunner(
        q, {"understand": HandlerSpec(run=handler)}, worker_id="w1", poll_interval_s=0.01
    )  # type: ignore[arg-type]

    async def stop_soon() -> None:
        for _ in range(50):
            await asyncio.sleep(0.01)
            if ran:
                break
        runner.stop()

    await asyncio.gather(runner.run_forever(), stop_soon())
    assert q.reaped >= 1 and ran == [str(job.id)]
