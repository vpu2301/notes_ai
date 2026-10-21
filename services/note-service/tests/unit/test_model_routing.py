"""Mistral (EU API) is the dev default, the local model the fallback: the registry
decides at load, `probe_chat` once more at startup; dev falls back, staging refuses to boot.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from models import ConfigError, ErrorKind, ProviderError, Registry
from note_service.domain import model_routing

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
        "routing": {op: {"standard": "hf_eu", "premium": "hf_eu"} for op in ("write", "ask")},
        "env_overrides": {
            "dev": env_dev or {"chat": {"primary": "mistral_eu", "fallback": "dev_mac"}},
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
    assert registry.resolve("ws", "write").name == "mistral_eu"
    assert registry.resolve("ws", "ask").name == "mistral_eu"


def test_an_api_that_does_not_answer_in_dev_falls_back_for_the_process(monkeypatch) -> None:  # noqa: ANN001
    _probe_answers(monkeypatch, {"mistral_eu": False})
    registry = _registry(environ={"MISTRAL_API_KEY": "k"})
    active = asyncio.run(model_routing.probe_chat(registry))
    assert active is not None and active.name == "dev_mac" and active.reason == "probe_failed"
    for op in ("write", "ask"):
        assert registry.resolve("ws", op).name == "dev_mac"
    # The page reads the same decision.
    described = model_routing.describe(registry)
    assert described is not None
    assert described["backend"] == "dev_mac" and described["reason"] == "probe_failed"
    assert described["processor"] == "Developer machine" and described["primary"] == "mistral_eu"
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
    assert registry.resolve("ws", "write").name == "mistral_eu"  # nothing switched


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


def test_the_dev_switch_names_the_chat_backend(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(model_routing.settings, "dev_chat_backend", "dev_mac")
    assert model_routing.forced_overrides() == {"chat": "dev_mac"}
    monkeypatch.setattr(model_routing.settings, "dev_chat_backend", "")
    assert model_routing.forced_overrides() == {}
