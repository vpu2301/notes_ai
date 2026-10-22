from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest

from telemetry import span
from telemetry.timing import critical_path_seconds, derive_status, ratios, sum_seconds


def test_nested_and_parallel_spans_form_a_tree(fake_store, run_ref) -> None:  # type: ignore[no-untyped-def]
    with span("other", "worker_job") as root:
        with span("vad", "vad.speech_runs") as vad:
            vad.update(backend="silero", duration_seconds=0.1, speech_seconds=50.0, run_count=3,
                       run_lengths_seconds=[10.0, 20.0, 20.0], threshold=0.5)  # fmt: skip
        with span("diarization_infer", "diar") as a, span("asr_recovery", "second_pass") as b:
            a.parallel_with.append(b.span_id)
    finished = [s for s in fake_store.spans if s.status != "started"]
    by_name = {s.name: s for s in finished}
    assert by_name["vad.speech_runs"].parent_span_id == root.span_id
    assert by_name["second_pass"].parent_span_id == a.span_id  # opened inside a's block
    assert by_name["diar"].is_parallel_with == [b.span_id]
    assert by_name["worker_job"].parent_span_id is None
    # Long stages wrote a `started` row first.
    assert {s.name for s in fake_store.spans if s.status == "started"} >= {"worker_job", "diar"}


def test_unset_stage_keys_are_null_with_a_reason_not_zero(fake_store, run_ref) -> None:  # type: ignore[no-untyped-def]
    with span("vad", "vad.speech_runs") as s:
        s.set("backend", "silero")
        s.missing("threshold", "not_supported")
    rec = fake_store.spans[-1]
    assert rec.attributes["run_count"] is None
    assert rec.attributes["_reasons"]["run_count"] == "not_measured"
    assert rec.attributes["_reasons"]["threshold"] == "not_supported"


def test_an_exception_marks_the_span_and_is_reraised_unchanged(fake_store, run_ref) -> None:  # type: ignore[no-untyped-def]
    err = ValueError("boom")
    with pytest.raises(ValueError) as caught, span("asr_primary", "transcribe"):
        raise err
    assert caught.value is err
    rec = fake_store.spans[-1]
    assert (rec.status, rec.error_category, rec.error_class) == ("error", "asr", "ValueError")
    assert "boom" not in rec.model_dump_json()


async def test_cancellation_marks_the_span_cancelled(fake_store, run_ref) -> None:  # type: ignore[no-untyped-def]
    async def work() -> None:
        async with span("llm_call", "write"):
            await asyncio.sleep(10)

    task = asyncio.create_task(work())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake_store.spans[-1].status == "cancelled"


async def test_spans_in_to_thread_attach_to_the_run(fake_store, run_ref) -> None:  # type: ignore[no-untyped-def]
    def blocking() -> None:
        with span("other", "in_thread"):
            pass

    async with span("other", "outer") as outer:
        await asyncio.to_thread(blocking)
    inner = next(s for s in fake_store.spans if s.name == "in_thread" and s.status != "started")
    assert inner.processing_run_id == run_ref.processing_run_id
    assert inner.parent_span_id == outer.span_id


def test_outside_a_run_nothing_is_written(fake_store) -> None:  # type: ignore[no-untyped-def]
    with span("vad", "vad") as s:
        time.sleep(0.001)
    assert fake_store.spans == [] and s.duration_seconds and s.duration_seconds > 0


def test_wall_time_is_the_critical_path_not_the_sum(fake_store, run_ref) -> None:  # type: ignore[no-untyped-def]
    with span("other", "root"):
        with span("asr_primary", "a"):
            time.sleep(0.02)
        with span("asr_recovery", "b"):
            time.sleep(0.02)
    finished = [s for s in fake_store.spans if s.status != "started"]
    submitted = min(s.start_wall_utc for s in finished)
    wall = critical_path_seconds(submitted, [s.end_wall_utc for s in finished])
    total = sum_seconds((s.end_monotonic_ns - s.start_monotonic_ns) / 1e9 for s in finished)
    assert wall is not None and total > wall * 1.5  # root overlaps its children
    assert wall == pytest.approx(0.04, abs=0.03)


def test_retries_are_attempts_and_do_not_add_wall_time() -> None:
    from datetime import UTC, datetime

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    ends = [t0 + timedelta(seconds=30), t0 + timedelta(seconds=50)]  # attempt 1 failed at 30 s
    assert critical_path_seconds(t0, ends) == 50.0
    assert critical_path_seconds(None, ends) is None
    assert critical_path_seconds(t0, []) is None


@pytest.mark.parametrize(
    ("statuses", "stored", "cancelled", "expected"),
    [
        ([("asr_primary", "ok")], True, False, "succeeded"),
        ([("asr_primary", "ok"), ("diarization_infer", "error")], True, False, "partial"),
        ([("asr_primary", "ok"), ("other", "error")], True, False, "succeeded"),
        ([("asr_primary", "error")], False, False, "failed"),
        ([("asr_primary", "cancelled")], False, False, "cancelled"),
        ([], True, True, "cancelled"),
    ],
)
def test_run_status(statuses, stored, cancelled, expected) -> None:  # type: ignore[no-untyped-def]
    assert derive_status(statuses, result_stored=stored, cancelled=cancelled) == expected


def test_rtf_and_speedup() -> None:
    assert ratios(50.0, 100.0) == (0.5, 2.0)
    assert ratios(None, 100.0) == (None, None)
    assert ratios(10.0, 0.0) == (None, None)
