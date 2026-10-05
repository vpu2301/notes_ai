# ruff: noqa: F811 — the imported `rig` fixture is injected by name.
"""Re-labelling routes: speaker-count hints on submit, re-run, undo.

In-memory repository scoped by tenant (``conn`` is the tenant id).
"""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from asr_service.domain.repository import RediarizeClaim, UndoOutcome
from auth import Claims

from .test_submit_rejections import rig  # noqa: F401 — the submit rig, reused

_TENANT_A = uuid4()
_TENANT_B = uuid4()


# ── Submit: hints ─────────────────────────────────────────────────────


def _submit(rig: SimpleNamespace, **data: str) -> Any:
    sent: list[dict[str, Any]] = []

    async def send(*, value: bytes, **_kw: Any) -> None:
        sent.append(json.loads(value))

    rig.producer.send = send
    resp = rig.client.post(
        "/asr/jobs",
        files={"audio": ("m.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")},
        data={"language": "en", **data},
    )
    return resp, sent


def test_an_exact_count_rides_the_queue_payload(rig: SimpleNamespace) -> None:
    resp, sent = _submit(rig, diarize="true", speakers_expected="2")

    assert resp.status_code == 202
    assert resp.json()["hints_applied"] is True
    assert (sent[0]["num_speakers"], sent[0]["max_speakers"], sent[0]["task"]) == (
        2,
        None,
        "transcribe",
    )
    queued = next(e for e in rig.audit.events if e["kind"] == "asr.job_queued")
    assert queued["payload"]["speakers_hint"] == "exact"


def test_hints_without_diarization_are_ignored_and_say_so(rig: SimpleNamespace) -> None:
    resp, sent = _submit(rig, diarize="false", speakers_expected="2")

    assert resp.status_code == 202
    assert resp.json()["hints_applied"] is False
    assert sent[0]["num_speakers"] is None


def test_no_hint_reports_null(rig: SimpleNamespace) -> None:
    resp, _ = _submit(rig, diarize="true")

    assert resp.json()["hints_applied"] is None


@pytest.mark.parametrize(
    "data",
    [
        {"speakers_expected": "9"},
        {"speakers_expected": "0"},
        {"speakers_max": "9"},
    ],
)
def test_impossible_hints_are_422(rig: SimpleNamespace, data: dict[str, str]) -> None:
    resp, sent = _submit(rig, diarize="true", **data)

    assert resp.status_code == 422
    assert sent == []


def test_a_person_stated_count_wins_over_a_calendar_cap(rig: SimpleNamespace) -> None:
    """Sprint 30 hint policy: never a 422 — the cap is simply dropped."""
    resp, sent = _submit(rig, diarize="true", speakers_expected="4", speakers_max="2")

    assert resp.status_code == 202
    assert (sent[0]["num_speakers"], sent[0]["max_speakers"]) == (4, None)


# ── Re-run / undo ─────────────────────────────────────────────────────


