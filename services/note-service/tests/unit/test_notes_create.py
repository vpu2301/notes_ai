"""POST /v1/notes — create path with the DB/audit boundary stubbed.

Exercises the real ``notes.create_note`` handler with the auth
dependency overridden — no infra required (mirrors
``test_notes_section_labels``).
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims

REQUESTER_SUB = UUID("11111111-1111-1111-1111-111111111111")
TEMPLATE_ID = UUID("44444444-4444-4444-4444-444444444444")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")


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


def _content_payload() -> dict:
    return {
        "template_id": str(TEMPLATE_ID),
        "template_schema_version": 1,
        "title": "Weekly sync",
        "sections": [{"section_key": "decisions", "text": "Ship the beta on Friday"}],
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    fake_state = SimpleNamespace(
        app_pool=object(),
        audit_writer=SimpleNamespace(write_event=_write_event),
    )
    deps.install_state(fake_state)  # type: ignore[arg-type]

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(notes, "tenant_connection", _fake_tenant_conn)

    async def _next_code(conn, *, tenant_id):  # noqa: ANN001
        return "NOTE-2026-00001"

    monkeypatch.setattr(notes.code_sequence, "next_code", _next_code)

    async def _no_metadata_check(conn, *, content):  # noqa: ANN001
        return None

    monkeypatch.setattr(notes, "ensure_valid_field_metadata", _no_metadata_check)

    create_calls: list[dict] = []

    async def _create(conn, **kwargs):  # noqa: ANN001, ANN003
        create_calls.append(kwargs)
        return NOTE_ID, VERSION_ID

    monkeypatch.setattr(notes.repo, "create_note_with_v1", _create)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    c = TestClient(app)
    c.audit_calls = audit_calls  # type: ignore[attr-defined]
    c.create_calls = create_calls  # type: ignore[attr-defined]
    return c


def test_create_missing_content_422(client: TestClient) -> None:
    # content absent → Pydantic rejects before any DB work.
    resp = client.post("/v1/notes", json={})
    assert resp.status_code == 422
    assert client.create_calls == []  # type: ignore[attr-defined]


def test_create_unknown_key_422(client: TestClient) -> None:
    # extra="forbid" on the request model: the deleted patient_id key
    # is rejected rather than silently ignored.
    resp = client.post(
        "/v1/notes",
        json={"content": _content_payload(), "patient_id": str(uuid4())},
    )
    assert resp.status_code == 422
    assert client.create_calls == []  # type: ignore[attr-defined]


def test_create_201_author_is_caller(client: TestClient) -> None:
    resp = client.post("/v1/notes", json={"content": _content_payload()})
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(NOTE_ID)
    assert body["status"] == "draft"
    assert body["code"] == "NOTE-2026-00001"

    create = client.create_calls[0]  # type: ignore[attr-defined]
    assert create["primary_author_id"] == REQUESTER_SUB
    assert create["co_author_ids"] == []
    assert create["template_id"] == TEMPLATE_ID

    (event,) = client.audit_calls  # type: ignore[attr-defined]
    assert event["kind"] == "note.created"
    assert event["payload"]["code"] == "NOTE-2026-00001"
