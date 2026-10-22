"""Telemetry sprint 2: what the server records at submission (capture_input, upload) and the
queue depth it reads before enqueueing — counts and facts only, fail-open."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import telemetry
from asr_service.routers import jobs
from telemetry import runs as t_runs
from telemetry import store as t_store


class _Recorder(t_store.NullStore):
    def __init__(self) -> None:
        super().__init__()
        self.spans: list[Any] = []

    def span(self, record: Any) -> None:
        self.spans.append(record)


@pytest.fixture
def recorder() -> Any:
    rec = _Recorder()
    t_runs._settings = t_runs.Settings(enabled=True)
    t_store.configure(rec)
    yield rec
    t_store.configure(None)


def _facts(**kw: Any) -> Any:
    base = {"mime_type": "audio/flac", "size_bytes": 960_000, "duration_ms": 60_000,
                "sample_rate_hz": 16_000, "channels": 2, "codec": "flac", "sha256": "x"}  # fmt: skip
    return SimpleNamespace(**(base | kw))


def test_capture_and_upload_spans_carry_the_server_facts(recorder: Any) -> None:
    run = telemetry.RunRef(processing_run_id=uuid4(), tenant_id=uuid4(), recording_id=uuid4())
    t0 = datetime.now(UTC)
    jobs._record_submission_spans(
        run,
        facts=_facts(),
        capture_context={
            "source": "calendar_event",
            "channel_layout": "mic_system",
            "client": "macos",
        },
        received_at=t0,
        probe=(t0 + timedelta(milliseconds=200), t0 + timedelta(milliseconds=260)),
        stored_at=t0 + timedelta(milliseconds=400),
    )
    capture, upload = recorder.spans
    assert (
        capture.stage == "capture_input"
        and capture.attributes["capture_mode"] == "calendar_event:mic_system"
    )
    assert (
        capture.attributes["audio_duration_seconds"] == 60.0 and capture.attributes["channels"] == 2
    )
    assert upload.stage == "upload" and upload.attributes == {
        "bytes": 960_000,
        "chunks": 1,
        "retries": 0,
        "resumed": False,
    }
    assert (upload.end_wall_utc - upload.start_wall_utc).total_seconds() == pytest.approx(
        0.4, abs=0.01
    )


def test_unknown_facts_are_null_with_a_reason(recorder: Any) -> None:
    run = telemetry.RunRef(processing_run_id=uuid4(), tenant_id=uuid4(), recording_id=uuid4())
    t0 = datetime.now(UTC)
    jobs._record_submission_spans(run, facts=_facts(duration_ms=None, sample_rate_hz=None),
                                  capture_context={}, received_at=None, probe=(t0, t0), stored_at=t0)  # fmt: skip
    capture = recorder.spans[0]
    assert capture.attributes["audio_duration_seconds"] is None
    assert capture.attributes["_reasons"]["sample_rate_hz"] == "unavailable"


class _Redis:
    def __init__(self, groups: Any) -> None:
        self._groups = groups

    async def xinfo_groups(self, stream: str) -> Any:
        if isinstance(self._groups, Exception):
            raise self._groups
        return self._groups


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ([{"name": b"asr-workers", "lag": 4}], 4),
        ([{"name": "other", "lag": 9}], None),
        ([{"name": "asr-workers", "lag": None}], None),  # Redis < 7
        (ConnectionError("down"), None),
    ],
)
async def test_queue_depth_is_the_group_lag_or_none(groups: Any, expected: int | None) -> None:
    assert await jobs._queue_depth(SimpleNamespace(redis=_Redis(groups))) == expected
