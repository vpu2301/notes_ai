"""Sprint F1 T1/T4: capture timing on submit, and coverage + capture on
the result view."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from asr_models import (
    Coverage,
    CoverageGap,
    Diagnostics,
    JobEnqueuePayload,
    JobStatus,
)

from .test_result_endpoint import _job_view, _output
from .test_result_endpoint import rig as result_rig  # noqa: F401 — fixture
from .test_submit_rejections import rig  # noqa: F401 — fixture

_AUDIO = {"audio": ("a.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")}


def _capture_inserts(rig: SimpleNamespace) -> list[dict[str, Any]]:  # noqa: F811
    inserted: list[dict[str, Any]] = []

    async def _insert(*_args: Any, **kwargs: Any) -> None:
        inserted.append(kwargs)

    rig.monkeypatch.setattr(rig.jobs.repository, "insert_job_row", _insert)
    return inserted


def _queued_payload(rig: SimpleNamespace) -> JobEnqueuePayload:  # noqa: F811
    sent: list[bytes] = []

    async def _send(**kwargs: Any) -> None:
        sent.append(kwargs["value"])

    rig.producer.send = _send
    return sent  # type: ignore[return-value]


def test_capture_timing_is_stored_queued_and_echoed(rig: SimpleNamespace) -> None:  # noqa: F811
    inserted = _capture_inserts(rig)
    sent = _queued_payload(rig)
    resp = rig.client.post(
        "/asr/jobs",
        files=_AUDIO,
        data={
            "language": "en",
            "record_pressed_at": "2026-09-25T16:29:03.250+02:00",
            "first_frame_offset_ms": "3120",
        },
    )
    assert resp.status_code == 202, resp.text
    (row,) = inserted
    assert row["record_pressed_at"] == datetime.fromisoformat("2026-09-25T16:29:03.250+02:00")
    assert row["first_frame_offset_ms"] == 3120
    payload = JobEnqueuePayload.model_validate_json(sent[0])  # type: ignore[index]
    assert payload.first_frame_offset_ms == 3120
    body = resp.json()
    assert body["first_frame_offset_ms"] == 3120
    assert body["record_pressed_at"].startswith("2026-09-25T16:29:03.25")


def test_older_clients_send_no_timing(rig: SimpleNamespace) -> None:  # noqa: F811
    inserted = _capture_inserts(rig)
    resp = rig.client.post("/asr/jobs", files=_AUDIO, data={"language": "en"})
    assert resp.status_code == 202
    assert inserted[0]["record_pressed_at"] is None
    assert inserted[0]["first_frame_offset_ms"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"first_frame_offset_ms": "-1"},
        {"first_frame_offset_ms": "600001"},
        {"first_frame_offset_ms": "3.5"},
        {"record_pressed_at": "yesterday"},
        # A wall clock without an offset cannot be placed in time.
        {"record_pressed_at": "2026-09-25T16:29:03"},
    ],
)
def test_out_of_range_timing_is_a_400_validation_error(
    rig: SimpleNamespace,  # noqa: F811
    fields: dict[str, str],
) -> None:
    resp = rig.client.post("/asr/jobs", files=_AUDIO, data={"language": "en", **fields})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "validation_error"
    assert rig.producer.sent == 0


def test_the_job_view_reads_timing_and_coverage_share_off_the_row() -> None:
    from asr_service.domain.repository import _row_to_view

    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "audio_id": uuid4(),
        "requester_sub": uuid4(),
        "language": "en",
        "model": "large-v3",
        "status": "complete",
        "error_kind": None,
        "error_detail": None,
        "queued_at": "2026-09-25T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "attempts": 1,
    }
    view = _row_to_view(
        {  # type: ignore[arg-type]
            **base,
            "record_pressed_at": datetime(2026, 9, 25, 16, 29, tzinfo=UTC),
            "first_frame_offset_ms": 800,
            "metadata": json.dumps({"model": "large-v3", "coverage_share": 0.9731}),
        }
    )
    assert view.first_frame_offset_ms == 800 and view.coverage_share == 0.9731
    # A row from before migration 0063 and before F1's metadata.
    old = _row_to_view({**base, "metadata": json.dumps({"model": "large-v3"})})  # type: ignore[arg-type]
    assert old.record_pressed_at is None and old.coverage_share is None


def test_the_result_carries_coverage_and_capture(
    result_rig: SimpleNamespace,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from asr_service.routers import jobs

    view = _job_view(JobStatus.COMPLETE).model_copy(
        update={
            "record_pressed_at": datetime(2026, 9, 25, 16, 29, tzinfo=UTC),
            "first_frame_offset_ms": 4200,
        }
    )

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    output = _output()
    output = output.model_copy(
        update={
            "diagnostics": Diagnostics(
                coverage=Coverage(
                    speech_ms=40_000,
                    transcribed_ms=36_000,
                    first_speech_ms=0,
                    first_segment_ms=0,
                    gaps=[
                        CoverageGap(start_ms=0, end_ms=4_200, cause="no_audio"),
                        CoverageGap(start_ms=10_000, end_ms=14_000, cause="decoder_empty"),
                    ],
                )
            )
        }
    )
    result_rig.store.body = output.model_dump_json().encode()

    body = result_rig.client.get(f"/asr/jobs/{uuid4()}/result").json()

    assert body["coverage"]["share"] == 0.9
    assert [g["cause"] for g in body["coverage"]["gaps"]] == ["no_audio", "decoder_empty"]
    assert body["capture"] == {
        "record_pressed_at": "2026-09-25T16:29:00Z",
        "first_frame_offset_ms": 4200,
    }
