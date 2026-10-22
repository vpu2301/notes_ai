"""Telemetry sprint 4: the deterministic Markdown report and its rules.

Snapshots live in ``snapshots/report-<case>.md`` next to this file. A missing snapshot is
written on the first run (review it, then commit); afterwards any byte difference fails.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from telemetry.report import INCOMPLETE, WALL_NOTE, hypotheses, missing_measurements, render_report
from telemetry.report import _prepare as prepare
from telemetry.report_rules import RULES
from telemetry.schema import (
    STAGE_KEYS,
    Device,
    LlmCall,
    ProcessingRun,
    RunContext,
    RunExport,
    SpanRecord,
)

SNAPSHOTS = Path(__file__).parent / "snapshots"
TENANT = UUID(int=0xA)
RECORDING = UUID(int=0x1000)
RUN = UUID(int=0x2000)
T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
_ids = iter(range(0x3000, 0x9000))


def _id() -> UUID:
    return UUID(int=next(_ids))


def span(
    stage: str, name: str, start: float, seconds: float, *, parent: SpanRecord | None = None,
    status: str = "ok", attempt: int = 1, parallel: list[SpanRecord] | None = None, **attrs: Any,
) -> SpanRecord:  # fmt: skip
    """A span; every schema key not given is None with reason ``not_measured``."""
    reasons = dict(attrs.pop("_reasons", {}))
    for key in STAGE_KEYS.get(stage, ()):
        if key not in attrs:
            attrs[key] = None
            reasons.setdefault(key, "not_measured")
    if reasons:
        attrs["_reasons"] = reasons
    begin = T0 + timedelta(seconds=start)
    return SpanRecord(
        span_id=_id(), processing_run_id=RUN, tenant_id=TENANT,
        parent_span_id=parent.span_id if parent else None, stage=stage, name=name,  # type: ignore[arg-type]
        attempt=attempt, status=status, start_monotonic_ns=int(start * 1e9),  # type: ignore[arg-type]
        end_monotonic_ns=int((start + seconds) * 1e9), start_wall_utc=begin,
        end_wall_utc=begin + timedelta(seconds=seconds), process_id=1, host="worker",
        attributes=attrs, is_parallel_with=[p.span_id for p in parallel] if parallel else None,
    )  # fmt: skip


def run(**kw: Any) -> ProcessingRun:
    fields: dict[str, Any] = {
        "processing_run_id": RUN, "tenant_id": TENANT, "recording_id": RECORDING,
        "kind": "initial", "trigger": "user", "status": "succeeded", "attempts": 1,
        "submitted_at": T0, "finished_at": T0 + timedelta(seconds=100),
        "processing_wall_seconds": 100.0, "rtf": 0.5, "speedup": 2.0,
        "audio_duration_seconds": 200.0, "asr_audio_processed_seconds": 180.0,
        "user_wait_seconds": 110.0, "time_to_transcript_seconds": 101.0,
        "time_to_speaker_labels_seconds": 101.5, "time_to_notes_seconds": 108.0,
        "concurrent_runs_at_start": 0, "telemetry_overhead_seconds": 0.04,
        "telemetry_buffer_peak_bytes": 2048, "retention_until": T0 + timedelta(days=90),
    }  # fmt: skip
    fields.update(kw)
    for name in ProcessingRun.MEASUREMENTS:
        if fields.get(name) is None:
            fields[name] = None
            fields.setdefault("null_reasons", {})
            fields["null_reasons"].setdefault(name, "not_measured")
    return ProcessingRun(**fields)


def context(**kw: Any) -> RunContext:
    fields: dict[str, Any] = {
        "processing_run_id": RUN, "tenant_id": TENANT, "app_commit": "abc1234",
        "app_build": "2026.10.22", "os_name": "Darwin", "os_version": "25.4.0", "arch": "arm64",
        "chip_model": "Apple M5", "memory_total_bytes": 24 * 1024**3, "execution_mode": "native",
        "device_asr": Device(value="metal", observation="observed"),
        "device_diarization": Device(value="cpu", observation="observed"),
        "device_llm": Device(value="remote", observation="configured"),
        "memory_pressure_start": "normal", "memory_pressure_end": "normal",
        "process_rss_start": 1_000_000_000, "process_rss_end": 1_500_000_000,
        "swap_used_start": 0, "swap_used_end": 0, "container_mem_limit": None,
        "null_reasons": {"container_mem_limit": "not_applicable"},
    }  # fmt: skip
    fields.update(kw)
    for name in RunContext.MEASUREMENTS:
        if fields.get(name) is None and name not in fields["null_reasons"]:
            fields["null_reasons"][name] = "unavailable"
    return RunContext(**fields)


def llm(parent: SpanRecord, purpose: str = "note_write", **kw: Any) -> LlmCall:
    fields: dict[str, Any] = {
        "llm_call_id": _id(), "span_id": parent.span_id, "processing_run_id": RUN,
        "tenant_id": TENANT, "purpose": purpose, "provider": "mistral_eu",
        "model": "mistral-large-2512", "backend": "mistral_eu", "execution_mode": "remote",
        "status": "ok", "queue_wait_seconds": 0.0, "total_latency_seconds": 4.0,
        "input_tokens": 12_000, "output_tokens": 900, "cached_input_tokens": 0,
        "reasoning_tokens": 0, "token_source": "provider", "prompt_chars": 48_000,
        "completion_chars": 3_600,
        "null_reasons": {"model_load_seconds": "not_applicable",
                         "time_to_first_token_seconds": "not_applicable",
                         "generation_tokens_per_second": "not_supported"},
    }  # fmt: skip
    fields.update(kw)
    return LlmCall(**fields)


def asr_pipeline(*, wall: float = 100.0, asr: float = 70.0) -> list[SpanRecord]:
    """A worker job: queue, prep, warm model, VAD, LID, two chunks, diarization, persist."""
    job = span("other", "worker_job", 0.5, wall - 1, job_status="complete")
    spans = [
        span("upload", "asr.submit.upload", 0, 0.4, bytes=1_000_000, chunks=1, retries=0,
             resumed=False),
        job,
        span("queue", "asr.queue_wait", 0.4, 0.1, parent=job, queue_name="asr:jobs",
             queue_wait_seconds=0.1),
        span("audio_prep", "asr.audio_prep", 0.6, 1.0, parent=job, retrieve_seconds=0.5,
             decode_seconds=0.5),
        span("model_init", "asr.model", 1.6, 0.0, parent=job, model_kind="asr",
             model_name="whisper-large-v3", model_revision="edaa852", quantization="int8",
             compute_type="int8", device={"value": "metal", "observation": "observed"},
             state="warm", load_seconds=0.0, backend="whisper_cpp"),
        span("vad", "vad.speech_runs", 1.6, 2.0, parent=job, backend="silero", speech_seconds=90.0,
             run_count=3, run_lengths_seconds=[20.0, 30.0, 40.0], threshold=0.5),
        span("language_detection", "lid.recording", 3.6, 4.0, parent=job, model="whisper-tiny",
             call_count=1, audio_seconds=90.0, decided_language="de",
             detected=[{"lang": "de", "confidence": 0.99}, {"lang": "en", "confidence": 0.01}]),
    ]  # fmt: skip
    primary = span("asr_primary", "asr.transcribe_runs", 7.6, asr, parent=job,
                   backend="whisper_cpp", audio_processed_seconds=90.0, wall_seconds=asr,
                   chunk_count=2)  # fmt: skip
    spans += [
        primary,
        span("asr_primary", "asr.chunk", 7.6, asr / 2, parent=primary, backend="whisper_cpp",
             audio_processed_seconds=45.0, wall_seconds=asr / 2),
        span("asr_primary", "asr.chunk", 7.6 + asr / 2, asr / 2, parent=primary,
             backend="whisper_cpp", audio_processed_seconds=45.0, wall_seconds=asr / 2),
    ]  # fmt: skip
    end = 7.6 + asr
    spans += [
        span("diarization_load", "diarization.load", end, 2.0, parent=job, backend="pyannote",
             model="pyannote-3.1", device={"value": "cpu", "observation": "observed"},
             state="warm", load_seconds=2.0,
             _reasons={"speakers_detected": "not_applicable",
                       "unknown_speaker_share": "not_applicable"}),
        span("diarization_infer", "diarization.infer", end + 2, 8.0, parent=job,
             backend="pyannote", model="pyannote-3.1",
             device={"value": "cpu", "observation": "observed"}, infer_seconds=8.0,
             speakers_detected=3, unknown_speaker_share=0.05, audio_seconds=100.0),
        span("persist", "asr.persist", end + 10, 0.2, parent=job, duration_seconds=0.2, items=40),
    ]  # fmt: skip
    return spans


def export(spans: list[SpanRecord], *, calls: list[LlmCall] | None = None,
           ctx: RunContext | None | bool = True, **run_kw: Any) -> RunExport:  # fmt: skip
    return RunExport(
        processing_run=run(**run_kw), run_context=context() if ctx is True else ctx or None,
        spans=spans, llm_calls=calls or [],
    )  # fmt: skip


def _with_notes(spans: list[SpanRecord], *, status: str = "ok") -> tuple[list[SpanRecord], list[LlmCall]]:  # fmt: skip
    notes = span("other", "notes.generate", 90.0, 6.0, status=status)
    write = span("llm_call", "llm.note_write", 90.5, 4.0, parent=notes, status=status)
    return spans + [notes, write], [llm(write, status=status)]


def _case_succeeded() -> RunExport:
    spans, calls = _with_notes(asr_pipeline())
    return export(spans, calls=calls)


def _case_partial() -> RunExport:
    spans, calls = _with_notes(asr_pipeline(), status="error")
    calls = [c.model_copy(update={"error_category": "llm", "output_tokens": None,
                                  "null_reasons": c.null_reasons | {"output_tokens": "error"}})
             for c in calls]  # fmt: skip
    return export(spans, calls=calls, status="partial", error_category="llm",
                  time_to_notes_seconds=None, user_wait_seconds=101.0)  # fmt: skip


def _case_failed() -> RunExport:
    job = span("other", "worker_job", 0.5, 20.0, status="error")
    spans = [
        job,
        span("asr_primary", "asr.transcribe_runs", 2.0, 18.0, parent=job, status="error",
             backend="whisper_cpp"),
    ]  # fmt: skip
    spans[1] = spans[1].model_copy(update={"error_category": "asr", "error_class": "RuntimeError"})
    return export(spans, status="failed", error_category="asr", processing_wall_seconds=20.5,
                  rtf=0.205, speedup=4.878, asr_audio_processed_seconds=None,
                  user_wait_seconds=None, time_to_transcript_seconds=None,
                  time_to_speaker_labels_seconds=None, time_to_notes_seconds=None)  # fmt: skip


def _case_cancelled() -> RunExport:
    job = span("other", "worker_job", 0.5, 30.0, status="cancelled")
    spans = [job, span("asr_primary", "asr.transcribe_runs", 2.0, 28.5, parent=job,
                       status="cancelled", backend="whisper_cpp")]  # fmt: skip
    return export(spans, status="cancelled", processing_wall_seconds=31.0, rtf=0.31,
                  speedup=3.226, asr_audio_processed_seconds=None, user_wait_seconds=None,
                  time_to_transcript_seconds=None, time_to_speaker_labels_seconds=None,
                  time_to_notes_seconds=None)  # fmt: skip


def _case_parallel() -> RunExport:
    spans = asr_pipeline()
    primary = next(s for s in spans if s.name == "asr.transcribe_runs")
    shadow = span("other", "asr.shadow", primary.start_monotonic_ns / 1e9, 30.0,  # type: ignore[operator]
                  parallel=[primary])  # fmt: skip
    infer = span("diarization_infer", "diarization.infer.parallel", 10.0, 50.0,
                 parallel=[primary], backend="pyannote", model="pyannote-3.1",
                 device={"value": "cpu", "observation": "observed"}, infer_seconds=50.0,
                 speakers_detected=2, unknown_speaker_share=0.4, audio_seconds=100.0)  # fmt: skip
    return export(spans + [shadow, infer])


def _case_retries() -> RunExport:
    spans = asr_pipeline()
    first = span("other", "notes.generate", 90.0, 2.0, status="error", attempt=1)
    second = span("other", "notes.generate", 93.0, 5.0, attempt=2)
    w1 = span("llm_call", "llm.note_write", 90.2, 1.5, parent=first, status="error", attempt=1)
    w2 = span("llm_call", "llm.note_write", 93.2, 4.5, parent=second, attempt=2)
    calls = [
        llm(w1, status="error", attempt=1, error_category="llm", output_tokens=None,
            total_latency_seconds=1.5,
            null_reasons={"model_load_seconds": "not_applicable",
                          "time_to_first_token_seconds": "not_applicable",
                          "generation_tokens_per_second": "not_supported",
                          "output_tokens": "error"}),
        llm(w2, attempt=2, token_source="estimated",
            token_accounting_note="estimated from characters (4 chars/token)"),
    ]  # fmt: skip
    return export(spans + [first, second, w1, w2], calls=calls, attempts=2)


def _case_heavy_nulls() -> RunExport:
    spans = [span("asr_primary", "asr.transcribe_runs", 1.0, 50.0)]
    return export(spans, ctx=None, processing_wall_seconds=None, rtf=None, speedup=None,
                  audio_duration_seconds=None, asr_audio_processed_seconds=None,
                  user_wait_seconds=None, time_to_transcript_seconds=None,
                  time_to_speaker_labels_seconds=None, time_to_notes_seconds=None,
                  concurrent_runs_at_start=None, telemetry_overhead_seconds=None,
                  telemetry_buffer_peak_bytes=None,
                  null_reasons={"processing_wall_seconds": "unavailable"})  # fmt: skip


CASES = {
    "succeeded": _case_succeeded, "partial": _case_partial, "failed": _case_failed,
    "cancelled": _case_cancelled, "parallel": _case_parallel, "retries": _case_retries,
    "heavy_nulls": _case_heavy_nulls,
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(CASES))
def test_snapshot(case: str) -> None:
    text = render_report(CASES[case]())
    path = SNAPSHOTS / f"report-{case}.md"
    if not path.exists():
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


HEADINGS = [
    "## 1. Run identity", "### Hardware & environment", "### Effective models & backends",
    "## 2. End-to-end timing", "## 3. Stage table", "## 4. ASR breakdown", "## 5. Diarization",
    "## 6. LLM usage", "## 7. Memory & resources, missing measurements",
    "### Missing measurements", "## 8. Bottleneck summary", "### Measured", "### Hypotheses",
]  # fmt: skip


@pytest.mark.parametrize("case", sorted(CASES))
def test_sections_in_order(case: str) -> None:
    text = render_report(CASES[case]())
    positions = [text.index(h + "\n") for h in HEADINGS]
    assert positions == sorted(positions)
    assert WALL_NOTE in text


@pytest.mark.parametrize("case", sorted(CASES))
def test_byte_identical_whatever_the_input_order(case: str) -> None:
    record = CASES[case]()
    first = render_report(record)
    assert render_report(record) == first
    shuffled = record.model_copy(deep=True)
    rng = random.Random(7)
    rng.shuffle(shuffled.spans)
    rng.shuffle(shuffled.llm_calls)
    assert render_report(shuffled) == first


def test_heavy_nulls_say_incomplete_and_list_every_reason() -> None:
    record = _case_heavy_nulls()
    text = render_report(record)
    assert "## 7. Memory & resources, missing measurements\n\n" + INCOMPLETE in text
    missing = missing_measurements(record)
    assert {"group": "context", "item": "context", "field": "run_context",
            "reason": "unavailable"} in missing  # fmt: skip
    assert missing == sorted(missing, key=lambda m: (m["group"], m["item"], m["field"],
                                                     m["reason"]))  # fmt: skip
    for m in missing:
        assert f"`{m['field']}` ({m['reason']})" in text


def test_redelivered_pickups_are_off_the_critical_path() -> None:
    spans = asr_pipeline()
    ghost = span("other", "worker_job", 99.5, 0.0, status="skipped", job_status="complete",
                 redelivered_after_finish=True)  # fmt: skip
    late = span("queue", "asr.queue_wait", 0.4, 99.0, parent=ghost, queue_wait_seconds=99.0,
                queue_name="asr:jobs")  # fmt: skip
    text = render_report(export(spans + [ghost, late]))
    assert "- Queue wait: 0.10 s." in text
    assert "Spans under a redelivered pickup" in text


# ── rules: each fires on its input and is "not assessable" without it ──


def _lines(record: RunExport) -> list[str]:
    return hypotheses(prepare(record))[0]


def _fired(record: RunExport, rule_id: str) -> bool:
    rule = next(r for r in RULES if r.id == rule_id)
    head = rule.text.split("{")[0]
    return any(line.startswith("Hypothesis: " + head) for line in _lines(record))


def _not_assessable(record: RunExport, rule_id: str) -> str | None:
    return next((line for line in _lines(record) if line.endswith(f"rule `{rule_id}`.")), None)


FIRING: dict[str, Any] = {
    "asr_device_configured": lambda: export(
        asr_pipeline(), ctx=context(device_asr=Device(value="cuda", observation="configured"))),
    "diarization_device_configured": lambda: export(
        asr_pipeline(),
        ctx=context(device_diarization=Device(value="cpu", observation="configured"))),
    "asr_dominates": lambda: export(asr_pipeline(asr=80.0), rtf=0.9),
    "reprocessing": lambda: export(asr_pipeline(), asr_audio_processed_seconds=300.0),
    "cold_model_init": lambda: export(asr_pipeline() + [
        span("model_init", "lid.model", 1.6, 15.0, model_kind="lid", state="cold",
             load_seconds=15.0)]),
    "unknown_speakers": lambda: _case_parallel(),
    "swap_growth": lambda: export(asr_pipeline(),
                                  ctx=context(swap_used_end=2 * 1024**3, swap_used_start=0)),
}  # fmt: skip

MISSING: dict[str, Any] = {
    "asr_device_configured": lambda: export(asr_pipeline(), ctx=None),
    "diarization_device_configured": lambda: export(asr_pipeline(), ctx=None),
    "asr_dominates": lambda: export(asr_pipeline(), rtf=None),
    "reprocessing": lambda: export(asr_pipeline(), asr_audio_processed_seconds=None),
    "cold_model_init": lambda: export(asr_pipeline(), processing_wall_seconds=None,
                                      null_reasons={"processing_wall_seconds": "unavailable"}),
    "unknown_speakers": lambda: export([s for s in asr_pipeline()
                                        if not s.stage.startswith("diarization")]),
    "swap_growth": lambda: export(asr_pipeline(), ctx=context(swap_used_end=None)),
}  # fmt: skip


def test_every_rule_has_both_cases() -> None:
    assert set(FIRING) == set(MISSING) == {r.id for r in RULES}


@pytest.mark.parametrize("rule_id", sorted(FIRING))
def test_rule_fires(rule_id: str) -> None:
    assert _fired(FIRING[rule_id](), rule_id)
    assert not _fired(_case_succeeded(), rule_id)  # the healthy run fires nothing


@pytest.mark.parametrize("rule_id", sorted(MISSING))
def test_rule_not_assessable(rule_id: str) -> None:
    line = _not_assessable(MISSING[rule_id](), rule_id)
    assert line is not None and line.startswith("Not assessable: ")
    assert " unavailable (" in line


# ── dashboard aggregates ──


def test_overview_counts_percentiles_shares_and_backends() -> None:
    from telemetry.overview import aggregate, percentile

    records = [_case_succeeded(), _case_failed(), _case_cancelled(), _case_heavy_nulls()]
    agg = aggregate(records)
    assert agg["runs"] == 4
    assert agg["status_counts"]["succeeded"] == 2  # heavy-nulls is a succeeded run too
    assert agg["status_counts"]["failed"] == 1 and agg["status_counts"]["cancelled"] == 1
    assert agg["rtf"] == {"p50": 0.31, "p95": 0.5, "n": 3}  # null rtf is left out, not zero
    assert agg["runs_with_wall"] == 3
    assert 0 < agg["stage_share"]["asr_primary"] <= 1
    asr = [b for b in agg["backends"] if b["kind"] == "asr"]
    assert asr[0]["name"] == "whisper_cpp" and asr[0]["observation"] == "observed"
    assert percentile([], 0.5) is None and percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0


def test_a_hand_crafted_older_record_is_read_and_rendered() -> None:
    # Acceptance (sprint 5): a record written before later additions (no attempts, no
    # user_wait_cross_device, no client events) and tagged with an older schema version.
    old = {
        "telemetry_schema_version": 0,
        "processing_run": {
            "processing_run_id": str(RUN), "tenant_id": str(TENANT), "recording_id": str(RECORDING),
            "kind": "initial", "trigger": "user", "status": "succeeded",
            "telemetry_schema_version": 0, "submitted_at": T0.isoformat(),
            "processing_wall_seconds": 50.0, "rtf": 0.5, "speedup": 2.0,
            "audio_duration_seconds": 100.0, "asr_audio_processed_seconds": 100.0,
            "concurrent_runs_at_start": 0, "telemetry_overhead_seconds": 0.01,
            "telemetry_buffer_peak_bytes": 10, "retention_until": (T0 + timedelta(days=90)).isoformat(),
            "null_reasons": {"user_wait_seconds": "not_measured",
                             "time_to_transcript_seconds": "not_measured",
                             "time_to_speaker_labels_seconds": "not_measured",
                             "time_to_notes_seconds": "not_measured"},
        },
        "spans": [],
    }  # fmt: skip
    record = RunExport.model_validate(old)
    assert (
        record.processing_run.attempts == 0 and record.processing_run.telemetry_schema_version == 0
    )
    text = render_report(record)
    assert "| telemetry schema version | 0 |" in text