class _Repo:
    """Jobs keyed by (tenant, job); the claim/undo rules mirror the SQL."""

    def __init__(self) -> None:
        self.jobs: dict[tuple[UUID, UUID], dict[str, Any]] = {}

    def add(self, tenant: UUID, **fields: Any) -> UUID:
        job_id = uuid4()
        self.jobs[(tenant, job_id)] = {
            "status": "complete",
            "diarization_status": None,
            "diarization_error": None,
            "diarization_runs": 0,
            "diarization_rev": 1,
            "audio_available": True,
            "result": "minio://mdx-transcripts/k.json.enc",
            "previous": None,
            **fields,
        }
        return job_id

    async def claim_rediarize(
        self, conn: UUID, *, job_id: UUID, max_runs: int
    ) -> RediarizeClaim | None:
        row = self.jobs.get((conn, job_id))
        if row is None:
            return None
        rev = row["diarization_rev"]
        if row["status"] != "complete":
            return RediarizeClaim(refused="job_not_complete", current_rev=rev)
        if row["diarization_status"] in ("queued", "running"):
            return RediarizeClaim(refused="rediarize_in_progress", current_rev=rev)
        if row["diarization_runs"] >= max_runs:
            return RediarizeClaim(refused="rediarize_limit", current_rev=rev)
        if not row["audio_available"]:
            return RediarizeClaim(refused="audio_unavailable", current_rev=rev)
        claim = RediarizeClaim(
            audio_id=uuid4(),
            requester_sub=uuid4(),
            target_rev=rev + 1,
            current_rev=rev,
            prior_status=row["diarization_status"],
            prior_error=row["diarization_error"],
        )
        row["diarization_status"] = "queued"
        row["diarization_runs"] += 1
        return claim

    async def release_rediarize_claim(
        self, conn: UUID, *, job_id: UUID, claim: RediarizeClaim
    ) -> None:
        row = self.jobs[(conn, job_id)]
        row["diarization_status"] = claim.prior_status
        row["diarization_error"] = claim.prior_error
        row["diarization_runs"] -= 1

    async def has_corrections(self, conn: UUID, *, job_id: UUID) -> bool:
        return False

    async def undo_rediarize(self, conn: UUID, *, job_id: UUID) -> UndoOutcome | None:
        row = self.jobs.get((conn, job_id))
        if row is None:
            return None
        if row["diarization_status"] in ("queued", "running"):
            return UndoOutcome(refused="rediarize_in_progress", rev=row["diarization_rev"])
        if row["previous"] is None:
            return UndoOutcome(refused="nothing_to_undo", rev=row["diarization_rev"])
        undone = row["result"]
        row["result"], row["previous"] = row["previous"], None
        row["diarization_rev"] += 1
        return UndoOutcome(rev=row["diarization_rev"], undone_uri=undone)


class _Producer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fails = False

    async def send(self, *, value: bytes, **_kw: Any) -> None:
        if self.fails:
            raise ConnectionError("redis is down")
        self.sent.append(json.loads(value))


class _Limiter:
    def __init__(self) -> None:
        self.allowed = True

    async def allow(self, scope: str, subject: str, **_kw: Any) -> SimpleNamespace:
        return SimpleNamespace(allowed=self.allowed, retry_after=1200)


class _Store:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, *, key: str) -> None:
        self.deleted.append(key)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kw: Any) -> None:
        self.events.append(kw)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from asr_service import deps
    from asr_service.main import create_app
    from asr_service.routers import jobs

    repo, producer, limiter, store, audit = _Repo(), _Producer(), _Limiter(), _Store(), _Audit()
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            queue_producer=producer,
            limiter=limiter,
            transcript_store=store,
            audit_writer=audit,
        )
    )

    @contextlib.asynccontextmanager
    async def _tenant_conn(_pool: object, tenant_id: UUID) -> Any:
        yield tenant_id

    monkeypatch.setattr(jobs, "tenant_connection", _tenant_conn)
    monkeypatch.setattr(deps, "check", lambda *a, **k: None)
    for name in ("claim_rediarize", "release_rediarize_claim", "undo_rediarize", "has_corrections"):
        monkeypatch.setattr(jobs.repository, name, getattr(repo, name))

    current = {"tid": _TENANT_A}

    def _claims() -> Claims:
        return Claims(
            sub=uuid4(),
            tid=current["tid"],
            roles=["member"],
            sid="s",
            iss="https://t",
            aud="mdx",
            exp=9_999_999_999,
            iat=1_700_000_000,
        )

    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    return SimpleNamespace(
        client=TestClient(app),
        repo=repo,
        producer=producer,
        limiter=limiter,
        store=store,
        audit=audit,
        current=current,
    )


def _rerun(api: SimpleNamespace, job: UUID, n: int | None = 2) -> Any:
    return api.client.post(f"/asr/jobs/{job}/rediarize", json={"speakers_expected": n})


def test_rerun_is_accepted_and_queued_as_a_rediarize_task(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A)

    resp = _rerun(api, job)

    assert resp.status_code == 202
    assert resp.json() == {"job_id": str(job), "diarization_status": "queued", "diarization_rev": 1}
    [msg] = api.producer.sent
    assert (msg["task"], msg["target_rev"], msg["num_speakers"]) == ("rediarize", 2, 2)
    assert api.audit.events[-1]["kind"] == "asr.rediarize_requested"
    assert api.audit.events[-1]["payload"] == {"hint": "exact", "reason": "user_count"}


