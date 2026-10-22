from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

import telemetry
from telemetry import runs, store
from telemetry.schema import Device


async def test_a_run_starts_queued_with_pending_reasons(fake_store) -> None:  # type: ignore[no-untyped-def]
    ref = await telemetry.start_run(
        tenant_id=uuid4(), recording_id=uuid4(), audio_duration_seconds=100.0
    )
    assert ref is not None
    (run,) = fake_store.runs
    assert run.status == "queued"
    # The INSERT counts open runs itself (telemetry_open_runs()) and drops this reason.
    assert run.null_reasons["concurrent_runs_at_start"] == "unavailable"
    assert run.null_reasons["processing_wall_seconds"] == "not_measured"
    assert (run.retention_until - run.submitted_at).days == 90


async def test_finish_derives_wall_rtf_status_and_overhead(fake_store) -> None:  # type: ignore[no-untyped-def]
    ref = await telemetry.start_run(
        tenant_id=uuid4(), recording_id=uuid4(), audio_duration_seconds=100.0
    )
    assert ref is not None
    token = telemetry.set_run(ref)
    try:
        await telemetry.begin_run(ref, effective_config={"beam_size": 1, "api_key": "x"},
                                  device_asr=Device(value="cpu", observation="configured"))  # fmt: skip
        with telemetry.span("other", "worker_job"):
            pass
        status = await telemetry.finish_run(
            ref, result_stored=True, stage_statuses=[("other", "ok")]
        )
    finally:
        telemetry.reset_run(token)
    assert status == "succeeded"
    (ctx,) = fake_store.contexts
    assert "api_key" not in ctx.effective_config
    fields = fake_store.updates[-1]["fields"]
    assert fields["status"] == "succeeded" and fields["processing_wall_seconds"] is not None
    assert fields["rtf"] == pytest.approx(fields["processing_wall_seconds"] / 100.0)
    assert fields["telemetry_overhead_seconds"] >= 0


class _Boom:
    """A pool whose every use explodes."""

    def acquire(self) -> Any:
        raise ConnectionError("db down")


async def test_a_broken_store_never_reaches_the_pipeline() -> None:
    runs._settings = runs.Settings(enabled=True)
    store.configure(store.TelemetryStore(_Boom(), write_timeout_seconds=0.5))
    try:

        async def pipeline() -> str:
            ref = await telemetry.start_run(tenant_id=uuid4(), recording_id=uuid4())
            assert ref is not None
            token = telemetry.set_run(ref)
            try:
                await telemetry.begin_run(ref)
                with telemetry.span("asr_primary", "transcribe") as s:
                    s.set("backend", "inproc")
                await telemetry.finish_run(ref, result_stored=True)
            finally:
                telemetry.reset_run(token)
            return "transcript stored"

        assert await pipeline() == "transcript stored"
    finally:
        store.configure(None)


async def test_disabled_telemetry_keeps_only_the_run_row(fake_store) -> None:  # type: ignore[no-untyped-def]
    # TELEMETRY_ENABLED=false (sprint 5 overhead runs): the run row with its status and wall
    # time, nothing else, so an off run can be compared with an on run.
    runs._settings = runs.Settings(enabled=False)
    try:
        ref = await telemetry.start_run(
            tenant_id=uuid4(), recording_id=uuid4(), audio_duration_seconds=100.0
        )
        assert ref is not None and len(fake_store.runs) == 1
        await telemetry.begin_run(ref, effective_config={"beam_size": 1})
        assert fake_store.contexts == []  # no run context probe
        status = await telemetry.finish_run(ref, result_stored=True)
        fields = fake_store.updates[-1]["fields"]
        assert status == "succeeded" and fields["processing_wall_seconds"] is not None
    finally:
        runs._settings = runs.Settings(enabled=True)


def test_a_row_only_store_drops_spans_and_llm_calls() -> None:
    from datetime import UTC, datetime

    from telemetry.schema import SpanRecord

    s = store.TelemetryStore(pool=None, row_only=True)
    now = datetime.now(UTC)
    s.span(SpanRecord(span_id=uuid4(), processing_run_id=uuid4(), tenant_id=uuid4(),
                      stage="other", name="x", status="ok", start_wall_utc=now,
                      end_wall_utc=now, process_id=1, host="h"))  # fmt: skip
    assert len(s._queue) == 0


def test_propagation_through_a_serialised_queue_payload() -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    ref = telemetry.RunRef(processing_run_id=uuid4(), tenant_id=uuid4(), recording_id=uuid4())
    tracer = TracerProvider().get_tracer("t")
    with tracer.start_as_current_span("submit"):
        fields = telemetry.inject(ref)
        trace_id = format(trace.get_current_span().get_span_context().trace_id, "032x")
    wire = json.dumps({"job_id": str(ref.recording_id), **{k: str(v) for k, v in fields.items()}})
    back = json.loads(wire)
    got = telemetry.extract(
        back["processing_run_id"], tenant_id=ref.tenant_id, recording_id=ref.recording_id
    )
    assert got == ref
    assert back["traceparent"].split("-")[1] == trace_id
    assert telemetry.extract(None, tenant_id=ref.tenant_id, recording_id=ref.recording_id) is None
