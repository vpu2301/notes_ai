from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest

from telemetry import runs, store
from telemetry.context import RunRef, reset_run, set_run
from telemetry.schema import ProcessingRun, RunContext, SpanRecord


class FakeStore(store.NullStore):
    """Records what would be written."""

    def __init__(self) -> None:
        super().__init__()
        self.spans: list[SpanRecord] = []
        self.runs: list[ProcessingRun] = []
        self.contexts: list[RunContext] = []
        self.updates: list[dict[str, Any]] = []

    def span(self, record: SpanRecord) -> None:
        self.spans.append(record)

    async def insert_run(self, run: ProcessingRun) -> None:
        self.runs.append(run)

    async def open_runs(self, tenant_id: UUID) -> int | None:
        return 2

    async def insert_context(self, ctx: RunContext) -> None:
        self.contexts.append(ctx)

    async def begin(
        self, tenant_id: UUID, run_id: UUID, activity: Any, ctx: RunContext | None
    ) -> None:
        if ctx is not None:
            self.contexts.append(ctx)

    async def run_facts(self, tenant_id: UUID, run_id: UUID) -> Any:
        ends = [s.end_wall_utc for s in self.spans if s.end_wall_utc and s.status != "started"]
        return (self.runs[0].submitted_at if self.runs else None), 100.0, ends

    async def update_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        fields: dict[str, Any],
        reasons: dict[str, str],
        cleared: list[str],
    ) -> None:
        self.updates.append({"fields": fields, "reasons": reasons, "cleared": cleared})


@pytest.fixture
def fake_store() -> Iterator[FakeStore]:
    fake = FakeStore()
    runs._settings = runs.Settings(enabled=True)
    store.configure(fake)
    yield fake
    store.configure(None)


@pytest.fixture
def run_ref() -> Iterator[RunRef]:
    ref = RunRef(processing_run_id=uuid4(), tenant_id=uuid4(), recording_id=uuid4())
    token = set_run(ref)
    yield ref
    reset_run(token)
