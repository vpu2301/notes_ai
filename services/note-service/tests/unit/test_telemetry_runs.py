"""Telemetry sprint 4: the read API — who sees which run, pagination, redaction on the way
out, 404s and the report download."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from telemetry import queries as real_queries
from telemetry.schema import ProcessingRun, RunExport, SpanRecord

TENANT_A, TENANT_B, ADMIN_HOME = uuid4(), uuid4(), uuid4()
ME, COLLEAGUE, STRANGER = uuid4(), uuid4(), uuid4()
MINE, THEIRS, ELSEWHERE = uuid4(), uuid4(), uuid4()  # recordings
T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _claims(sub: UUID, roles: list[str], tid: UUID = TENANT_A) -> Claims:
    return Claims(
        sub=sub, tid=tid, roles=roles, sid="s", iss="https://test/issuer", aud="mdx",
        exp=9_999_999_999, iat=1_700_000_000,
    )  # fmt: skip


def _record(tenant: UUID, recording: UUID, minutes: int, created_by: UUID | None) -> RunExport:
    run_id = uuid4()
    run = ProcessingRun(
        processing_run_id=run_id, tenant_id=tenant, recording_id=recording, kind="initial",
        trigger="user", status="succeeded", submitted_at=T0 + timedelta(minutes=minutes),
        processing_wall_seconds=10.0, rtf=0.5, speedup=2.0, audio_duration_seconds=20.0,
        asr_audio_processed_seconds=20.0, created_by=created_by, concurrent_runs_at_start=0,
        telemetry_overhead_seconds=0.01, telemetry_buffer_peak_bytes=10,
        retention_until=T0 + timedelta(days=90),
        null_reasons=dict.fromkeys(("user_wait_seconds", "time_to_transcript_seconds", "time_to_speaker_labels_seconds", "time_to_notes_seconds"), "not_measured"),
    )  # fmt: skip
    span = SpanRecord(
        span_id=uuid4(), processing_run_id=run_id, tenant_id=tenant, stage="other",
        name="worker_job", status="ok", start_wall_utc=run.submitted_at,
        end_wall_utc=run.submitted_at + timedelta(seconds=10), process_id=1, host="w",
        # A content key that must never leave the API, even if it reached the table.
        attributes={"job_status": "complete", "transcript_text": "the secret words"},
    )  # fmt: skip
    return RunExport(processing_run=run, spans=[span])


RECORDS = [
    _record(TENANT_A, MINE, 0, ME),
    _record(TENANT_A, MINE, 5, None),  # a regeneration: its run has no created_by
    _record(TENANT_A, THEIRS, 1, COLLEAGUE),
    _record(TENANT_B, ELSEWHERE, 2, STRANGER),
]
REQUESTERS = {MINE: ME, THEIRS: COLLEAGUE, ELSEWHERE: STRANGER}
TENANT_OF = {MINE: TENANT_A, THEIRS: TENANT_A, ELSEWHERE: TENANT_B}


def _summary(r: RunExport) -> dict[str, Any]:
    run = r.processing_run
    return {
        "processing_run_id": run.processing_run_id, "tenant_id": run.tenant_id,
        "recording_id": run.recording_id, "kind": run.kind, "status": run.status,
        "submitted_at": run.submitted_at, "created_by": run.created_by, "asr_backend": None,
        "llm_model": None,
    }  # fmt: skip


class _Conn:
    def __init__(self, tenant: UUID) -> None:
        self.tenant = tenant

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "transcription_jobs" in sql:
            rec = args[0]
            return REQUESTERS.get(rec) if TENANT_OF.get(rec) == self.tenant else None
        if "FROM notes" in sql:
            return None  # no note: access comes from requester / admin only here
        raise AssertionError(sql)


class _Queries:
    """Stands in for telemetry.queries; every read honours the connection's tenant (RLS)."""

    decode_cursor = staticmethod(real_queries.decode_cursor)
    encode_cursor = staticmethod(real_queries.encode_cursor)

    @staticmethod
    async def run_tenant(conn: _Conn, run_id: UUID) -> UUID | None:
        return next((r.processing_run.tenant_id for r in RECORDS
                     if r.processing_run.processing_run_id == run_id), None)  # fmt: skip

    @staticmethod
    async def recording_tenant(conn: _Conn, recording_id: UUID) -> UUID | None:
        return TENANT_OF.get(recording_id)

    @staticmethod
    async def tenants_between(conn: _Conn, start: datetime, end: datetime) -> list[UUID]:
        return sorted({r.processing_run.tenant_id for r in RECORDS})

    @staticmethod
    async def fetch_export(conn: _Conn, run_id: UUID) -> RunExport | None:
        return next((r for r in RECORDS if r.processing_run.processing_run_id == run_id
                     and r.processing_run.tenant_id == conn.tenant), None)  # fmt: skip

    @staticmethod
    async def list_runs(conn: _Conn, *, limit: int, recording_id: UUID | None = None,
                        status: str | None = None, requester: UUID | None = None,
                        submitted_from: Any = None, submitted_to: Any = None,
                        before: tuple[datetime, UUID] | None = None) -> list[dict[str, Any]]:  # fmt: skip
        rows = [_summary(r) for r in RECORDS if r.processing_run.tenant_id == conn.tenant]
        rows = [x for x in rows if recording_id is None or x["recording_id"] == recording_id]
        rows = [x for x in rows if requester is None or REQUESTERS[x["recording_id"]] == requester]
        rows.sort(key=lambda x: (x["submitted_at"], x["processing_run_id"]), reverse=True)
        if before is not None:
            rows = [x for x in rows if (x["submitted_at"], x["processing_run_id"]) < before]
        return rows[:limit]


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import telemetry_runs as mod

    @contextlib.asynccontextmanager
    async def tenant_connection(_pool: Any, tid: Any) -> Any:
        yield _Conn(tid)

    monkeypatch.setattr(mod, "tenant_connection", tenant_connection)
    monkeypatch.setattr(mod, "queries", _Queries)
    deps.install_state(SimpleNamespace(app_pool=object()))  # type: ignore[arg-type]
    app = create_app()
    who = {"claims": _claims(ME, ["member"])}
    app.dependency_overrides[deps.current_user] = lambda: who["claims"]

    def as_(claims: Claims) -> TestClient:
        who["claims"] = claims
        return client

    client = TestClient(app)
    yield as_


