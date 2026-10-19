"""N1 T7 — /v1/ai/instructions at the route level: real handlers, auth overridden, the DB
stubbed per tenant. Who may read and write, versions, the no-op re-save, the flag, the
preview cap, a failed compile, the budget, tenant isolation, and content hygiene."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from models import ProviderError
from note_service.domain import ai_settings as settings_rules
from note_service.domain import note_instructions_repository as repo

TENANT_A = UUID("22222222-2222-2222-2222-222222222222")
TENANT_B = UUID("33333333-3333-3333-3333-333333333333")
USER = UUID("11111111-1111-1111-1111-111111111111")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "instructions"
BRIEF = (FIXTURES / "executive_brief.txt").read_text("utf-8")
BRIEF_PROFILE = json.loads((FIXTURES / "executive_brief.json").read_text("utf-8"))
INJECT = (FIXTURES / "hostile_inject_fact.txt").read_text("utf-8")
INJECT_PROFILE = json.loads((FIXTURES / "hostile_inject_fact.json").read_text("utf-8"))


def _claims(role: str = "tenant_admin", tenant: UUID = TENANT_A) -> Claims:
    roles = {"tenant_admin": ["tenant_admin", "member"], "guest": ["guest"]}.get(role, [role])
    return Claims(
        sub=USER, tid=tenant, roles=roles, sid="s", iss="https://test/issuer", aud="mdx",
        exp=9_999_999_999, iat=1_700_000_000,
    )  # fmt: skip


@dataclass
class Scripted:
    """The writing model: answers from ``answers`` (a dict, or an exception), counts calls."""

    answers: list[Any] = field(default_factory=list)
    backend: str = "scripted"
    calls: int = 0
    prompts: list[str] = field(default_factory=list)

    async def complete(self, prompt: str, schema: Any = None, **kw: Any) -> Any:
        self.calls += 1
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if self.answers else {}
        if isinstance(answer, BaseException):
            raise answer
        return type("Answer", (), {"text": json.dumps(answer)})()


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import ai_instructions as router_mod

    caplog.set_level(logging.DEBUG)
    audit: list[dict] = []
    rows: dict[tuple[UUID, str], repo.Row] = {}
    jobs: list[dict[str, Any]] = []
    model = Scripted()
    limiter = {"allowed": True}
    budget = {"spent": 0}

    async def _write_event(**kwargs: Any) -> None:
        audit.append(kwargs)

    async def _enqueue(tenant_id: UUID, kind: str, payload: dict, **kw: Any) -> None:
        jobs.append({"tenant_id": tenant_id, "kind": kind, "payload": payload, **kw})

    class _Compiler:
        async def for_workspace(self, workspace_id: str) -> Scripted:
            return model

        async def aclose(self) -> None:
            return None

    class _Limiter:
        async def check(self, *, tenant_id: UUID) -> tuple[bool, int]:
            return (True, 0) if limiter["allowed"] else (False, 1200)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            note_instructions_compiler=_Compiler(),
            note_instructions_rate_limiter=_Limiter(),
            job_queue=SimpleNamespace(enqueue=_enqueue),
        )
    )
    current = {"tenant": TENANT_A}

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        current["tenant"] = tenant_id
        yield None

    async def _fetch(conn: Any, *, tenant_id: UUID, scope: str = "workspace") -> Any:
        # RLS: only the connection's own tenant is visible.
        return rows.get((tenant_id, scope)) if tenant_id == current["tenant"] else None

    async def _fetch_many(conn: Any, *, tenant_id: UUID, scopes: Any) -> dict[str, repo.Row]:
        if tenant_id != current["tenant"]:
            return {}
        return {s: rows[(tenant_id, s)] for s in scopes if (tenant_id, s) in rows}

    async def _mark_stale(conn: Any, *, tenant_id: UUID) -> int:
        n = 0
        for (t, scope), row in list(rows.items()):
            if t == tenant_id and scope != "workspace":
                rows[(t, scope)] = dataclasses.replace(row, compile_status="stale")
                n += 1
        return n

    async def _upsert(conn: Any, **kw: Any) -> repo.Row:
        old = rows.get((kw["tenant_id"], kw["scope"]))
        now = datetime.now(UTC)
        rows[(kw["tenant_id"], kw["scope"])] = repo.Row(
            tenant_id=kw["tenant_id"], scope=kw["scope"],
            version=(old.version + (1 if kw["bump_version"] else 0)) if old else 1,
            text=kw["text"], profile=kw["profile"], profile_hash=kw["profile_hash"],
            compile_status=kw["compile_status"], compile_error_kind=kw["compile_error_kind"],
            compiler_version=kw["compiler_version"], backend=kw["backend"],
            updated_by=kw["updated_by"], created_at=old.created_at if old else now, updated_at=now,
            base_versions=kw.get("base_versions") or {},
        )  # fmt: skip
        return rows[(kw["tenant_id"], kw["scope"])]

    async def _delete(conn: Any, *, tenant_id: UUID, scope: str = "workspace") -> bool:
        return rows.pop((tenant_id, scope), None) is not None

    async def _settings(conn: Any, *, tenant_id: UUID) -> Any:
        return settings_rules.SettingsRow(tenant_id=tenant_id, monthly_budget_cents=1000)

    async def _spent(conn: Any, *, tenant_id: UUID) -> int:
        return budget["spent"]

    async def _plan(conn: Any, tenant_id: UUID) -> Any:
        return "pro", {}

    monkeypatch.setattr(router_mod, "tenant_connection", _conn)
    monkeypatch.setattr(router_mod.repo, "fetch", _fetch)
    monkeypatch.setattr(router_mod.repo, "upsert", _upsert)
    monkeypatch.setattr(router_mod.repo, "delete", _delete)
    monkeypatch.setattr(router_mod.repo, "fetch_many", _fetch_many)
    monkeypatch.setattr(router_mod.repo, "mark_types_stale", _mark_stale)
    monkeypatch.setattr(router_mod.settings_rules, "fetch", _settings)
    monkeypatch.setattr(router_mod.settings_rules, "month_to_date_cents", _spent)
    monkeypatch.setattr(router_mod.ai_settings_router, "_plan", _plan)
    monkeypatch.setattr(router_mod.settings, "note_instructions_enabled", True)

    app = create_app()

    def as_(role: str, tenant: UUID = TENANT_A) -> None:
        app.dependency_overrides[deps.current_user] = lambda: _claims(role, tenant)

    as_("tenant_admin")
    yield SimpleNamespace(
        client=TestClient(app), as_=as_, rows=rows, model=model, audit=audit, jobs=jobs,
        limiter=limiter, budget=budget, router=router_mod, caplog=caplog,
    )  # fmt: skip
    app.dependency_overrides.clear()
    deps.install_state(None)  # type: ignore[arg-type]


def _put(api: Any, text: str, *answers: Any) -> Any:
    api.model.answers.extend(answers)
    return api.client.put("/v1/ai/instructions", json={"text": text})


def test_an_admin_saves_and_a_member_reads(api: Any) -> None:
    created = _put(api, BRIEF, BRIEF_PROFILE)
    assert created.status_code == 201
    body = created.json()
    assert body["version"] == 1 and body["profile"]["length"] == "short"
    assert body["profile"]["summary_sentences"] == 4
    assert body["profile"]["sections_off"] == ["topics", "open_questions"]
    assert "Shorter than standard — about 60 % of the usual length." in body["understood"]
    assert body["not_applied"] == [] and body["can_edit"] is True
    api.as_("member")
    read = api.client.get("/v1/ai/instructions").json()
    assert read["text"] == BRIEF.strip() and read["understood"] == body["understood"]
    assert read["can_edit"] is False


def test_a_member_may_not_write(api: Any) -> None:
    api.as_("member")
    assert api.client.put("/v1/ai/instructions", json={"text": "Short."}).status_code == 403
    assert (
        api.client.post("/v1/ai/instructions/preview", json={"text": "Short."}).status_code == 403
    )
    assert api.client.delete("/v1/ai/instructions").status_code == 403


def test_a_guest_may_not_even_read(api: Any) -> None:
    api.as_("guest")
    assert api.client.get("/v1/ai/instructions").status_code == 403


def test_a_changed_text_is_a_new_version_and_the_same_text_no_model_call(api: Any) -> None:
    assert _put(api, BRIEF, BRIEF_PROFILE).status_code == 201
    second = _put(api, BRIEF + "\nAlso: plain words.", BRIEF_PROFILE)
    assert second.status_code == 200 and second.json()["version"] == 2
    calls = api.model.calls
    again = api.client.put("/v1/ai/instructions", json={"text": BRIEF + "\nAlso: plain words."})
    assert again.status_code == 200 and again.json()["version"] == 2
    assert api.model.calls == calls  # identical text: no model call


def test_an_empty_text_clears_the_instructions(api: Any) -> None:
    _put(api, BRIEF, BRIEF_PROFILE)
    body = api.client.put("/v1/ai/instructions", json={"text": "  \n "}).json()
    assert body["version"] == 0 and body["text"] == "" and api.rows == {}
    assert api.audit[-1]["kind"] == "ai.instructions_cleared"
    assert api.client.delete("/v1/ai/instructions").status_code == 204  # idempotent


def test_a_text_over_the_limit_is_refused_not_cut(api: Any) -> None:
    r = api.client.put("/v1/ai/instructions", json={"text": "x" * 8001})
    assert r.status_code == 413 and r.json()["code"] == "text_too_long"
    assert r.json()["max_chars"] == 8000 and "xxxx" not in r.text
    assert api.rows == {} and api.model.calls == 0


def test_with_the_flag_off_every_route_is_not_available(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api.router.settings, "note_instructions_enabled", False)
    for method, path, body in (
        ("get", "/v1/ai/instructions", None),
        ("put", "/v1/ai/instructions", {"text": "Short."}),
        ("post", "/v1/ai/instructions/preview", {"text": "Short."}),
        ("delete", "/v1/ai/instructions", None),
    ):
        r = getattr(api.client, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 404 and r.json()["code"] == "not_available", path


def test_a_preview_writes_nothing_and_is_capped(api: Any) -> None:
    r = api.client.post("/v1/ai/instructions/preview", json={"text": BRIEF})
    assert r.status_code == 200 and r.json()["version"] == 0 and api.rows == {}
    api.model.answers.append(BRIEF_PROFILE)
    preview = api.client.post("/v1/ai/instructions/preview", json={"text": BRIEF}).json()
    assert preview["profile"]["length"] == "short" and api.rows == {}
    api.limiter["allowed"] = False
    limited = api.client.post("/v1/ai/instructions/preview", json={"text": BRIEF})
    assert limited.status_code == 429 and limited.json()["code"] == "too_many_previews"
    assert limited.headers["Retry-After"] == "1200"


def test_a_failed_compile_is_saved_with_the_empty_profile(api: Any) -> None:
    r = _put(api, BRIEF, ProviderError("unavailable", "down", backend="scripted"))
    assert r.status_code == 201
    body = r.json()
    assert body["compile_status"] == "failed" and body["compile_error_kind"] == "provider_error"
    assert body["understood"] == [] and body["profile"]["length"] == "standard"
    # The text is kept: the admin's work is not lost.
    assert api.rows[(TENANT_A, "workspace")].text == BRIEF.strip()


def test_a_spent_budget_compiles_and_saves_nothing(api: Any) -> None:
    api.budget["spent"] = 1000
    r = _put(api, BRIEF, BRIEF_PROFILE)
    assert r.status_code == 429 and r.json()["code"] == "budget_exceeded"
    assert api.rows == {} and api.model.calls == 0


def test_another_workspace_sees_nothing(api: Any) -> None:
    _put(api, BRIEF, BRIEF_PROFILE)
    api.as_("tenant_admin", TENANT_B)
    body = api.client.get("/v1/ai/instructions").json()
    assert body["version"] == 0 and body["text"] == ""


def test_hostile_text_is_refused_and_adds_nothing(api: Any) -> None:
    body = _put(api, INJECT, INJECT_PROFILE).json()
    assert [r["reason"] for r in body["not_applied"]] == ["adds_content"]
    assert (
        body["not_applied"][0]["message"]
        == "The notes contain only what was said in the recording."
    )
    assert not any("contract" in g.casefold() or "signed" in g.casefold() for g in body["guidance"])


def test_no_text_reaches_logs_or_audit(api: Any) -> None:
    _put(api, BRIEF, BRIEF_PROFILE)
    _put(api, INJECT, INJECT_PROFILE)
    api.client.post("/v1/ai/instructions/preview", json={"text": BRIEF})
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in api.caplog.records)
    audited = json.dumps([e["payload"] for e in api.audit])
    for needle in ("CEO", "Quillhaven", "synergy", "Thirty seconds"):
        assert needle not in logged and needle not in audited, needle
    changed = [e for e in api.audit if e["kind"] == "ai.instructions_changed"]
    assert changed and all(
        set(e["payload"]) == {"scope", "version", "chars", "compile_status", "not_applied", "dials"}
        for e in changed
    )


# ── N4: a text per meeting type ───────────────────────────────────

CLIENT = "Keep topic sections. Use 'Mandant' for the client."
CLIENT_PROFILE = {**BRIEF_PROFILE, "sections_off": ["open_questions"],
                  "terminology": [{"use": "Mandant", "instead_of": "client"}]}  # fmt: skip


def test_a_type_text_is_compiled_after_the_workspace_text(api: Any) -> None:
    _put(api, BRIEF, BRIEF_PROFILE)
    api.model.answers.append(CLIENT_PROFILE)
    body = api.client.put("/v1/ai/instructions/client", json={"text": CLIENT}).json()
    prompt = api.model.prompts[-1]
    assert prompt.index(BRIEF.strip()) < prompt.index("# ---") < prompt.index(CLIENT)
    assert body["scope"] == "client" and body["base_versions"] == {"workspace": 1}
    assert body["extends"] == {"scope": "workspace", "version": 1}
    # The combined readout: the workspace's length, the type's sections.
    assert "Shorter than standard — about 60 % of the usual length." in body["understood"]
    assert "Left out: open questions." in body["understood"]
    workspace = api.client.get("/v1/ai/instructions").json()
    assert [s["scope"] for s in workspace["scopes"]] == ["workspace", "client"]


def test_a_workspace_change_makes_the_types_stale_and_queues_one_recompile(api: Any) -> None:
    _put(api, BRIEF, BRIEF_PROFILE)
    for scope in ("client", "sales"):
        api.model.answers.append(CLIENT_PROFILE)
        api.client.put(f"/v1/ai/instructions/{scope}", json={"text": CLIENT})
    assert api.jobs == []  # nothing to recompile yet: the types were built on v1
    _put(api, BRIEF + "\nNo adjectives.", BRIEF_PROFILE)
    assert api.rows[(TENANT_A, "client")].compile_status == "stale"
    assert api.rows[(TENANT_A, "sales")].compile_status == "stale"
    assert [(j["kind"], j["idempotency_key"]) for j in api.jobs] == [
        ("note.instructions_recompile", "recompile:2")
    ]
    assert api.client.get("/v1/ai/instructions/client").json()["stale"] is True
    _put(api, BRIEF + "\nNo adverbs.", BRIEF_PROFILE)
    assert api.jobs[-1]["idempotency_key"] == "recompile:3"


def test_an_unknown_scope_is_not_found(api: Any) -> None:
    for call in (
        lambda: api.client.get("/v1/ai/instructions/auto"),
        lambda: api.client.put("/v1/ai/instructions/board", json={"text": "x"}),
        lambda: api.client.delete("/v1/ai/instructions/nope"),
    ):
        r = call()
        assert r.status_code == 404 and r.json()["code"] == "scope_unknown"