def test_a_null_count_lets_the_engine_decide(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A)

    assert _rerun(api, job, None).status_code == 202
    assert api.producer.sent[0]["num_speakers"] is None
    assert api.audit.events[-1]["payload"] == {"hint": "none", "reason": "engine_upgrade"}


@pytest.mark.parametrize(
    ("fields", "status", "code"),
    [
        ({"status": "running"}, 409, "job_not_complete"),
        ({"diarization_status": "queued"}, 409, "rediarize_in_progress"),
        ({"audio_available": False}, 409, "audio_unavailable"),
        ({"diarization_runs": 5}, 429, "rediarize_limit"),
    ],
)
def test_rerun_refusals(
    api: SimpleNamespace, fields: dict[str, Any], status: int, code: str
) -> None:
    job = api.repo.add(_TENANT_A, **fields)

    resp = _rerun(api, job)

    assert resp.status_code == status
    assert resp.json()["code"] == code
    assert api.producer.sent == []


def test_the_sixth_rerun_is_refused(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A)
    for _ in range(5):
        assert _rerun(api, job).status_code == 202
        api.repo.jobs[(_TENANT_A, job)]["diarization_status"] = "complete"

    resp = _rerun(api, job)

    assert (resp.status_code, resp.json()["code"]) == (429, "rediarize_limit")


def test_count_out_of_range_is_422(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A)

    assert _rerun(api, job, 9).status_code == 422
    assert _rerun(api, job, 0).status_code == 422


def test_per_user_rate_limit_is_429_with_retry_after(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A)
    api.limiter.allowed = False

    resp = _rerun(api, job)

    assert (resp.status_code, resp.json()["code"]) == (429, "rate_limited")
    assert resp.headers["retry-after"] == "1200"
    assert api.repo.jobs[(_TENANT_A, job)]["diarization_runs"] == 0


def test_a_dead_queue_leaves_the_job_as_it_was(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A)
    api.producer.fails = True

    resp = _rerun(api, job)

    assert (resp.status_code, resp.json()["code"]) == (503, "enqueue_failed")
    row = api.repo.jobs[(_TENANT_A, job)]
    assert (row["diarization_status"], row["diarization_runs"]) == (None, 0)


def test_undo_restores_and_a_second_undo_is_409(api: SimpleNamespace) -> None:
    job = api.repo.add(
        _TENANT_A,
        diarization_rev=2,
        diarization_status="complete",
        result="minio://mdx-transcripts/t/j.r2.json.enc",
        previous="minio://mdx-transcripts/t/j.json.enc",
    )

    first = api.client.post(f"/asr/jobs/{job}/rediarize/undo")
    second = api.client.post(f"/asr/jobs/{job}/rediarize/undo")

    assert first.status_code == 200
    assert first.json()["diarization_rev"] == 3
    assert api.store.deleted == ["t/j.r2.json.enc"]
    assert api.audit.events[-1]["kind"] == "asr.rediarize_undone"
    assert (second.status_code, second.json()["code"]) == (409, "nothing_to_undo")


def test_undo_while_a_rerun_runs_is_409(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A, diarization_status="running", previous="minio://b/k")

    resp = api.client.post(f"/asr/jobs/{job}/rediarize/undo")

    assert (resp.status_code, resp.json()["code"]) == (409, "rediarize_in_progress")


def test_another_tenant_gets_404_and_nothing_is_queued(api: SimpleNamespace) -> None:
    job = api.repo.add(_TENANT_A, previous="minio://b/k")
    api.current["tid"] = _TENANT_B

    assert _rerun(api, job).status_code == 404
    assert api.client.post(f"/asr/jobs/{job}/rediarize/undo").status_code == 404
    assert api.producer.sent == []
    assert api.repo.jobs[(_TENANT_A, job)]["previous"] == "minio://b/k"


# ── Capture context on submit ─────────────────────────────────────────