def _run_id(i: int) -> str:
    return str(RECORDS[i].processing_run.processing_run_id)


def test_the_requester_sees_their_runs_and_nobody_elses(rig: Any) -> None:
    me = rig(_claims(ME, ["member"]))
    listed = me.get("/v1/telemetry/runs").json()["runs"]
    assert [r["recording_id"] for r in listed] == [str(MINE), str(MINE)]
    assert me.get(f"/v1/telemetry/runs/{_run_id(0)}").status_code == 200
    assert me.get(f"/v1/telemetry/runs/{_run_id(2)}").status_code == 404  # a colleague's
    assert me.get(f"/v1/telemetry/runs/{_run_id(3)}").status_code == 404  # another tenant
    assert me.get("/v1/telemetry/runs", params={"recording_id": str(THEIRS)}).status_code == 404


def test_a_workspace_admin_sees_the_workspace_only(rig: Any) -> None:
    admin = rig(_claims(ME, ["tenant_admin", "member"]))
    listed = admin.get("/v1/telemetry/runs").json()["runs"]
    assert {r["recording_id"] for r in listed} == {str(MINE), str(THEIRS)}
    assert admin.get(f"/v1/telemetry/runs/{_run_id(2)}").status_code == 200
    assert admin.get(f"/v1/telemetry/runs/{_run_id(3)}").status_code == 404
    assert admin.get("/v1/admin/telemetry/overview").status_code == 403


def test_the_platform_admin_sees_every_tenant(rig: Any) -> None:
    root = rig(_claims(uuid4(), ["platform_admin"], tid=ADMIN_HOME))
    listed = root.get("/v1/telemetry/runs").json()["runs"]
    assert len(listed) == 4
    assert root.get(f"/v1/telemetry/runs/{_run_id(3)}").status_code == 200
    runs = root.get(f"/v1/telemetry/recordings/{ELSEWHERE}/runs").json()["runs"]
    assert [r["recording_id"] for r in runs] == [str(ELSEWHERE)]
    body = root.get("/v1/admin/telemetry/overview",
                    params={"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"}).json()  # fmt: skip
    assert body["runs"] == 4 and body["status_counts"]["succeeded"] == 4
    assert body["rtf"]["p50"] == 0.5 and body["capped"] is False


def test_a_role_without_telemetry_read_is_refused(rig: Any) -> None:
    assert rig(_claims(ME, ["auditor"])).get("/v1/telemetry/runs").status_code == 403
    assert rig(_claims(ME, ["guest"])).get(f"/v1/telemetry/runs/{_run_id(0)}").status_code == 403


def test_pagination_walks_every_run_once(rig: Any) -> None:
    root = rig(_claims(uuid4(), ["platform_admin"], tid=ADMIN_HOME))
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params: dict[str, Any] = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        page = root.get("/v1/telemetry/runs", params=params).json()
        seen += [r["processing_run_id"] for r in page["runs"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(_run_id(i) for i in range(4)) and len(seen) == 4
    assert root.get("/v1/telemetry/runs", params={"cursor": "nope"}).status_code == 422


def test_unknown_run_is_404(rig: Any) -> None:
    root = rig(_claims(uuid4(), ["platform_admin"], tid=ADMIN_HOME))
    assert root.get(f"/v1/telemetry/runs/{uuid4()}").status_code == 404
    assert root.get(f"/v1/telemetry/runs/{uuid4()}/report.md").status_code == 404


def test_content_keys_are_redacted_at_the_boundary(rig: Any) -> None:
    me = rig(_claims(ME, ["member"]))
    body = me.get(f"/v1/telemetry/runs/{_run_id(0)}").json()
    attrs = body["spans"][0]["attributes"]
    assert attrs == {"job_status": "complete"}
    assert "the secret words" not in me.get(f"/v1/telemetry/runs/{_run_id(0)}/report.md").text
    assert any(m["field"] == "user_wait_seconds" for m in body["missing_measurements"])


def test_report_download_headers(rig: Any) -> None:
    me = rig(_claims(ME, ["member"]))
    resp = me.get(f"/v1/telemetry/runs/{_run_id(0)}/report.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers["content-disposition"] == (
        f'attachment; filename="diagnostics-{MINE}-{_run_id(0)}.md"'
    )
    assert resp.text.startswith(f"# Diagnostics — recording {MINE}")
