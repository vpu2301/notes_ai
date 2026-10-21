"""P2 T1 — /v1/ai/templates: built-ins read-only, a workspace's override, reset, validation,
roles and tenant isolation. Real handlers, auth overridden, the repository stubbed per tenant."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import templates_repository as repo
from note_service.domain import writer

TENANT_A = UUID("22222222-2222-2222-2222-222222222222")
TENANT_B = UUID("33333333-3333-3333-3333-333333333333")
USER = UUID("11111111-1111-1111-1111-111111111111")
OVERRIDE = "## Overview\n*One sentence.*\n## Decisions\n*What was decided.*"


def _claims(role: str = "tenant_admin", tenant: UUID = TENANT_A) -> Claims:
    roles = {"tenant_admin": ["tenant_admin", "member"]}.get(role, [role])
    return Claims(sub=USER, tid=tenant, roles=roles, sid="s", iss="https://test/issuer", aud="mdx",
                  exp=9_999_999_999, iat=1_700_000_000)  # fmt: skip


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import ai_templates as mod

    audit: list[dict] = []
    rows: dict[tuple[UUID, str, str], repo.Row] = {}
    current = {"tenant": TENANT_A}

    async def _write_event(**kwargs: Any) -> None:
        audit.append(kwargs)

    deps.install_state(
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event))
    )  # type: ignore[arg-type]

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        current["tenant"] = tenant_id
        yield None

    async def _fetch_all(conn: Any, *, tenant_id: UUID) -> list[repo.Row]:
        return [r for (t, _n, _l), r in rows.items() if t == tenant_id == current["tenant"]]

    async def _fetch(conn: Any, *, tenant_id: UUID, name: str, language: str) -> repo.Row | None:
        return rows.get((tenant_id, name, language)) if tenant_id == current["tenant"] else None

    async def _upsert(conn: Any, **kw: Any) -> repo.Row:
        now = datetime.now(UTC)
        row = repo.Row(tenant_id=kw["tenant_id"], name=kw["name"], language=kw["language"],
                       markdown=kw["markdown"], updated_by=kw["updated_by"], created_at=now, updated_at=now)  # fmt: skip
        rows[(kw["tenant_id"], kw["name"], kw["language"])] = row
        return row

    async def _delete(conn: Any, *, tenant_id: UUID, name: str, language: str) -> bool:
        return rows.pop((tenant_id, name, language), None) is not None

    monkeypatch.setattr(mod, "tenant_connection", _conn)
    monkeypatch.setattr(mod.repo, "fetch_all", _fetch_all)
    monkeypatch.setattr(mod.repo, "fetch", _fetch)
    monkeypatch.setattr(mod.repo, "upsert", _upsert)
    monkeypatch.setattr(mod.repo, "delete", _delete)
    app = create_app()

    def as_(role: str, tenant: UUID = TENANT_A) -> None:
        app.dependency_overrides[deps.current_user] = lambda: _claims(role, tenant)

    as_("tenant_admin")
    yield SimpleNamespace(client=TestClient(app), as_=as_, rows=rows, audit=audit)
    app.dependency_overrides.clear()
    deps.install_state(None)  # type: ignore[arg-type]


def test_the_list_is_every_built_in_per_language_read_only(api: Any) -> None:
    body = api.client.get("/v1/ai/templates").json()
    assert len(body) == 7 * 3
    meeting_de = next(t for t in body if t["name"] == "meeting" and t["language"] == "de")
    assert meeting_de["source"] == "builtin" and meeting_de["markdown"] == writer.template_text(
        "meeting", "de"
    )
    assert meeting_de["can_edit"] is True and meeting_de["updated_at"] is None
    # `?language=` narrows the list to the seven of one language (what a Settings page shows).
    only_uk = api.client.get("/v1/ai/templates", params={"language": "uk"}).json()
    assert [t["name"] for t in only_uk] == list(writer.TEMPLATES) + [writer.AUTO]
    assert {t["language"] for t in only_uk} == {"uk"}


def test_an_override_is_served_and_a_delete_restores_the_built_in(api: Any) -> None:
    put = api.client.put("/v1/ai/templates/meeting", json={"language": "en", "markdown": OVERRIDE})
    assert put.status_code == 200 and put.json()["source"] == "workspace"
    one = api.client.get("/v1/ai/templates/meeting?language=en").json()
    assert one["source"] == "workspace" and one["markdown"] == OVERRIDE
    listed = {
        (t["name"], t["language"]): t["source"] for t in api.client.get("/v1/ai/templates").json()
    }
    assert listed[("meeting", "en")] == "workspace" and listed[("meeting", "de")] == "builtin"
    assert api.client.delete("/v1/ai/templates/meeting?language=en").status_code == 204
    assert api.client.get("/v1/ai/templates/meeting?language=en").json()["source"] == "builtin"
    assert (
        api.client.delete("/v1/ai/templates/meeting?language=en").status_code == 204
    )  # idempotent
    assert [e["kind"] for e in api.audit] == ["ai.template_changed", "ai.template_reset"]
    assert OVERRIDE not in str(api.audit)


def test_validation_is_a_400_and_an_unknown_name_a_404(api: Any) -> None:
    long = api.client.put(
        "/v1/ai/templates/memo", json={"language": "en", "markdown": "## A\n" + "x" * 4_000}
    )
    assert long.status_code == 400 and long.json()["code"] == "template_too_long"
    flat = api.client.put(
        "/v1/ai/templates/memo", json={"language": "en", "markdown": "just prose"}
    )
    assert flat.status_code == 400 and flat.json()["code"] == "template_no_sections"
    assert (
        api.client.put(
            "/v1/ai/templates/board", json={"language": "en", "markdown": OVERRIDE}
        ).status_code
        == 404
    )
    assert api.client.get("/v1/ai/templates/board").status_code == 404
    assert api.rows == {}


def test_a_member_reads_and_may_not_write(api: Any) -> None:
    api.as_("member")
    assert api.client.get("/v1/ai/templates").status_code == 200
    assert (
        api.client.put(
            "/v1/ai/templates/meeting", json={"language": "en", "markdown": OVERRIDE}
        ).status_code
        == 403
    )
    assert api.client.delete("/v1/ai/templates/meeting").status_code == 403


def test_another_workspace_sees_only_the_built_in(api: Any) -> None:
    api.client.put("/v1/ai/templates/meeting", json={"language": "en", "markdown": OVERRIDE})
    api.as_("tenant_admin", TENANT_B)
    one = api.client.get("/v1/ai/templates/meeting?language=en").json()
    assert one["source"] == "builtin" and one["markdown"] != OVERRIDE
    assert api.client.delete("/v1/ai/templates/meeting?language=en").status_code == 204
    assert (TENANT_A, "meeting", "en") in api.rows  # A's override is untouched
