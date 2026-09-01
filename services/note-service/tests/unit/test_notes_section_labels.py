"""GET /v1/notes/{id} returns localized section_labels (spec item 4).

Exercises the real ``notes.get_note`` handler with the auth dependency
overridden and the DB/audit boundary stubbed — no infra required (mirrors
``test_notes_versions``).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteContent, NoteSection

REQUESTER_SUB = UUID("11111111-1111-1111-1111-111111111111")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
TEMPLATE_ID = UUID("44444444-4444-4444-4444-444444444444")


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


def _note_row():
    from note_models import NoteStatus
    from note_service.domain.notes_repository import NoteRow

    now = datetime(2026, 5, 20, tzinfo=UTC)
    return NoteRow(
        id=NOTE_ID,
        tenant_id=uuid4(),
        code="R-0001",
        status=NoteStatus.FINALIZED,
        current_version_id=uuid4(),
        current_version_number=2,
        primary_author_id=REQUESTER_SUB,
        co_author_ids=[],
        title="Chest CT",
        created_at=now,
        updated_at=now,
        finalized_at=now,
        cancelled_at=None,
    )


def _content() -> NoteContent:
    return NoteContent(
        template_id=TEMPLATE_ID,
        template_schema_version=1,
        sections=[
            NoteSection(section_key="findings", text="..."),
            NoteSection(section_key="impression", text="..."),
        ],
    )


def _version_row():
    from note_service.domain.notes_repository import VersionRow

    return VersionRow(
        id=uuid4(),
        note_id=NOTE_ID,
        version_number=2,
        parent_version_id=None,
        created_by=REQUESTER_SUB,
        created_at=datetime(2026, 5, 20, tzinfo=UTC),
        content=_content(),
        rendered_text="rendered body",
        body_hash=None,
        is_amendment=False,
        amendment_type=None,
        amendment_reason=None,
    )


def _template_schema_jsonb() -> dict:
    from template_models import TemplateDefinition, TemplateSection

    definition = TemplateDefinition(
        code="chest_ct",
        name="Chest CT",
        language="en",
        category="radiology",
        schema_version=1,
        sections=(
            TemplateSection(id="impression", name="Impression", asr_prompt="impression", order=2),
            TemplateSection(id="findings", name="Findings", asr_prompt="findings", order=1),
        ),
    )
    return definition.model_dump(mode="json")


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

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return _note_row()

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return _version_row()

    monkeypatch.setattr(notes.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(notes.repo, "fetch_version", _fetch_version)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    c = TestClient(app)
    c.audit_calls = audit_calls  # type: ignore[attr-defined]
    return c


def test_get_note_includes_localized_section_labels(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from note_service.domain import repository

    async def _get_template(conn, *, template_id):  # noqa: ANN001
        assert template_id == TEMPLATE_ID
        return {"schema_jsonb": _template_schema_jsonb()}

    monkeypatch.setattr(repository, "get_template", _get_template)

    resp = client.get(f"/v1/notes/{NOTE_ID}")
    assert resp.status_code == 200
    labels = resp.json()["section_labels"]
    # Ordered by template section.order: findings (1) before impression (2).
    assert [lbl["section_key"] for lbl in labels] == ["findings", "impression"]
    # Per-language template name mirrored into both locales.
    assert labels[0]["name"] == {"uk": "Findings", "en": "Findings"}
    assert labels[1]["name"] == {"uk": "Impression", "en": "Impression"}


def test_get_note_section_labels_none_when_template_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from note_service.domain import repository

    async def _get_template(conn, *, template_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(repository, "get_template", _get_template)

    resp = client.get(f"/v1/notes/{NOTE_ID}")
    assert resp.status_code == 200
    assert resp.json()["section_labels"] is None
