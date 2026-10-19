"""The worker writes under the workspace's compiled writing profile (N2 T5)."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from note_models import NoteStatus
from note_service.domain import note_instructions as ni
from note_service.domain import note_instructions_repository as repo
from note_service.jobs import generate_note
from note_service.routers import notes_generation

TENANT = uuid4()
BRIEF = {
    "length": "short",
    "summary_sentences": 4,
    "terminology": [{"use": "PR", "instead_of": "pull request"}],
}


class _StopError(Exception):
    pass


def _row(profile: dict[str, Any], status: str = "compiled") -> repo.Row:
    now = datetime.now(UTC)
    return repo.Row(
        tenant_id=TENANT, scope="workspace", version=3, text="Short notes.", profile=profile,
        profile_hash="h" * 64, compile_status=status, compile_error_kind=None,
        compiler_version="x", backend="mistral_eu", updated_by=uuid4(), created_at=now, updated_at=now,
    )  # fmt: skip


def _install(
    monkeypatch: pytest.MonkeyPatch,
    row: repo.Row | None,
    *,
    others: dict[str, repo.Row] | None = None,
    note_row: Any = None,
    recording_type: str = "meeting",
) -> dict[str, Any]:
    """Stub every step before ``pipeline.run``; the run raises with the kwargs it got."""
    seen: dict[str, Any] = {}

    @contextlib.asynccontextmanager
    async def connection(*_a: Any, **_k: Any) -> Any:
        yield object()

    async def none(*_a: Any, **_k: Any) -> Any:
        return None

    async def fetch_many(*_a: Any, scopes: Any, **_k: Any) -> Any:
        seen["fetched"] = True
        stored = {**({"workspace": row} if row is not None else {}), **(others or {})}
        return {s: stored[s] for s in scopes if s in stored}

    async def fetch_note(*_a: Any, **_k: Any) -> Any:
        seen["fetched"] = True
        return note_row

    async def run(_result: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise _StopError

    g = generate_note
    monkeypatch.setattr(g, "tenant_connection", connection)
    monkeypatch.setattr(g.gen_repo, "fetch", lambda *a, **k: _async(SimpleNamespace(
        snapshot_key="k", config_snapshot={}, requested_by=uuid4())))  # fmt: skip
    monkeypatch.setattr(g.repo, "fetch_note", lambda *a, **k: _async(SimpleNamespace(
        status=NoteStatus.DRAFT, created_at=datetime.now(UTC))))  # fmt: skip
    monkeypatch.setattr(g.gen_repo, "last_written", none)
    monkeypatch.setattr(g.gen_repo, "mark", none)
    monkeypatch.setattr(g, "_role_map", lambda *a, **k: _async(({}, None)))
    monkeypatch.setattr(g, "_carried", lambda *a, **k: _async([]))
    monkeypatch.setattr(g.meetings, "fetch", none)
    monkeypatch.setattr(g.note_instructions_repo, "fetch_many", fetch_many)
    monkeypatch.setattr(g.note_instructions_repo, "fetch_note", fetch_note)
    monkeypatch.setattr(g, "_recording_type", lambda *a, **k: _async((recording_type, "default")))
    monkeypatch.setattr(g, "_store_detected_type", none)
    monkeypatch.setattr(g, "_known_names", lambda *a, **k: _async(([], [])))
    monkeypatch.setattr(g, "_stage_providers", lambda *a, **k: _async(({}, [])))
    monkeypatch.setattr(g.pipeline, "run", run)
    return seen


async def _async(value: Any) -> Any:
    return value


def _generate(enabled: bool) -> None:
    class Store:
        async def get(self, **_k: Any) -> bytes:
            return json.dumps({"language": "en", "segments": []}).encode()

    async def provider_for(_t: str) -> Any:
        return SimpleNamespace(backend="scripted", context_window=None)

    deps = generate_note.GenerationDeps(
        app_pool=object(), transcripts_store=Store(), provider_for=provider_for,
        note_instructions=enabled,
    )  # fmt: skip
    with pytest.raises(_StopError):
        asyncio.run(
            generate_note.handle_generate(
                deps,
                tenant_id=TENANT,
                payload={"generation_id": str(uuid4()), "note_id": str(uuid4())},
            )
        )


def test_a_compiled_row_reaches_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(monkeypatch, _row(BRIEF))
    _generate(enabled=True)
    assert isinstance(seen["profile"], ni.WritingProfile)
    assert seen["profile"].length == "short"


@pytest.mark.parametrize(
    "row",
    [None, _row(BRIEF, status="failed"), _row({"length": "enormous"}), _row({})],
    ids=["absent", "failed", "invalid", "empty"],
)
def test_no_usable_row_is_no_profile(monkeypatch: pytest.MonkeyPatch, row: Any) -> None:
    seen = _install(monkeypatch, row)
    _generate(enabled=True)
    assert seen["profile"] is None


def test_flag_off_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(monkeypatch, _row(BRIEF))
    _generate(enabled=False)
    assert seen["profile"] is None
    assert "fetched" not in seen


def test_stats_carry_the_pointer_and_nothing_else() -> None:
    held = generate_note._Instructions(ni.WritingProfile.model_validate(BRIEF), 3, "h" * 64)
    assert held.ref == {"scope": "workspace", "version": 3, "profile_hash": "h" * 64}
    assert all(not isinstance(v, str) or len(v) <= 64 for v in held.ref.values())


def test_the_view_shows_scope_and_version_only() -> None:
    ref = notes_generation._instructions_ref(
        {"instructions": {"scope": "workspace", "version": 3, "profile_hash": "h"}}
    )
    assert ref is not None and ref.model_dump() == {
        "scope": "workspace",
        "version": 3,
        "fallback": None,
    }
    assert notes_generation._instructions_ref({}) is None


def test_the_done_log_gains_no_long_string() -> None:
    """``instructions_applied`` is numbers and booleans only."""
    import inspect

    source = inspect.getsource(generate_note.handle_generate)
    assert '"instructions_applied": document.stats.get("instructions_applied")' in source
    applied = {"scale": 0.6, "summary_cap": 4, "bullets": [2, 6], "sections_off": 0,
               "topics_skipped": False, "heading_max_words": 8, "terms_replaced": 1, "terms_skipped": 0}  # fmt: skip
    assert all(not isinstance(v, str) for v in applied.values())


# ── N0: the model settings a run used ─────────────────────────────


def test_model_settings_are_capped_by_the_writer_and_recorded_as_a_pointer() -> None:
    from note_service.domain import model_params as mp
    from note_service.domain.ai_settings import SettingsRow

    row = SettingsRow(
        tenant_id=TENANT, writing_style="academic", model_params_version=2,
        model_params={"temperature": 0.4, "context_window_tokens": 65_536, "max_concurrency": 8},
    )  # fmt: skip
    deps = SimpleNamespace(settings_row=lambda _t: row)
    provider = SimpleNamespace(context_window=32_768, max_concurrency=2)
    settings = generate_note.model_settings(deps, TENANT, provider)
    assert settings.params.context_window_tokens == 32_768 and settings.params.max_concurrency == 2
    assert settings.context_window == 32_768 and settings.style == "academic"
    assert settings.ref == {"version": 2, "hash": mp.canonical_hash(settings.params, "academic")}


def test_no_row_is_todays_run() -> None:
    settings = generate_note.model_settings(
        SimpleNamespace(), TENANT, SimpleNamespace(context_window=16_384)
    )
    assert settings.style == "business" and settings.version == 0
    assert settings.params.temperature == 0.0 and settings.context_window == 16_384


def test_an_invalid_stored_object_writes_with_the_defaults() -> None:
    from note_service.domain import model_params as mp
    from note_service.domain.ai_settings import SettingsRow

    row = SettingsRow(tenant_id=TENANT, model_params={"temperature": 9})
    settings = generate_note.model_settings(
        SimpleNamespace(settings_row=lambda _t: row), TENANT, None
    )
    assert settings.params == mp.DEFAULT


def test_the_view_carries_the_settings_version() -> None:
    assert (
        notes_generation._model_settings_version({"model_params": {"version": 3, "hash": "h"}}) == 3
    )
    assert notes_generation._model_settings_version({}) is None


# ── N4: the most specific instructions win ────────────────────────


def _typed(scope: str, profile: dict[str, Any], status: str = "compiled") -> repo.Row:
    return dataclasses.replace(_row(profile, status), scope=scope, version=1)


def test_the_notes_own_instructions_win(monkeypatch: pytest.MonkeyPatch) -> None:
    note_row = SimpleNamespace(
        compile_status="compiled", profile={"length": "long"}, profile_hash="n" * 64
    )
    seen = _install(monkeypatch, _row(BRIEF), note_row=note_row)
    _generate(enabled=True)
    assert seen["profile"].length == "long"


def test_a_compiled_type_text_is_used_for_its_family(monkeypatch: pytest.MonkeyPatch) -> None:
    from note_service.domain.meeting_doc import types

    client_type = next(t for t, f in types._FAMILY_OF_RECORDING.items() if f == "client")
    seen = _install(monkeypatch, _row(BRIEF), others={"client": _typed("client", {"length": "long"})},
                    recording_type=client_type)  # fmt: skip
    _generate(enabled=True)
    assert seen["profile"].length == "long"


def test_a_stale_type_text_never_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from note_service.domain.meeting_doc import types

    client_type = next(t for t, f in types._FAMILY_OF_RECORDING.items() if f == "client")
    stale = _typed("client", {"length": "long"}, status="stale")
    seen = _install(monkeypatch, _row(BRIEF), others={"client": stale}, recording_type=client_type)
    _generate(enabled=True)
    assert seen["profile"].length == "short"  # the workspace's


def test_the_run_records_scope_and_fallback() -> None:
    held = generate_note._Instructions(ni.EMPTY, 3, "h" * 64, scope="workspace", fallback="stale")
    assert held.ref == {
        "scope": "workspace",
        "version": 3,
        "profile_hash": "h" * 64,
        "fallback": "stale",
    }
    assert notes_generation._instructions_ref(
        {"instructions": {"scope": "client", "version": 1, "profile_hash": "h"}}
    ).model_dump() == {"scope": "client", "version": 1, "fallback": None}
