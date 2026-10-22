"""Telemetry sprint 3, part B: client-event ingest (ACL, run resolution, idempotency, clock
offset) and the user-visible timings derived from the events (with and without clock skew)."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from telemetry import store as t_store
from telemetry.client_timings import Event, derive
from telemetry.schema import ClientEvent

TENANT = uuid4()
ME = uuid4()
RECORDING = uuid4()
OTHER_RECORDING = uuid4()
RUN = uuid4()
T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _claims(roles: list[str] | None = None) -> Claims:
    return Claims(
        sub=ME, tid=TENANT, roles=roles or ["member"], sid="test-session",
        iss="https://test/issuer", aud="mdx", exp=9_999_999_999, iat=1_700_000_000,
    )  # fmt: skip


class _Store(t_store.NullStore):
    def __init__(self) -> None:
        super().__init__()
        self.events: dict[tuple[UUID | None, str, str], ClientEvent] = {}
        self.timings_for: list[UUID] = []

    async def run_recording(self, tenant_id: UUID, run_id: UUID) -> UUID | None:
        return RECORDING if run_id == RUN else None

    async def resolve_run(self, tenant_id: UUID, recording_id: UUID, event: str) -> UUID | None:
        return RUN if recording_id == RECORDING else None

    async def add_client_event(self, event: ClientEvent) -> bool:
        key = (event.processing_run_id, event.client, event.event)
        if key in self.events:
            return False
        self.events[key] = event
        return True

    async def apply_client_timings(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
        self.timings_for.append(run_id)
        return {}


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import telemetry_events as mod

    requesters = {RECORDING: ME, OTHER_RECORDING: uuid4()}

    class _Conn:
        async def fetchval(self, sql: str, *args: Any) -> Any:
            assert "transcription_jobs" in sql
            return requesters.get(args[0])

    @contextlib.asynccontextmanager
    async def tenant_connection(_pool: Any, _tid: Any) -> Any:
        yield _Conn()

    monkeypatch.setattr(mod, "tenant_connection", tenant_connection)
    deps.install_state(SimpleNamespace(app_pool=object()))  # type: ignore[arg-type]
    fake = _Store()
    t_store.configure(fake)
    app = create_app()
    claims = {"value": _claims()}
    app.dependency_overrides[deps.current_user] = lambda: claims["value"]
    yield SimpleNamespace(client=TestClient(app), store=fake, claims=claims)
    t_store.configure(None)


def _event(event: str, at: datetime, **kw: Any) -> dict[str, Any]:
    return {"recording_id": str(RECORDING), "client": "web", "client_version": "2026.10",
            "event": event, "client_wall_utc": at.isoformat()} | kw  # fmt: skip


def test_events_are_stored_with_a_receive_time_and_an_offset(rig: Any) -> None:
    sent = datetime.now(UTC) - timedelta(seconds=2)  # the client's clock is 2 s behind
    resp = rig.client.post("/v1/telemetry/client-events", json={
        "sent_at": sent.isoformat(),
        "events": [_event("recording_stopped", sent - timedelta(minutes=3)),
                   _event("upload_finished", sent - timedelta(minutes=2))],
    })  # fmt: skip
    assert resp.status_code == 202 and resp.json() == {
        "accepted": 2,
        "duplicates": 0,
        "unresolved": 0,
    }
    stopped = rig.store.events[(RUN, "web", "recording_stopped")]
    assert stopped.processing_run_id == RUN  # resolved from the recording
    assert (
        1_900 <= stopped.estimated_clock_offset_ms <= 3_000
    )  # against sent_at, not the event's age
    assert rig.store.timings_for == [RUN]


def test_a_duplicate_is_ignored_first_report_wins(rig: Any) -> None:
    body = [_event("notes_displayed", T0)]
    rig.client.post("/v1/telemetry/client-events", json=body)
    resp = rig.client.post(
        "/v1/telemetry/client-events", json=[_event("notes_displayed", T0 + timedelta(seconds=9))]
    )
    assert resp.json()["duplicates"] == 1
    assert rig.store.events[(RUN, "web", "notes_displayed")].client_wall_utc == T0


def test_someone_elses_recording_is_refused(rig: Any) -> None:
    resp = rig.client.post(
        "/v1/telemetry/client-events",
        json=[_event("notes_displayed", T0) | {"recording_id": str(OTHER_RECORDING)}],
    )
    assert resp.status_code == 404 and rig.store.events == {}


def test_a_workspace_admin_may_report_for_any_recording(rig: Any) -> None:
    rig.claims["value"] = _claims(["tenant_admin", "member"])
    resp = rig.client.post(
        "/v1/telemetry/client-events",
        json=[_event("notes_displayed", T0) | {"recording_id": str(OTHER_RECORDING)}],
    )
    assert resp.status_code == 202 and resp.json()["unresolved"] == 1  # no run for that recording


def test_a_run_of_another_recording_is_not_trusted(rig: Any) -> None:
    rig.client.post(
        "/v1/telemetry/client-events",
        json=[_event("transcript_displayed", T0, processing_run_id=str(uuid4()))],
    )
    assert (RUN, "web", "transcript_displayed") in rig.store.events


def test_attributes_are_redacted_and_unknown_fields_refused(rig: Any) -> None:
    rig.client.post(
        "/v1/telemetry/client-events",
        json=[
            _event(
                "error_shown",
                T0,
                attributes={"error_category": "asr", "transcript": "secret words"},
            )
        ],
    )
    assert rig.store.events[(RUN, "web", "error_shown")].attributes == {"error_category": "asr"}
    assert (
        rig.client.post(
            "/v1/telemetry/client-events", json=[_event("notes_displayed", T0, text="x")]
        ).status_code
        == 422
    )


# ── derived timings (pure) ──


def _e(event: str, client: str, seconds: float, offset_ms: int = 0) -> Event:
    return Event(event, client, T0 + timedelta(seconds=seconds), offset_ms)


def test_time_to_and_user_wait_on_one_device() -> None:
    submitted = T0 + timedelta(seconds=5)
    fields, reasons = derive(
        [_e("recording_stopped", "macos", 0), _e("transcript_displayed", "macos", 95),
         _e("speaker_labels_displayed", "macos", 96), _e("notes_displayed", "macos", 140)],
        submitted,
    )  # fmt: skip
    assert fields["time_to_transcript_seconds"] == 90.0 and fields["time_to_notes_seconds"] == 135.0
    assert fields["user_wait_seconds"] == 140.0 and fields["user_wait_cross_device"] is False
    assert reasons == {}


def test_a_skewed_client_clock_is_corrected_for_time_to_but_cancels_for_user_wait() -> None:
    # The Mac runs 30 s fast: its wall times read 30 s late; the offset (−30 s) corrects them.
    submitted = T0 + timedelta(seconds=5)
    fields, _ = derive(
        [
            _e("recording_stopped", "macos", 30, -30_000),
            _e("notes_displayed", "macos", 170, -30_000),
        ],
        submitted,
    )
    assert fields["time_to_notes_seconds"] == 135.0
    assert fields["user_wait_seconds"] == 140.0  # one device: its own clock, offset cancels


def test_two_devices_use_corrected_clocks_and_say_so() -> None:
    fields, _ = derive(
        [_e("recording_stopped", "ios", 0, 2_000), _e("notes_displayed", "web", 150, -1_000)],
        T0,
    )
    assert fields["user_wait_seconds"] == 147.0 and fields["user_wait_cross_device"] is True


def test_impossible_clocks_are_null_with_a_reason_never_zero() -> None:
    fields, reasons = derive([_e("transcript_displayed", "web", 1)], T0 + timedelta(minutes=5))
    assert (
        fields["time_to_transcript_seconds"] is None
        and reasons["time_to_transcript_seconds"] == "error"
    )


def test_without_notes_the_last_displayed_result_ends_the_wait() -> None:
    fields, _ = derive(
        [_e("import_submitted", "web", 0), _e("transcript_displayed", "web", 80)], T0
    )
    assert fields["user_wait_seconds"] == 80.0
