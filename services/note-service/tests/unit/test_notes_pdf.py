"""Behavioural tests for ``GET /notes/{id}/pdf`` (M1·A3).

The actual weasyprint render is stubbed — these assert the lifecycle
gate, content negotiation and audit, not the renderer.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteContent, NoteStatus

REQUESTER_SUB = UUID("11111111-1111-1111-1111-111111111111")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
TEMPLATE_ID = UUID("44444444-4444-4444-4444-444444444444")


def _member_claims() -> Claims:
    return Claims(
        sub=REQUESTER_SUB,
        tid=uuid4(),
        roles=["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note_row(*, status: NoteStatus, finalized: bool):
    from note_service.domain.notes_repository import NoteRow

    now = datetime(2026, 5, 20, tzinfo=UTC)
    return NoteRow(
        id=NOTE_ID,
        tenant_id=uuid4(),
        code="N-0001",
        status=status,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=REQUESTER_SUB,
        co_author_ids=[],
        title="Weekly sync",
        created_at=now,
        updated_at=now,
        finalized_at=now if finalized else None,
        cancelled_at=None,
    )


def _version_row():
    from note_service.domain.notes_repository import VersionRow

    return VersionRow(
        id=uuid4(),
        note_id=NOTE_ID,
        version_number=1,
        parent_version_id=None,
        created_by=REQUESTER_SUB,
        created_at=datetime(2026, 5, 20, tzinfo=UTC),
        content=NoteContent(template_id=TEMPLATE_ID, template_schema_version=1),
        rendered_text="body",
        body_hash=None,
        is_amendment=False,
        amendment_type=None,
        amendment_reason=None,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_pdf

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
        )
    )

    class _FakeConn:
        async def fetchrow(self, *args, **kwargs):  # noqa: ANN002, ANN003
            # No branding row in unit env → PDF issuer falls back to default.
            return None

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield _FakeConn()

    monkeypatch.setattr(notes_pdf, "tenant_connection", _fake_tenant_conn)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    c = TestClient(app)
    c.audit_calls = audit_calls  # type: ignore[attr-defined]
    return c


def test_pdf_404_when_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from note_service.routers import notes_pdf

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(notes_pdf.repo, "fetch_note", _fetch_note)
    assert client.get(f"/v1/notes/{NOTE_ID}/pdf").status_code == 404


def test_pdf_409_for_cancelled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from note_service.routers import notes_pdf

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return _note_row(status=NoteStatus.CANCELLED, finalized=True)

    monkeypatch.setattr(notes_pdf.repo, "fetch_note", _fetch_note)
    resp = client.get(f"/v1/notes/{NOTE_ID}/pdf")
    assert resp.status_code == 409
    assert "note-cancelled" in resp.text
    assert client.audit_calls == []  # type: ignore[attr-defined]


def test_pdf_200_for_draft_with_watermark(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A draft note renders a PDF with the draft treatment on."""
    from note_service.routers import notes_pdf

    captured: dict = {}

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return _note_row(status=NoteStatus.DRAFT, finalized=False)

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return _version_row()

    def _render(*, note, version, issuer_name, is_draft, language):  # noqa: ANN001
        captured["is_draft"] = is_draft
        captured["language"] = language
        # The native weasyprint stack is not installed in unit envs, so the
        # render itself is stubbed (mirrors the finalized test); the template
        # wiring is asserted separately via direct Jinja rendering below.
        return b"%PDF-1.7 draft-bytes"

    monkeypatch.setattr(notes_pdf.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(notes_pdf.repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(notes_pdf, "render_note_pdf", _render)

    resp = client.get(f"/v1/notes/{NOTE_ID}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert f"note-{NOTE_ID}-draft.pdf" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 0
    # The draft note forces the draft treatment.
    assert captured["is_draft"] is True
    assert captured["language"] == "en"

    calls = client.audit_calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0]["kind"] == "note.pdf_rendered"
    assert calls[0]["payload"]["variant"] == "draft"


def test_pdf_clean_variant_ignored_for_draft(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """variant=clean is NOT honoured for a draft note."""
    from note_service.routers import notes_pdf

    captured: dict = {}

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return _note_row(status=NoteStatus.DRAFT, finalized=False)

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return _version_row()

    def _render(*, note, version, issuer_name, is_draft, language):  # noqa: ANN001
        captured["is_draft"] = is_draft
        return b"%PDF-1.7 x"

    monkeypatch.setattr(notes_pdf.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(notes_pdf.repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(notes_pdf, "render_note_pdf", _render)

    resp = client.get(f"/v1/notes/{NOTE_ID}/pdf?variant=clean")
    assert resp.status_code == 200
    assert captured["is_draft"] is True
    assert f"note-{NOTE_ID}-draft.pdf" in resp.headers["content-disposition"]


def test_pdf_clean_variant_honoured_for_finalized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from note_service.routers import notes_pdf

    captured: dict = {}

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return _note_row(status=NoteStatus.FINALIZED, finalized=True)

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return _version_row()

    def _render(*, note, version, issuer_name, is_draft, language):  # noqa: ANN001
        captured["is_draft"] = is_draft
        return b"%PDF-1.7 clean"

    monkeypatch.setattr(notes_pdf.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(notes_pdf.repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(notes_pdf, "render_note_pdf", _render)

    resp = client.get(f"/v1/notes/{NOTE_ID}/pdf?variant=clean")
    assert resp.status_code == 200
    assert captured["is_draft"] is False
    assert f"note-{NOTE_ID}.pdf" in resp.headers["content-disposition"]


def test_pdf_template_gates_draft_elements_bilingual() -> None:
    """The ``is_draft`` template var gates a bilingual watermark + banner."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    import note_service.domain.pdf as pdfmod

    env = Environment(
        loader=FileSystemLoader(str(pdfmod._TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("note.html.j2")

    base = {
        "title": "t",
        "code": "N-1",
        "issuer": "iss",
        "primary_author": "a",
        "co_authors": [],
        "sections": [],
        "finalized_at": "",
    }

    draft_uk = tpl.render(**base, language="uk", is_draft=True)
    assert "ЧЕРНЕТКА" in draft_uk
    assert "НЕ ФІНАЛІЗОВАНО" in draft_uk

    draft_en = tpl.render(**base, language="en", is_draft=True)
    assert "DRAFT" in draft_en
    assert "NOT FINALIZED" in draft_en

    clean = tpl.render(**base, language="uk", is_draft=False)
    assert "ЧЕРНЕТКА" not in clean
    assert "draft-watermark" not in clean


def test_pdf_200_for_finalized(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from note_service.routers import notes_pdf

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return _note_row(status=NoteStatus.FINALIZED, finalized=True)

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return _version_row()

    def _render(*, note, version, issuer_name, is_draft, language):  # noqa: ANN001
        return b"%PDF-1.7 fake-bytes"

    monkeypatch.setattr(notes_pdf.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(notes_pdf.repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(notes_pdf, "render_note_pdf", _render)

    resp = client.get(f"/v1/notes/{NOTE_ID}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content == b"%PDF-1.7 fake-bytes"

    calls = client.audit_calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0]["kind"] == "note.pdf_rendered"
    assert calls[0]["payload"]["size_bytes"] == len(b"%PDF-1.7 fake-bytes")
