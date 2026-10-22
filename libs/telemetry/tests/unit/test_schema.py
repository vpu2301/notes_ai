from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from telemetry.schema import (
    STAGE_KEYS,
    STAGES,
    ClientEvent,
    Device,
    LlmCall,
    ProcessingRun,
    RunContext,
    RunExport,
    SpanRecord,
)  # fmt: skip

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
IDS = {k: uuid4() for k in ("run", "tenant", "rec", "span")}


def _run(**kw: object) -> ProcessingRun:
    base: dict[str, object] = {
        "processing_run_id": IDS["run"], "tenant_id": IDS["tenant"], "recording_id": IDS["rec"],
        "kind": "initial", "trigger": "user", "status": "succeeded", "submitted_at": NOW,
        "retention_until": NOW + timedelta(days=90), "processing_wall_seconds": 12.5,
        "audio_duration_seconds": 100.0, "rtf": 0.125, "speedup": 8.0,
        "null_reasons": dict.fromkeys(("user_wait_seconds", "time_to_transcript_seconds", "time_to_speaker_labels_seconds", "time_to_notes_seconds", "asr_audio_processed_seconds", "concurrent_runs_at_start", "telemetry_overhead_seconds", "telemetry_buffer_peak_bytes"), "not_measured"),
    }  # fmt: skip
    base.update(kw)
    return ProcessingRun(**base)  # type: ignore[arg-type]


def _context() -> RunContext:
    return RunContext(
        processing_run_id=IDS["run"], tenant_id=IDS["tenant"], app_commit="abc", app_build="1",
        os_name="Darwin", os_version="25.4", arch="arm64", chip_model="Apple M5",
        memory_total_bytes=24 << 30, execution_mode="native", effective_config={"beam_size": 1},
        device_asr=Device(value="cpu", observation="observed"),
        device_diarization=Device(value="cpu", observation="configured"),
        process_rss_start=1, process_rss_end=2, swap_used_start=0, swap_used_end=0,
        memory_pressure_start="normal", memory_pressure_end="normal",
        null_reasons={"device_llm": "not_applicable", "container_mem_limit": "not_applicable"},
    )  # fmt: skip


def _span(stage: str = "vad", **attrs: object) -> SpanRecord:
    attributes = dict.fromkeys(STAGE_KEYS.get(stage, ()), 1) | attrs
    return SpanRecord(
        span_id=IDS["span"],
        processing_run_id=IDS["run"],
        tenant_id=IDS["tenant"],
        stage=stage,
        name=f"{stage}.x",
        status="ok",
        start_wall_utc=NOW,
        end_wall_utc=NOW,
        process_id=1,
        host="h",
        attributes=attributes,
    )  # type: ignore[arg-type]


def _llm() -> LlmCall:
    return LlmCall(
        llm_call_id=uuid4(), span_id=IDS["span"], processing_run_id=IDS["run"], tenant_id=IDS["tenant"],
        purpose="note_write", provider="openai_compat", model="mistral-large-2512", backend="mistral_eu",
        execution_mode="remote", status="ok", total_latency_seconds=3.2, input_tokens=1000,
        output_tokens=200, token_source="provider",
        null_reasons=dict.fromkeys(("queue_wait_seconds", "model_load_seconds", "time_to_first_token_seconds", "cached_input_tokens", "reasoning_tokens", "generation_tokens_per_second", "prompt_chars", "completion_chars"), "not_supported"),
    )  # fmt: skip


def _event() -> ClientEvent:
    return ClientEvent(
        event_id=uuid4(), recording_id=IDS["rec"], tenant_id=IDS["tenant"], client="web",
        client_version="1.0", event="notes_displayed", client_wall_utc=NOW,
        server_received_utc=NOW + timedelta(milliseconds=40), estimated_clock_offset_ms=40,
    )  # fmt: skip


@pytest.mark.parametrize("make", [_run, _context, _span, _llm, _event], ids=lambda f: f.__name__)
def test_every_entity_round_trips(make) -> None:  # type: ignore[no-untyped-def]
    obj = make()
    assert type(obj).model_validate_json(obj.model_dump_json()) == obj


def test_the_export_matches_the_json_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parents[4] / "telemetry-sprints/design/telemetry_v1.schema.json"
    if not schema_path.exists():
        pytest.skip("design schema not in this checkout")
    export = RunExport(processing_run=_run(), run_context=_context(), spans=[_span()],
                       llm_calls=[_llm()], client_events=[_event()])  # fmt: skip
    jsonschema.validate(json.loads(export.model_dump_json()), json.loads(schema_path.read_text()))


def test_a_zero_where_a_reason_is_given_fails() -> None:
    with pytest.raises(ValidationError, match="has a value and a reason"):
        _run(user_wait_seconds=0.0)


def test_null_without_a_reason_fails() -> None:
    with pytest.raises(ValidationError, match="null without a reason"):
        _run(rtf=None)


def test_an_unknown_reason_fails() -> None:
    with pytest.raises(ValidationError):
        _run(null_reasons={"rtf": "because"})


def test_a_span_missing_a_stage_key_fails_but_a_started_row_does_not() -> None:
    with pytest.raises(ValidationError, match="missing attribute keys"):
        SpanRecord(**(_span("asr_primary").model_dump() | {"attributes": {"backend": "x"}}))
    SpanRecord(**(_span("asr_primary").model_dump() | {"attributes": {}, "status": "started"}))


def test_a_null_stage_key_needs_its_reason() -> None:
    with pytest.raises(ValidationError, match="threshold is null"):
        _span("vad", threshold=None)
    _span("vad", threshold=None, _reasons={"threshold": "not_measured"})


def test_every_stage_has_an_error_category() -> None:
    from telemetry.schema import STAGE_ERROR_CATEGORY

    assert set(STAGES) == set(STAGE_ERROR_CATEGORY)
