"""``POST /asr/jobs`` rejections the router owns: every one names a code, none 500s.

``run_all`` is stubbed (ffprobe's verdict is tested in ``test_validators.py``).
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from asr_models import JobErrorKind
from asr_service.validators.result import UploadFacts, ok
from auth import Claims

_TENANT = uuid4()


def _member_claims() -> Claims:
    return Claims(
        sub=uuid4(),
        tid=_TENANT,
        roles=["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _facts() -> UploadFacts:
    return UploadFacts(
        mime_type="audio/wav",
        size_bytes=1024,
        duration_ms=5_000,
        sample_rate_hz=16_000,
        channels=1,
        codec="pcm_s16le",
        sha256=b"\x00" * 32,
    )


class _FakeStore:
    bucket = "mdx-audio"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def put(self, **_kwargs: Any) -> object:
        return object()

    async def delete(self, *, key: str) -> None:
        self.deleted.append(key)


class _FakeProducer:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.sent = 0

    async def send(self, **_kwargs: Any) -> None:
        if self.fails:
            raise ConnectionError("redis is down")
        self.sent += 1


class _FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from asr_service import deps
    from asr_service.main import create_app
    from asr_service.routers import jobs

    store = _FakeStore()
    producer = _FakeProducer()
    audit = _FakeAuditWriter()
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audio_store=store,
            audit_writer=audit,
            queue_producer=producer,
        )
    )

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(jobs, "tenant_connection", _fake_tenant_conn)
    # Grant everything: the role→permission matrix is not under test here.
    monkeypatch.setattr(deps, "check", lambda *a, **k: None)
    monkeypatch.setattr(deps, "check_any", lambda *a, **k: None)

    async def _run_all(*, mime_type: str, payload: bytes):  # noqa: ANN202
        return ok(), _facts()

    monkeypatch.setattr(jobs, "run_all", _run_all)
    monkeypatch.setattr(jobs, "_header_to_json", lambda _h: {})

    # Defaults: everything the handler asks the DB is fine.
    async def _count_active(_conn: Any, *, tenant_id: Any) -> int:
        return 0

    async def _validate_quota(_conn: Any, **_kwargs: Any):  # noqa: ANN202
        return ok()

    async def _insert(*_args: Any, **_kwargs: Any) -> None:
        return None

    failed: list[dict[str, Any]] = []

    async def _fail_job(
        _conn: Any, *, job_id: Any, error_kind: str, error_detail: str, **_: Any
    ) -> bool:
        failed.append({"job_id": job_id, "kind": error_kind, "detail": error_detail})
        return True

    monkeypatch.setattr(jobs.repository, "count_active_jobs", _count_active)
    monkeypatch.setattr(jobs.repository, "insert_audio_row", _insert)
    monkeypatch.setattr(jobs.repository, "insert_job_row", _insert)
    monkeypatch.setattr(jobs.repository, "fail_job", _fail_job)
    monkeypatch.setattr(jobs, "validate_quota", _validate_quota)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    return SimpleNamespace(
        client=TestClient(app),
        store=store,
        producer=producer,
        audit=audit,
        failed=failed,
        jobs=jobs,
        monkeypatch=monkeypatch,
    )


def _post(rig: SimpleNamespace) -> Any:
    return rig.client.post(
        "/asr/jobs",
        files={"audio": ("dictation.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")},
        data={"language": "uk", "vocabulary_hint": "Notes AI roadmap"},
    )


def test_accepted_upload_is_queued(rig: SimpleNamespace) -> None:
    resp = _post(rig)
    assert resp.status_code == 202
    assert rig.producer.sent == 1


def test_concurrency_limit_names_a_code_and_keeps_its_type_uri(
    rig: SimpleNamespace,
) -> None:
    async def _many(_conn: Any, *, tenant_id: Any) -> int:
        return 999

    rig.monkeypatch.setattr(rig.jobs.repository, "count_active_jobs", _many)

    resp = _post(rig)
    assert resp.status_code == 429
    body = resp.json()
    assert body["code"] == "concurrency_exceeded"
    assert body["type"] == "urn:mdx:asr:rate_limit:per_tenant_concurrent"


def test_enqueue_failure_fails_the_job_instead_of_reporting_202(
    rig: SimpleNamespace,
) -> None:
    rig.producer.fails = True

    resp = _post(rig)

    # 503, not 202: nothing is going to transcribe this recording.
    assert resp.status_code == 503
    assert resp.json()["code"] == str(JobErrorKind.ENQUEUE_FAILED)
    # And the row says so.
    assert len(rig.failed) == 1
    assert rig.failed[0]["kind"] == str(JobErrorKind.ENQUEUE_FAILED)


def test_auto_language_is_an_accepted_submit(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        "/asr/jobs",
        files={"audio": ("meeting.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")},
        data={"language": "auto"},
    )
    assert resp.status_code == 202
    assert resp.json()["language"] == "auto"
    assert resp.json()["detected_language"] is None


def test_unknown_language_pin_is_rejected(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        "/asr/jobs",
        files={"audio": ("meeting.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")},
        data={"language": "pl"},
    )
    assert resp.status_code == 422


# ── What the transcriber was told is stored with the job ──────────────


def test_the_hint_is_stored_on_the_job_and_counted_in_the_audit(rig: SimpleNamespace) -> None:
    inserted: list[dict[str, Any]] = []

    async def _insert(*_args: Any, **kwargs: Any) -> None:
        inserted.append(kwargs)

    rig.monkeypatch.setattr(rig.jobs.repository, "insert_job_row", _insert)
    resp = rig.client.post(
        "/asr/jobs",
        files={"audio": ("a.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")},
        data={"language": "en", "vocabulary_hint": "Gregor Gysi, Springbrook Marine, Pardo"},
    )
    assert resp.status_code == 202, resp.text
    (row,) = inserted
    assert row["vocabulary_hint"] == "Gregor Gysi, Springbrook Marine, Pardo"
    assert resp.json()["vocabulary_hint"] == "Gregor Gysi, Springbrook Marine, Pardo"
    queued = next(e for e in rig.audit.events if e["kind"] == "asr.job_queued")
    assert queued["payload"]["hint_terms"] == 3
    assert "Gysi" not in repr(queued)


def test_no_hint_is_stored_as_null_and_counts_zero(rig: SimpleNamespace) -> None:
    inserted: list[dict[str, Any]] = []

    async def _insert(*_args: Any, **kwargs: Any) -> None:
        inserted.append(kwargs)

    rig.monkeypatch.setattr(rig.jobs.repository, "insert_job_row", _insert)
    resp = rig.client.post(
        "/asr/jobs",
        files={"audio": ("a.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")},
        data={"language": "en", "vocabulary_hint": ""},
    )
    assert resp.status_code == 202
    assert inserted[0]["vocabulary_hint"] is None
    assert resp.json()["vocabulary_hint"] is None
    queued = next(e for e in rig.audit.events if e["kind"] == "asr.job_queued")
    assert queued["payload"]["hint_terms"] == 0


def test_a_job_row_without_the_column_reads_as_no_hint() -> None:
    """A database ahead of or behind migration 0061 still serves the job."""
    from asr_service.domain.repository import _row_to_view

    class _Row(dict):
        pass

    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "audio_id": uuid4(),
        "requester_sub": uuid4(),
        "language": "en",
        "model": "large-v3",
        "status": "queued",
        "error_kind": None,
        "error_detail": None,
        "queued_at": "2026-09-25T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "attempts": 0,
    }
    assert _row_to_view(_Row(base)).vocabulary_hint is None
    assert _row_to_view(_Row({**base, "vocabulary_hint": "Pardo"})).vocabulary_hint == "Pardo"
