"""W3 B-5: the note linked to a job gates its transcript and its changes.

``note_access_for_job`` is faked per test: ``None`` = no linked note (today's
rule), a ``NoteAccess`` = the caller's level on the linked note, an
exception = the function is unavailable (fail closed).
"""

# ruff: noqa: F811 — `result_rig` is the result route's fixture, imported below
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from asr_models import JobStatus, TranscriptionJobView
from asr_service.domain.repository import note_access_for_job as real_note_access_for_job
from auth import Claims

from .test_result_endpoint import _job_view
from .test_result_endpoint import rig as result_rig  # noqa: F401

_TENANT = uuid4()
_ME = uuid4()

VIEW = ("view", False)
VIEW_SHARED = ("view", True)
COMMENT = ("comment", False)
EDIT = ("edit", True)


def _install_access(monkeypatch: pytest.MonkeyPatch, access: tuple[str, bool] | None) -> None:
    from asr_service.domain import repository

    async def fake(_conn: Any, *, job_id: UUID, sub: UUID, roles: list[str]) -> Any:
        return None if access is None else repository.NoteAccess(*access)

    monkeypatch.setattr(repository, "note_access_for_job", fake)


def _install_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from asr_service.domain import repository

    async def broken(_conn: Any, **_k: Any) -> Any:
        raise repository.NoteAccessUnavailableError

    monkeypatch.setattr(repository, "note_access_for_job", broken)


# ── GET /asr/jobs/{id}/result (the result route's own rig) ──────────────


@pytest.fixture
def complete_job(monkeypatch: pytest.MonkeyPatch) -> TranscriptionJobView:
    from asr_service.routers import jobs

    view = _job_view(JobStatus.COMPLETE)

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    return view


def test_result_hidden_from_a_view_collaborator_is_404(
    result_rig: SimpleNamespace, complete_job: TranscriptionJobView, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, VIEW)
    resp = result_rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 404
    assert resp.json()["code"] == "job_not_found"
    assert result_rig.store.calls == []  # nothing decrypted
    assert result_rig.audit.events == []


def test_result_shared_with_a_view_collaborator_is_200(
    result_rig: SimpleNamespace, complete_job: TranscriptionJobView, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, VIEW_SHARED)
    assert result_rig.client.get(f"/asr/jobs/{uuid4()}/result").status_code == 200


def test_result_for_an_edit_collaborator_is_200(
    result_rig: SimpleNamespace, complete_job: TranscriptionJobView, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, EDIT)
    assert result_rig.client.get(f"/asr/jobs/{uuid4()}/result").status_code == 200


def test_result_of_an_unlinked_job_is_unchanged(
    result_rig: SimpleNamespace, complete_job: TranscriptionJobView, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, None)
    assert result_rig.client.get(f"/asr/jobs/{uuid4()}/result").status_code == 200


