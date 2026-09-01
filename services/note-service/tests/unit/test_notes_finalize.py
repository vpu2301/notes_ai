"""Behavioural tests for POST /v1/notes/{id}/finalize (Items 2 + 5).

Exercises the real handler with the auth dependency overridden and the
DB/audit boundary stubbed — no infra required (mirrors
``test_notes_versions``).
"""

from __future__ import annotations

import ast
import contextlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteContent, NoteSection


class _FakeRedis:
    """Records XADDs so a test can assert the sprint-12 event was emitted.

    Mirrors the real ServiceState, which now carries a Redis client for
    the notification event bus.
    """

    def __init__(self) -> None:
        self.xadds: list[tuple[str, dict]] = []

    async def xadd(self, name, fields, **kwargs):  # noqa: ANN001, ANN003
        self.xadds.append((name, fields))
        return b"0-1"


REQUESTER_SUB = UUID("11111111-1111-1111-1111-111111111111")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
TEMPLATE_ID = UUID("44444444-4444-4444-4444-444444444444")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
SESSION_ID = UUID("66666666-6666-6666-6666-666666666666")

CURRENT_VERSION_NUMBER = 3


def _member_claims() -> Claims:
    return Claims(
        sub=REQUESTER_SUB,
        tid=uuid4(),
        roles=["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note_row(*, source_session_id: UUID | None = None):
    from note_models import NoteStatus
    from note_service.domain.notes_repository import NoteRow

    now = datetime(2026, 5, 20, tzinfo=UTC)
    return NoteRow(
        id=NOTE_ID,
        tenant_id=uuid4(),
        code="R-0001",
        status=NoteStatus.DRAFT,
        current_version_id=VERSION_ID,
        current_version_number=CURRENT_VERSION_NUMBER,
        primary_author_id=REQUESTER_SUB,
        co_author_ids=[],
        title="Weekly sync",
        created_at=now,
        updated_at=now,
        finalized_at=None,
        cancelled_at=None,
        source_session_id=source_session_id,
    )


def _version_row(sections):
    from note_service.domain.notes_repository import VersionRow

    return VersionRow(
        id=VERSION_ID,
        note_id=NOTE_ID,
        version_number=CURRENT_VERSION_NUMBER,
        parent_version_id=None,
        created_by=REQUESTER_SUB,
        created_at=datetime(2026, 5, 20, tzinfo=UTC),
        content=NoteContent(
            template_id=TEMPLATE_ID,
            template_schema_version=1,
            sections=sections,
        ),
        rendered_text="rendered body",
        body_hash=None,
        is_amendment=False,
        amendment_type=None,
        amendment_reason=None,
    )


def _template(sections):
    return SimpleNamespace(sections=[SimpleNamespace(**s) for s in sections])


def _detail(resp):
    """Recover the (dict) HTTPException detail from the RFC 9457 envelope.

    The service's global handler str()-wraps dict details into the
    ``detail`` member, so we round-trip via ``ast.literal_eval``.
    """
    return ast.literal_eval(resp.json()["detail"])


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_lifecycle

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    fake_redis = _FakeRedis()
    fake_state = SimpleNamespace(
        app_pool=object(),
        audit_writer=SimpleNamespace(write_event=_write_event),
        redis=fake_redis,
    )
    deps.install_state(fake_state)  # type: ignore[arg-type]

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(notes_lifecycle, "tenant_connection", _fake_tenant_conn)

    # No-op state-machine transition (DB-free).
    async def _finalize(conn, *, note_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(notes_lifecycle._sm, "finalize", _finalize)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    c = TestClient(app)
    c.audit_calls = audit_calls  # type: ignore[attr-defined]
    c.notification_redis = fake_redis  # type: ignore[attr-defined]
    return c


def _wire(monkeypatch, *, row, version, template_sections):
    from note_service.routers import notes_lifecycle

    async def _lock(conn, *, note_id):  # noqa: ANN001
        return row

    async def _fetch_v(conn, *, version_id):  # noqa: ANN001
        return version

    async def _tpl(conn, *, template_id):  # noqa: ANN001
        return _template(template_sections)

    set_calls: list[dict] = []

    async def _set_session(conn, *, note_id, session_id):  # noqa: ANN001
        set_calls.append({"note_id": note_id, "session_id": session_id})

    monkeypatch.setattr(notes_lifecycle.repo, "lock_note_for_update", _lock)
    monkeypatch.setattr(notes_lifecycle.repo, "fetch_version", _fetch_v)
    monkeypatch.setattr(notes_lifecycle, "_fetch_template_definition", _tpl)
    monkeypatch.setattr(notes_lifecycle.repo, "set_source_session_id_if_absent", _set_session)
    return set_calls


def test_finalize_422_problems_include_section_key_and_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(
        monkeypatch,
        row=_note_row(),
        version=_version_row([]),  # required section absent
        template_sections=[{"key": "ccx", "required": True, "min_chars": 0}],
    )

    resp = client.post(f"/v1/notes/{NOTE_ID}/finalize")
    assert resp.status_code == 422
    # `problems` is now a first-class RFC-9457 extension member (top-level JSON),
    # not stuffed into the str()-wrapped `detail`.
    payload = resp.json()
    assert payload["code"] == "finalize_validation_failed"
    problems = payload["problems"]
    assert len(problems) == 1
    p = problems[0]
    assert p["section_key"] == "ccx"
    assert p["reason"] == "required_empty"
    # Backward-compat keys retained.
    assert p["code"] == "missing_required_section"
    assert p["field"] == "sections.ccx.text"


def test_finalize_stale_expected_version_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(
        monkeypatch,
        row=_note_row(),
        version=_version_row([NoteSection(section_key="ccx", text="ok")]),
        template_sections=[],
    )

    resp = client.post(
        f"/v1/notes/{NOTE_ID}/finalize",
        json={"expected_version": CURRENT_VERSION_NUMBER - 1},
    )
    assert resp.status_code == 409
    assert _detail(resp)["error"] == "optimistic_lock_mismatch"
    assert client.audit_calls == []  # type: ignore[attr-defined]


def test_finalize_correct_expected_version_succeeds_and_emits_completed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_calls = _wire(
        monkeypatch,
        row=_note_row(source_session_id=None),
        version=_version_row(
            [
                NoteSection(section_key="findings", text="Normal [[uncertain]] study"),
                NoteSection(section_key="impression", text="Clear"),
            ]
        ),
        template_sections=[],
    )

    resp = client.post(
        f"/v1/notes/{NOTE_ID}/finalize",
        json={
            "expected_version": CURRENT_VERSION_NUMBER,
            "dictation_session_id": str(SESSION_ID),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "finalized"

    # Session linkage was persisted (note had none).
    assert set_calls == [{"note_id": NOTE_ID, "session_id": SESSION_ID}]

    calls = client.audit_calls  # type: ignore[attr-defined]
    kinds = [c["kind"] for c in calls]
    assert "note.finalized" in kinds
    assert "note.completed" in kinds

    completed = next(c for c in calls if c["kind"] == "note.completed")
    assert completed["target_id"] == str(NOTE_ID)
    payload = completed["payload"]
    assert payload["version_number"] == CURRENT_VERSION_NUMBER
    assert payload["section_count"] == 2
    assert payload["low_confidence_count"] == 1

    # Sprint-12: finalizing publishes exactly one notification event onto
    # the bus, carrying the note CODE and no title (ADR-0031).
    xadds = client.notification_redis.xadds  # type: ignore[attr-defined]
    assert len(xadds) == 1
    stream, fields = xadds[0]
    assert stream == "mdx:notifications:events"
    envelope = json.loads(fields[b"value"].decode())
    assert envelope["category"] == "note.finalized"
    assert envelope["payload"] == {"note_code": "R-0001"}
    assert envelope["resource_id"] == str(NOTE_ID)
    assert payload["source_session_id"] == str(SESSION_ID)


def test_finalize_no_body_backward_compatible(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_calls = _wire(
        monkeypatch,
        row=_note_row(source_session_id=SESSION_ID),
        version=_version_row([NoteSection(section_key="ccx", text="ok")]),
        template_sections=[],
    )

    resp = client.post(f"/v1/notes/{NOTE_ID}/finalize")
    assert resp.status_code == 200
    # No dictation_session_id supplied → no backfill attempt.
    assert set_calls == []

    completed = next(
        c
        for c in client.audit_calls
        if c["kind"] == "note.completed"  # type: ignore[attr-defined]
    )
    # Existing source session is surfaced in the payload.
    assert completed["payload"]["source_session_id"] == str(SESSION_ID)