def _capture_insert(rig: SimpleNamespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    async def insert_job_row(_conn: Any, **kw: Any) -> None:
        rows.append(kw)

    rig.monkeypatch.setattr(rig.jobs.repository, "insert_job_row", insert_job_row)
    return rows


def test_calendar_context_is_stored_and_only_counted_in_audit(rig: SimpleNamespace) -> None:
    rows = _capture_insert(rig)
    names = ["Anna  Keller", "Tom Berg", "anna keller"]

    resp = rig.client.post(
        "/asr/jobs",
        files={"audio": ("m.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")},
        data={
            "language": "en",
            "diarize": "true",
            "speakers_max": "3",
            "name_candidates": json.dumps(names),
            "capture_source": "calendar_event",
        },
        headers={"X-Client-Type": "macos"},
    )

    assert resp.status_code == 202, resp.text
    # Whitespace collapsed, case-insensitive duplicate dropped.
    assert rows[0]["name_candidates"] == ["Anna Keller", "Tom Berg"]
    assert rows[0]["capture_context"] == {
        "source": "calendar_event",
        "client": "macos",
        "channel_layout": "mono",
    }
    queued = next(e for e in rig.audit.events if e["kind"] == "asr.job_queued")
    assert queued["payload"]["name_candidates"] == 2
    assert "Anna" not in json.dumps([e["payload"] for e in rig.audit.events])


@pytest.mark.parametrize(
    "names",
    [
        json.dumps([f"Person {i}" for i in range(13)]),
        json.dumps(["x" * 81]),
        json.dumps(["Anna\u0007"]),
        json.dumps(["   "]),
        json.dumps({"a": "b"}),
        "not json",
    ],
)
def test_bad_name_candidates_are_422(rig: SimpleNamespace, names: str) -> None:
    resp, sent = _submit(rig, diarize="true", name_candidates=names)

    assert resp.status_code == 422
    assert resp.json()["code"] == "name_candidates_invalid"
    assert sent == []


def test_an_unknown_capture_source_is_422(rig: SimpleNamespace) -> None:
    resp, _ = _submit(rig, capture_source="email")

    assert resp.status_code == 422


# ── Dual-channel submit ───────────────────────────────────────────────


def _stereo(rig: SimpleNamespace) -> None:
    from asr_service.validators.result import ok

    from .test_submit_rejections import _facts

    async def run_all(*, mime_type: str, payload: bytes):  # noqa: ANN202
        facts = _facts()
        facts.channels = 2
        return ok(), facts

    rig.monkeypatch.setattr(rig.jobs, "run_all", run_all)


def test_mic_system_rides_the_payload_and_the_name_never_reaches_audit(
    rig: SimpleNamespace,
) -> None:
    _stereo(rig)

    resp, sent = _submit(
        rig,
        diarize="true",
        channel_layout="mic_system",
        local_speaker_name="  Volodymyr  Pugachov ",
    )

    assert resp.status_code == 202, resp.text
    assert (sent[0]["channel_layout"], sent[0]["local_speaker_name"]) == (
        "mic_system",
        "Volodymyr Pugachov",
    )
    queued = next(e for e in rig.audit.events if e["kind"] == "asr.job_queued")
    assert queued["payload"]["channel_layout"] == "mic_system"
    assert "Volodymyr" not in json.dumps([e["payload"] for e in rig.audit.events])


def test_mic_system_on_a_mono_file_is_422(rig: SimpleNamespace) -> None:
    resp, sent = _submit(rig, diarize="true", channel_layout="mic_system")

    assert resp.status_code == 422
    assert resp.json()["code"] == "channel_layout_mismatch"
    assert sent == []


def test_a_stereo_file_without_the_field_is_an_ordinary_upload(rig: SimpleNamespace) -> None:
    """Acceptance 9: arbitrary stereo uploads behave exactly as before."""
    _stereo(rig)

    resp, sent = _submit(rig, diarize="true")

    assert resp.status_code == 202
    assert sent[0]["channel_layout"] == "mono"
    assert sent[0]["local_speaker_name"] is None


def test_an_overlong_local_name_is_422(rig: SimpleNamespace) -> None:
    _stereo(rig)

    resp, _ = _submit(rig, channel_layout="mic_system", local_speaker_name="x" * 81)

    assert resp.status_code == 422
    assert resp.json()["code"] == "local_speaker_name_invalid"