def test_result_fails_closed_when_the_note_check_is_unavailable(
    result_rig: SimpleNamespace, complete_job: TranscriptionJobView, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_unavailable(monkeypatch)
    resp = result_rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 404
    assert resp.json()["code"] == "job_not_found"
    assert result_rig.store.calls == []


def test_a_hidden_job_and_a_missing_job_answer_the_same(
    result_rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    async def _missing(conn, *, job_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(jobs.repository, "get_job", _missing)
    missing = result_rig.client.get(f"/asr/jobs/{uuid4()}/result").json()
    _install_access(monkeypatch, VIEW)
    hidden = result_rig.client.get(f"/asr/jobs/{uuid4()}/result").json()
    for body in (missing, hidden):
        body.pop("instance")
    assert hidden == missing


# ── The other routes ────────────────────────────────────────────────────


def _claims() -> Claims:
    return Claims(
        sub=_ME,
        tid=_TENANT,
        roles=["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


class _Repo:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.list_kwargs: list[dict[str, Any]] = []
        self.list_unavailable = False

    async def get_job_and_result_uri(self, conn: Any, *, job_id: UUID) -> Any:
        self.calls.append("get_job_and_result_uri")
        view = _job_view(JobStatus.COMPLETE).model_copy(update={"id": job_id})
        return view, None

    async def set_speaker_names(self, conn: Any, *, job_id: UUID, names: dict[str, str]) -> Any:
        self.calls.append("set_speaker_names")
        return dict(names)

    async def update_name_sources(self, conn: Any, **_k: Any) -> dict[str, str]:
        return {}

    async def request_cancel(self, conn: Any, *, job_id: UUID) -> str:
        self.calls.append("request_cancel")
        return "cancelled"

    async def has_corrections(self, conn: Any, *, job_id: UUID) -> bool:
        return False

    async def claim_rediarize(self, conn: Any, **_k: Any) -> Any:
        self.calls.append("claim_rediarize")
        return None

    async def list_jobs(self, conn: Any, **kwargs: Any) -> list[TranscriptionJobView]:
        from asr_service.domain import repository

        self.list_kwargs.append(kwargs)
        if self.list_unavailable and not kwargs.get("own_only"):
            raise repository.NoteAccessUnavailableError
        return []


class _Store:
    def __init__(self) -> None:
        self.presigned: list[str] = []

    async def presigned_url(self, *, key: str, expires_in: int) -> str:
        self.presigned.append(key)
        return f"https://store.test/{key}"


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _Limiter:
    async def allow(self, *_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(allowed=True, retry_after=0)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from asr_service import deps
    from asr_service.main import create_app
    from asr_service.routers import jobs

    repo = _Repo()
    store = _Store()
    audit = _Audit()
    deps.install_state(
        SimpleNamespace(
            app_pool=object(),
            transcript_store=store,
            audit_writer=audit,
            limiter=_Limiter(),
        )  # type: ignore[arg-type]
    )

    @contextlib.asynccontextmanager
    async def _tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(jobs, "tenant_connection", _tenant_conn)
    for name in (
        "get_job_and_result_uri",
        "set_speaker_names",
        "update_name_sources",
        "request_cancel",
        "has_corrections",
        "claim_rediarize",
        "list_jobs",
    ):
        monkeypatch.setattr(jobs.repository, name, getattr(repo, name))
    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    return SimpleNamespace(client=TestClient(app), repo=repo, store=store, audit=audit)


def test_job_status_with_its_result_url_follows_the_transcript_rule(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, COMMENT)
    resp = api.client.get(f"/asr/jobs/{uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "job_not_found"
    assert api.store.presigned == []

    _install_access(monkeypatch, VIEW_SHARED)
    resp = api.client.get(f"/asr/jobs/{uuid4()}")
    assert resp.status_code == 200
    assert resp.json()["result_url"].startswith("https://store.test/")


def test_naming_speakers_as_a_comment_collaborator_is_403(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, COMMENT)
    resp = api.client.put(f"/asr/jobs/{uuid4()}/speakers", json={"names": {"SPEAKER_1": "Anna"}})
    assert resp.status_code == 403
    assert resp.json()["code"] == "insufficient_role"
    assert "set_speaker_names" not in api.repo.calls
    assert api.audit.events == []


def test_naming_speakers_as_an_edit_collaborator_is_allowed(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, EDIT)
    resp = api.client.put(f"/asr/jobs/{uuid4()}/speakers", json={"names": {"SPEAKER_1": "Anna"}})
    assert resp.status_code == 200
    assert "set_speaker_names" in api.repo.calls


def test_naming_speakers_on_an_unlinked_job_is_unchanged(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, None)
    resp = api.client.put(f"/asr/jobs/{uuid4()}/speakers", json={"names": {"SPEAKER_1": "Anna"}})
    assert resp.status_code == 200


def test_a_view_collaborator_with_the_transcript_still_cannot_edit_it(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, VIEW_SHARED)
    job = uuid4()
    assert api.client.post(f"/asr/jobs/{job}/rediarize", json={}).status_code == 403
    assert api.client.post(f"/asr/jobs/{job}/rediarize/undo").status_code == 403
    assert api.client.post(f"/asr/jobs/{job}/speakers/edits/reset").status_code == 403
    assert api.client.delete(f"/asr/jobs/{job}/speakers/edits/{uuid4()}").status_code == 403
    assert (
        api.client.post(
            f"/asr/jobs/{job}/speakers/merge", json={"from": "SPEAKER_1", "into": "SPEAKER_2"}
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            f"/asr/jobs/{job}/speakers/suggestions/dismiss",
            json={"label": "SPEAKER_1", "name": "Anna"},
        ).status_code
        == 403
    )
    assert api.client.delete(f"/asr/jobs/{job}").status_code == 403
    assert api.repo.calls == []


def test_cancel_as_an_edit_collaborator_is_allowed(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, EDIT)
    resp = api.client.delete(f"/asr/jobs/{uuid4()}")
    assert resp.status_code == 202
    assert api.repo.calls == ["request_cancel"]


def test_an_edit_route_fails_closed_when_the_note_check_is_unavailable(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_unavailable(monkeypatch)
    resp = api.client.put(f"/asr/jobs/{uuid4()}/speakers", json={"names": {}})
    assert resp.status_code == 404
    assert resp.json()["code"] == "job_not_found"
    assert api.repo.calls == []


def test_list_passes_the_caller_to_the_gated_query(api: SimpleNamespace) -> None:
    assert api.client.get("/asr/jobs?limit=7").status_code == 200
    (kwargs,) = api.repo.list_kwargs
    assert kwargs["sub"] == _ME
    assert kwargs["roles"] == ["member"]
    assert kwargs["limit"] == 7
    assert not kwargs.get("own_only")


def test_list_falls_back_to_own_jobs_when_the_note_check_is_unavailable(
    api: SimpleNamespace,
) -> None:
    api.repo.list_unavailable = True
    assert api.client.get("/asr/jobs").status_code == 200
    assert [k.get("own_only", False) for k in api.repo.list_kwargs] == [False, True]


# ── Corrections (spellings are transcript content) ──────────────────────


def test_corrections_follow_the_note_rules(
    api: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_access(monkeypatch, VIEW)
    job = uuid4()
    resp = api.client.get(f"/asr/jobs/{job}/corrections")
    assert resp.status_code == 404
    assert resp.json()["code"] == "job_not_found"
    _install_access(monkeypatch, VIEW_SHARED)
    resp = api.client.put(
        f"/asr/jobs/{job}/corrections/{uuid4()}",
        json={"status": "rejected", "corrections_rev": 0},
    )
    assert resp.status_code == 403
    assert api.client.post(f"/asr/jobs/{job}/corrections:recompute").status_code == 403


# ── Repository (the real function; conftest stubs the module attribute) ─


class _Conn:
    """Records SQL; ``transaction()`` is the savepoint the repository opens."""

    def __init__(self, *, row: dict[str, Any] | None = None, error: Exception | None = None):
        self.row = row
        self.error = error
        self.sql: list[tuple[str, tuple[Any, ...]]] = []
        self.savepoints = 0

    @contextlib.asynccontextmanager
    async def _tx(self) -> Any:
        self.savepoints += 1
        yield

    def transaction(self) -> Any:
        return self._tx()

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.sql.append((sql, args))
        if self.error is not None:
            raise self.error
        return self.row

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.sql.append((sql, args))
        if self.error is not None:
            raise self.error
        return []


async def test_repository_reads_the_level_and_the_transcript_flag() -> None:
    from asr_service.domain import repository

    conn = _Conn(row={"level": "comment", "transcript": True})
    got = await real_note_access_for_job(
        conn,  # type: ignore[arg-type]
        job_id=uuid4(),
        sub=_ME,
        roles=["viewer"],
    )
    assert got == repository.NoteAccess(level="comment", transcript=True)
    assert "public.note_access_for_job($1, $2, $3::text[])" in conn.sql[0][0]
    assert conn.savepoints == 1


async def test_repository_no_row_means_unlinked() -> None:
    got = await real_note_access_for_job(
        _Conn(row=None),  # type: ignore[arg-type]
        job_id=uuid4(),
        sub=_ME,
        roles=["member"],
    )
    assert got is None


async def test_repository_a_missing_function_is_unavailable_not_unlinked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from asr_service.domain import repository

    conn = _Conn(error=asyncpg.UndefinedFunctionError("function does not exist"))
    with pytest.raises(repository.NoteAccessUnavailableError):
        await real_note_access_for_job(
            conn,  # type: ignore[arg-type]
            job_id=uuid4(),
            sub=_ME,
            roles=["member"],
        )
    assert "asr.note_access_unavailable" in caplog.text


async def test_repository_list_filters_before_the_limit_and_keeps_own_jobs() -> None:
    from asr_service.domain import repository

    conn = _Conn()
    await repository.list_jobs(
        conn,  # type: ignore[arg-type]
        limit=20,
        sub=_ME,
        roles=["member"],
        status=JobStatus.COMPLETE,
    )
    sql, args = conn.sql[0]
    assert "j.requester_sub = $1 OR NOT EXISTS" in sql
    assert "note_access_for_job(j.id, $1, $2::text[])" in sql
    assert "WHERE NOT a.transcript" in sql
    assert sql.index("NOT EXISTS") < sql.index("LIMIT")
    assert args == (_ME, ["member"], "complete", 20)


async def test_repository_list_own_only_skips_the_note_function() -> None:
    from asr_service.domain import repository

    conn = _Conn()
    await repository.list_jobs(
        conn,  # type: ignore[arg-type]
        limit=5,
        sub=_ME,
        roles=["member"],
        own_only=True,
    )
    sql, args = conn.sql[0]
    assert "note_access_for_job" not in sql
    assert "j.requester_sub = $1" in sql
    assert args == (_ME, 5)


async def test_repository_list_raises_unavailable_on_a_missing_function() -> None:
    from asr_service.domain import repository

    conn = _Conn(error=asyncpg.UndefinedFunctionError("function does not exist"))
    with pytest.raises(repository.NoteAccessUnavailableError):
        await repository.list_jobs(
            conn,  # type: ignore[arg-type]
            limit=5,
            sub=_ME,
            roles=["member"],
        )


async def test_a_linked_note_you_cannot_see_hides_the_job_everywhere() -> None:
    """Migration 0075 returns level NULL for a linked note without a grant: never the `asr.read` fallback."""
    import pytest
    from fastapi import HTTPException

    from asr_service.domain import repository
    from asr_service.routers import jobs

    async def _hidden(conn, *, job_id, sub, roles):  # noqa: ANN001, ANN202
        return repository.NoteAccess(level=None, transcript=False)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(repository, "note_access_for_job", _hidden)

        class _Conn:
            pass

        import contextlib

        @contextlib.asynccontextmanager
        async def _tc(pool, tid):  # noqa: ANN001, ANN202
            yield _Conn()

        mp.setattr(jobs, "tenant_connection", _tc)
        mp.setattr(jobs, "get_state", lambda: type("S", (), {"app_pool": None})())
        claims = type("C", (), {"tid": None, "sub": None, "roles": ["member"]})()
        for need in ("transcript", "edit"):
            with pytest.raises(HTTPException) as exc:
                await jobs.require_note_access(claims, job_id=None, need=need)  # type: ignore[arg-type]
            assert exc.value.status_code == 404
