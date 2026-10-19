"""The recompile job (N4): every stale type row compiled with the current workspace text."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from note_service.domain import note_instructions_repository as repo
from note_service.jobs import recompile_instructions as job

TENANT = UUID("22222222-2222-2222-2222-222222222222")


def _row(scope: str, text: str, version: int, status: str, bases: dict[str, int]) -> repo.Row:
    now = datetime.now(UTC)
    return repo.Row(
        tenant_id=TENANT, scope=scope, version=version, text=text, profile={}, profile_hash="h",
        compile_status=status, compile_error_kind=None, compiler_version="x", backend="b",
        updated_by=TENANT, created_at=now, updated_at=now, base_versions=bases,
    )  # fmt: skip


class _Model:
    backend = "scripted"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, prompt: str, schema: Any = None, **_: Any) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text=json.dumps({"length": "short"}))


def test_every_stale_type_row_is_compiled_on_the_new_workspace_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = {
        "workspace": _row("workspace", "Short notes.", 4, "compiled", {}),
        "client": _row("client", "Keep topics.", 2, "stale", {"workspace": 3}),
        "sales": _row("sales", "Prices first.", 1, "stale", {"workspace": 3}),
        "team": _row("team", "Short headings.", 1, "compiled", {"workspace": 4}),
    }

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        yield None

    async def _fetch_many(conn: Any, *, tenant_id: UUID, scopes: Any) -> dict[str, repo.Row]:
        return {s: rows[s] for s in scopes if s in rows}

    async def _set_compiled(conn: Any, *, scope: str, **kw: Any) -> repo.Row:
        rows[scope] = dataclasses.replace(
            rows[scope], compile_status=kw["compile_status"], base_versions=kw["base_versions"]
        )
        return rows[scope]

    monkeypatch.setattr(job, "tenant_connection", _conn)
    monkeypatch.setattr(job.repo, "fetch_many", _fetch_many)
    monkeypatch.setattr(job.repo, "set_compiled", _set_compiled)
    model = _Model()

    async def _compiler_for(tenant_id: UUID) -> _Model:
        return model

    deps = SimpleNamespace(app_pool=object(), compiler_for=_compiler_for)
    out = asyncio.run(job.handle_recompile(deps, tenant_id=TENANT, payload={"scope": "*"}))
    assert out["recompiled"] == 2 and out["failed"] == 0
    for scope in ("client", "sales", "team"):
        assert rows[scope].compile_status == "compiled"
        assert rows[scope].base_versions == {"workspace": 4}
    # Each compile reads the workspace text first, then the type's.
    assert all(p.index("Short notes.") < p.index("# ---") for p in model.prompts)
    assert len(model.prompts) == 2  # the fresh row is left alone


def test_nothing_stale_is_no_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        yield None

    async def _fetch_many(conn: Any, **_: Any) -> dict[str, repo.Row]:
        return {}

    monkeypatch.setattr(job, "tenant_connection", _conn)
    monkeypatch.setattr(job.repo, "fetch_many", _fetch_many)

    async def _never(tenant_id: UUID) -> Any:
        raise AssertionError("no compile without a stale row")

    deps = SimpleNamespace(app_pool=object(), compiler_for=_never)
    assert asyncio.run(job.handle_recompile(deps, tenant_id=TENANT, payload={})) == {
        "recompiled": 0,
        "failed": 0,
    }
