"""Sprint L2 — Mistral (EU API) is the dev default, the local model the fallback.

The registry decides at load (missing key, forced switch); `probe_chat`
decides once more at startup (the API does not answer). Dev falls back and
says why; staging refuses to boot. The AI-settings page reads the same
object, so what it says is what the worker does.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from models import ConfigError, ErrorKind, ProviderError, Registry
from note_service.domain import model_routing
from note_service.domain.meeting_doc import pipeline, windows
from note_service.jobs import generate_note

MISTRAL = {
    "kind": "openai_compat",
    "base_url": "${MISTRAL_API_URL:-https://api.mistral.ai/v1}",
    "auth": "bearer:${MISTRAL_API_KEY}",
    "enabled_in_envs": ["dev", "staging", "prod"],
    "models": {"chat": "${MISTRAL_LARGE_PIN:-mistral-large-2512}"},
    "structured_output": "probe",
    "context_window": 131072,
    "processor": {"name": "Mistral AI", "region": "EU"},
}
LOCAL = {
    "kind": "openai_compat",
    "base_url": "http://localhost:11434/v1",
    "auth": "none",
    "enabled_in_envs": ["dev", "test"],
    "models": {"chat": "notes-chat"},
    "context_window": 16384,
    "small_model": True,
    "processor": {"name": "Developer machine", "region": "local"},
}
HF = {
    "kind": "openai_compat",
    "base_url": "${HF_CHAT_ENDPOINT_URL}",
    "auth": "bearer:${HF_TOKEN}",
    "enabled_in_envs": ["staging", "prod"],
    "models": {"chat": "${HF_CHAT_MODEL_PIN}"},
    "processor": {"name": "Hugging Face Inference Endpoints", "region": "EU"},
}
STAGING_ENV = {
    "HF_CHAT_ENDPOINT_URL": "https://x/v1",
    "HF_TOKEN": "t",
    "HF_CHAT_MODEL_PIN": "m",
    "MISTRAL_API_KEY": "k",
}


def _config(env_dev: dict[str, Any] | None = None) -> dict[str, Any]:
    small = {**MISTRAL, "models": {"chat": "${MISTRAL_SMALL_PIN:-mistral-small-2603}"}}
    return {
        "version": 1,
        "backends": {
            "mistral_eu": dict(MISTRAL),
            "mistral_eu_small": small,
            "dev_mac": dict(LOCAL),
            "hf_eu": dict(HF),
        },
        "routing": {
            op: {"standard": "hf_eu", "premium": "hf_eu"}
            for op in ("understand", "summarize", "classify", "title", "entities")
        },
        "env_overrides": {
            "dev": env_dev
            or {
                "chat": {"primary": "mistral_eu", "fallback": "dev_mac"},
                "classify": {"primary": "mistral_eu_small", "fallback": "dev_mac"},
                "title": {"primary": "mistral_eu_small", "fallback": "dev_mac"},
                "entities": {"primary": "mistral_eu_small", "fallback": "dev_mac"},
            },
            "staging": {"chat": {"primary": "mistral_eu", "fallback": "hf_eu"}},
        },
    }


def _registry(env: str = "dev", environ: dict[str, str] | None = None) -> Registry:
    return Registry.load(_config(), env=env, environ=environ or {}, validate=False)


def _probe_answers(monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, bool]) -> list[str]:
    """Make `probe_chat` see a backend answer (True) or fail (False)."""
    probed: list[str] = []

    async def fake(registry: Registry, backend: str, timeout_s: float) -> bool:
        probed.append(backend)
        return outcomes.get(backend, True)

    monkeypatch.setattr(model_routing, "_answers", fake)
    return probed


# ── startup probe ────────────────────────────────────────────────────


def test_with_the_key_and_an_answering_api_the_primary_writes(monkeypatch) -> None:  # noqa: ANN001
    probed = _probe_answers(monkeypatch, {"mistral_eu": True})
    registry = _registry(environ={"MISTRAL_API_KEY": "k"})
    active = asyncio.run(model_routing.probe_chat(registry))
    assert probed == ["mistral_eu"]
    assert active is not None and active.name == "mistral_eu" and active.reason is None
    assert registry.resolve("ws", "summarize").name == "mistral_eu"
    assert registry.resolve("ws", "title").name == "mistral_eu_small"


def test_an_api_that_does_not_answer_in_dev_falls_back_for_the_process(monkeypatch) -> None:  # noqa: ANN001
    _probe_answers(monkeypatch, {"mistral_eu": False})
    registry = _registry(environ={"MISTRAL_API_KEY": "k"})
    active = asyncio.run(model_routing.probe_chat(registry))
    assert active is not None and active.name == "dev_mac" and active.reason == "probe_failed"
    # The short operations follow the writer to the local model.
    for op in ("summarize", "classify", "title", "entities"):
        assert registry.resolve("ws", op).name == "dev_mac"
    # The page reads the same decision.
    described = model_routing.describe(registry)
    assert described is not None
    assert described["backend"] == "dev_mac" and described["reason"] == "probe_failed"
    assert described["processor"] == "Developer machine" and described["primary"] == "mistral_eu"
    assert described["small"]["backend"] == "dev_mac"
    assert "http" not in str(described) and described.get("model_id") != "k"


def test_without_the_key_the_fallback_is_probed_and_kept_even_when_silent(monkeypatch) -> None:  # noqa: ANN001
    probed = _probe_answers(monkeypatch, {"dev_mac": False})
    registry = _registry(environ={})
    active = asyncio.run(model_routing.probe_chat(registry))
    assert probed == ["dev_mac"]
    assert active is not None and active.name == "dev_mac" and active.reason == "missing_env"


def test_on_staging_a_failed_probe_refuses_to_boot(monkeypatch) -> None:  # noqa: ANN001
    _probe_answers(monkeypatch, {"mistral_eu": False})
    registry = _registry(env="staging", environ=STAGING_ENV)
    with pytest.raises(ConfigError) as exc:
        asyncio.run(model_routing.probe_chat(registry))
    assert exc.value.code == "probe_failed"
    assert registry.resolve("ws", "summarize").name == "mistral_eu"  # nothing switched


def test_the_real_probe_absorbs_provider_errors_and_timeouts(monkeypatch) -> None:  # noqa: ANN001
    class Slow:
        async def probe(self) -> None:
            await asyncio.sleep(10)

        async def aclose(self) -> None:
            return None

    class Broken:
        async def probe(self) -> None:
            raise ProviderError(ErrorKind.UNAVAILABLE, "connection refused", backend="x")

        async def aclose(self) -> None:
            return None

    registry = _registry(environ={"MISTRAL_API_KEY": "k"})
    monkeypatch.setattr(model_routing, "build_chat_provider", lambda resolved: Slow())
    assert asyncio.run(model_routing._answers(registry, "mistral_eu", 0.01)) is False
    monkeypatch.setattr(model_routing, "build_chat_provider", lambda resolved: Broken())
    assert asyncio.run(model_routing._answers(registry, "mistral_eu", 1.0)) is False


def test_the_dev_switch_names_every_chat_operation(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(model_routing.settings, "dev_chat_backend", "dev_mac")
    assert model_routing.forced_overrides() == {
        "chat": "dev_mac",
        "classify": "dev_mac",
        "title": "dev_mac",
        "entities": "dev_mac",
    }
    monkeypatch.setattr(model_routing.settings, "dev_chat_backend", "")
    assert model_routing.forced_overrides() == {}


# ── the generation's side calls go to their own backend ─────────────


def test_side_calls_use_their_routed_provider_and_fall_back_to_the_writer() -> None:
    calls: list[tuple[str, str]] = []

    async def by_operation(workspace_id: str, operation: str) -> str:
        calls.append((workspace_id, operation))
        if operation == "entities":
            raise ConfigError("unknown_backend", "no such backend")
        return f"provider:{operation}"

    deps = generate_note.GenerationDeps(
        app_pool=None,
        transcripts_store=None,
        provider_for=None,
        operation_provider_for=by_operation,
    )
    tenant = __import__("uuid").UUID(int=7)
    assert asyncio.run(generate_note._operation_provider(deps, tenant, "classify", "writer")) == (
        "provider:classify"
    )
    assert asyncio.run(generate_note._operation_provider(deps, tenant, "entities", "writer")) == (
        "writer"
    )
    plain = generate_note.GenerationDeps(app_pool=None, transcripts_store=None, provider_for=None)
    assert asyncio.run(generate_note._operation_provider(plain, tenant, "title", "writer")) == (
        "writer"
    )
    assert calls == [(str(tenant), "classify"), (str(tenant), "entities")]


# ── T5: the engine's sizes follow the context ───────────────────────


def test_sizes_keep_todays_values_up_to_32k_and_grow_on_128k() -> None:
    class Ctx:
        def __init__(self, n: int) -> None:
            self.context_window = n

    small = pipeline.sizes_for(Ctx(16_384))
    today = pipeline.sizes_for(Ctx(32_768))
    large = pipeline.sizes_for(Ctx(131_072))
    for s in (small, today):
        assert s.window_chars == windows.MAX_WINDOW_CHARS == 6_000
        assert s.extract_max_tokens == pipeline.EXTRACT_MAX_TOKENS
        assert s.reduce_max_tokens == pipeline.REDUCE_MAX_TOKENS
        assert s.max_facts_budget == pipeline.MAX_FACTS_BUDGET
    assert large.window_chars == windows.LARGE_WINDOW_CHARS == 16_000
    assert large.max_facts_budget == 64 and large.extract_max_tokens == 8_000
    assert large.reduce_max_tokens > pipeline.REDUCE_MAX_TOKENS
    # A provider without the attribute is today's 32K.
    assert pipeline.sizes_for(object()).window_chars == 6_000
    assert windows.window_chars(None) == 6_000 and windows.window_chars(131_072) == 16_000


def test_a_long_context_provider_gets_larger_windows_and_budgets() -> None:
    from .meeting_doc_fakes import ScriptedProvider, as_result

    class Wide(ScriptedProvider):
        context_window = 131_072

    meeting = {
        "language": "de",
        "transcript": [
            {
                "speaker": ("SPEAKER_1", "SPEAKER_2")[n % 2],
                "t_start_ms": n * 20_000,
                "t_end_ms": n * 20_000 + 19_000,
                "text": f"Im Jahr {2000 + n} traf Peter Thiel in Kalifornien genau {n + 3} "
                "Investoren aus dem Silicon Valley und sprach lange über Daten",
            }
            for n in range(60)
        ],
    }
    wide, narrow = Wide(), ScriptedProvider()
    doc_wide = asyncio.run(
        pipeline.run(as_result(meeting), provider=wide, role_by_key={}, language="de")
    )
    doc_narrow = asyncio.run(
        pipeline.run(as_result(meeting), provider=narrow, role_by_key={}, language="de")
    )
    assert doc_wide.stats["window_chars"] == 16_000 and doc_wide.stats["context_window"] == 131_072
    assert doc_narrow.stats["window_chars"] == 6_000
    assert doc_wide.windows_total < doc_narrow.windows_total
    schemas_wide = [s for s in wide.schemas if s and "facts" in s["properties"]]
    assert all(s["properties"]["facts"]["maxItems"] <= 64 for s in schemas_wide)
    assert any(
        s["properties"]["facts"]["maxItems"] > pipeline.MAX_FACTS_BUDGET for s in schemas_wide
    )


# ── the AI-settings page reads the same object ──────────────────────


def test_the_settings_view_says_who_writes_and_why(monkeypatch) -> None:  # noqa: ANN001
    from note_service.routers import ai_settings as router_mod

    registry = _registry(environ={})  # no key: the local model, missing_env
    monkeypatch.setattr(router_mod, "_registry", lambda: registry)
    writer, small = router_mod._writers()
    assert writer is not None and small is not None
    assert writer.backend == "dev_mac" and writer.reason == "missing_env"
    assert writer.primary == "mistral_eu" and writer.fallback == "dev_mac"
    assert writer.processor == "Developer machine" and writer.region == "local"
    assert small.backend == "dev_mac" and small.primary == "mistral_eu_small"

    with_key = _registry(environ={"MISTRAL_API_KEY": "k"})
    monkeypatch.setattr(router_mod, "_registry", lambda: with_key)
    writer, small = router_mod._writers()
    assert writer is not None and writer.backend == "mistral_eu" and writer.reason is None
    assert writer.processor == "Mistral AI" and writer.model_id == "mistral-large-2512"
    assert small is not None and small.model_id == "mistral-small-2603"
    # Names only — never the key or a URL.
    assert "k" not in (writer.model_id or "").split("-") and "http" not in str(writer)


# ── T3: a processor nobody agreed to blocks the run before a byte leaves ──


def test_an_unacknowledged_processor_blocks_generation_with_the_code(monkeypatch) -> None:  # noqa: ANN001
    from uuid import UUID

    from note_service.domain import ai_settings as rules
    from note_service.domain import generation_service

    tenant = UUID(int=9)
    required = rules.required_processors(_registry(environ={"MISTRAL_API_KEY": "k"}))
    assert {p.name for p in required} == {"Mistral AI"}
    mistral = next(p for p in required if p.name == "Mistral AI")
    assert "writing your meeting notes" in mistral.purposes
    assert "naming your notes" in mistral.purposes

    rows = {"row": rules.SettingsRow(tenant_id=tenant)}

    async def fetch(conn, *, tenant_id):  # noqa: ANN001, ANN202
        return rows["row"]

    monkeypatch.setattr(generation_service.ai_settings, "fetch", fetch)
    with pytest.raises(generation_service.ProcessorUnacknowledgedError) as exc:
        asyncio.run(
            generation_service.check_allowed(None, tenant_id=tenant, required_processors=required)
        )
    assert [(p.name, p.region) for p in exc.value.processors] == [("Mistral AI", "EU")]

    # The seeded dev workspace has agreed: the gate passes on to the budget
    # check, which needs the database — reaching it is the assertion.
    rows["row"] = rules.SettingsRow(
        tenant_id=tenant, acknowledged=[{"name": "mistral ai", "region": "eu"}]
    )

    class _Conn:
        async def fetchrow(self, *a: Any) -> None:
            raise RuntimeError("budget check reached")

    with pytest.raises(RuntimeError, match="budget check reached"):
        asyncio.run(
            generation_service.check_allowed(
                _Conn(), tenant_id=tenant, required_processors=required
            )
        )
    # No list at all (a deployment without a registry) never blocks.
    with pytest.raises(RuntimeError, match="budget check reached"):
        asyncio.run(generation_service.check_allowed(_Conn(), tenant_id=tenant))


def test_the_seed_acknowledges_exactly_the_processors_dev_routes_to() -> None:
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("seed", repo / "scripts" / "seed" / "seed.py")
    seed = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(seed)
    seeded = {(p["name"], p["region"]) for p in seed._dev_processors()}
    registry = Registry.load(
        repo / "config" / "models.yaml", env="dev", environ={"MISTRAL_API_KEY": "x"}, validate=False
    )
    assert seeded == {(p.name, p.region) for p in registry.processors_for_env()}
    assert ("Mistral AI", "EU") in seeded and ("Developer machine", "local") in seeded
