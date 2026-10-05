from __future__ import annotations

import logging

import pytest

from models import ConfigError, Registry, WorkspaceModelSettings

from .conftest_helpers import STAGING_ENV, base_config

WS = "0192a1b2-0000-7000-8000-000000000001"


def _registry(env: str, environ: dict[str, str] | None = None, **kw: object) -> Registry:
    return Registry.load(base_config(), env=env, environ=environ or {}, **kw)  # type: ignore[arg-type]


# ── resolve matrix: provider × tier × env × enabled ─────────────────────
MATRIX: list[tuple[str, str, str, str, dict[str, str], str]] = [
    # env, provider, tier, operation, environ, expected backend
    ("dev", "platform", "standard", "understand", {}, "dev_mac"),
    ("dev", "platform", "premium", "understand", {}, "dev_mac"),
    ("dev", "platform", "standard", "summarize", {}, "dev_mac"),
    ("dev", "platform", "standard", "asr", {}, "dev_mac_asr"),
    ("test", "platform", "standard", "understand", {}, "recorded"),
    ("test", "platform", "premium", "asr", {}, "inproc_cpu_asr"),
    ("staging", "platform", "standard", "understand", STAGING_ENV, "hf_eu"),
    ("staging", "platform", "premium", "understand", STAGING_ENV, "hf_eu"),
    ("staging", "platform", "standard", "asr", STAGING_ENV, "hf_eu_asr"),
    ("prod", "platform", "standard", "summarize", STAGING_ENV, "hf_eu"),
    ("prod", "platform", "premium", "asr", STAGING_ENV, "hf_eu_asr"),
]


@pytest.mark.parametrize(("env", "provider", "tier", "operation", "environ", "expected"), MATRIX)
def test_resolve_matrix(
    env: str, provider: str, tier: str, operation: str, environ: dict[str, str], expected: str
) -> None:
    reg = _registry(
        env,
        environ,
        settings_source=lambda _ws: WorkspaceModelSettings(provider=provider, tier=tier),
    )  # type: ignore[arg-type]
    resolved = reg.resolve(WS, operation)
    assert resolved.name == expected
    assert resolved.model_id
    assert resolved.processor is not None or resolved.kind in ("asr_inproc", "recorded")


def test_premium_flips_to_hosted_eu_by_config_only() -> None:
    cfg = base_config()
    cfg["backends"]["hosted_eu"]["enabled"] = True
    cfg["routing"]["understand"]["premium"] = "hosted_eu"
    environ = {
        **STAGING_ENV,
        "HOSTED_MODEL_URL": "https://gpu.internal/v1",
        "HOSTED_MODEL_TOKEN": "t",
        "HOSTED_CHAT_MODEL_PIN": "Qwen/Qwen3-8B",
    }
    reg = Registry.load(
        cfg,
        env="prod",
        environ=environ,
        settings_source=lambda _ws: WorkspaceModelSettings(tier="premium"),
    )
    resolved = reg.resolve(WS, "understand")
    assert resolved.name == "hosted_eu"
    assert resolved.caps.structured_output == "guided_json"
    assert resolved.processor is not None and resolved.processor.name == "Notes AI (own EU host)"
    # standard stays on hf_eu
    assert Registry.load(cfg, env="prod", environ=environ).resolve(WS, "understand").name == "hf_eu"


def test_hosted_eu_disabled_is_refused_even_if_routed() -> None:
    cfg = base_config()
    cfg["routing"]["understand"]["premium"] = "hosted_eu"
    with pytest.raises(ConfigError) as exc:
        Registry.load(cfg, env="staging", environ=STAGING_ENV)
    assert exc.value.code == "backend_disabled"


# ── env guard ───────────────────────────────────────────────────────────
def test_dev_mac_referenced_on_staging_is_refused_at_startup() -> None:
    cfg = base_config()
    cfg["env_overrides"]["staging"] = {"chat": "dev_mac"}
    with pytest.raises(ConfigError) as exc:
        Registry.load(cfg, env="staging", environ=STAGING_ENV)
    assert exc.value.code == "backend_not_allowed_in_env"
    assert "dev_mac" in str(exc.value)


def test_dev_mac_direct_lookup_on_prod_is_refused() -> None:
    reg = _registry("prod", STAGING_ENV)
    with pytest.raises(ConfigError) as exc:
        reg.backend("dev_mac")
    assert exc.value.code == "backend_not_allowed_in_env"


def test_dev_mac_cannot_be_routed_on_prod_even_by_widening_enabled_in_envs() -> None:
    cfg = base_config()
    cfg["backends"]["dev_mac"]["enabled_in_envs"] = ["dev", "prod"]
    cfg["routing"]["understand"]["standard"] = "dev_mac"
    with pytest.raises(ConfigError) as exc:
        Registry.load(cfg, env="prod", environ=STAGING_ENV)
    assert exc.value.code == "backend_not_allowed_in_env"


# ── startup validation ──────────────────────────────────────────────────
def test_missing_env_for_reachable_backend_fails_at_load() -> None:
    with pytest.raises(ConfigError) as exc:
        _registry("staging", {})
    assert exc.value.code == "missing_env"
    assert "HF_CHAT_ENDPOINT_URL" in str(exc.value)


def test_missing_env_for_unreachable_backend_is_fine_in_dev() -> None:
    reg = _registry("dev", {})
    assert reg.resolve(WS, "understand").name == "dev_mac"


def test_unknown_env_is_refused() -> None:
    with pytest.raises(ConfigError) as exc:
        _registry("production")
    assert exc.value.code == "unknown_env"


def test_unknown_operation_at_resolve() -> None:
    reg = _registry("dev")
    with pytest.raises(ConfigError) as exc:
        reg.resolve(WS, "translate")
    assert exc.value.code == "unknown_operation"


def test_anthropic_provider_setting_is_not_configured_yet() -> None:
    reg = _registry("dev", settings_source=lambda _ws: WorkspaceModelSettings(provider="anthropic"))
    with pytest.raises(ConfigError) as exc:
        reg.resolve(WS, "understand")
    assert exc.value.code in ("provider_not_configured", "backend_disabled")


def test_custom_provider_setting_lands_in_s7() -> None:
    reg = _registry("dev", settings_source=lambda _ws: WorkspaceModelSettings(provider="custom"))
    with pytest.raises(ConfigError) as exc:
        reg.resolve(WS, "understand")
    assert exc.value.code == "provider_not_configured"


def test_processors_for_env_feed_the_data_page() -> None:
    names = {p.name for p in _registry("staging", STAGING_ENV).processors_for_env()}
    assert names == {"Hugging Face Inference Endpoints"}
    assert {p.name for p in _registry("dev").processors_for_env()} == {"Developer machine"}


def test_route_log_has_no_url_or_token(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="models.registry"):
        _registry("staging", STAGING_ENV)
    blob = "\n".join(
        f"{r.getMessage()} {getattr(r, 'backend', '')} {r.__dict__}" for r in caplog.records
    )
    assert "hf_secret_token" not in blob
    assert "endpoints.huggingface.cloud" not in blob


def test_small_model_reaches_the_resolved_backend_and_the_provider() -> None:
    """Sprint L1 T2: the flag travels config → Capabilities → provider."""
    from models import build_chat_provider

    cfg = base_config()
    cfg["backends"]["dev_mac"]["small_model"] = True
    cfg["backends"]["dev_mac"]["request_overrides"] = {"reasoning_effort": "${UNSET_L1:-}"}
    reg = Registry.load(cfg, env="dev", environ={})  # type: ignore[arg-type]
    resolved = reg.backend("dev_mac", expect_kind="chat")
    assert resolved.caps.small_model is True
    provider = build_chat_provider(resolved)
    assert provider.small_model is True
    # An override that interpolated to nothing is not sent to the server.
    assert provider.request_overrides == {}  # type: ignore[attr-defined]
    test_env = Registry.load(cfg, env="test", environ={})  # type: ignore[arg-type]
    assert test_env.backend("recorded", expect_kind="chat").caps.small_model is False


# ── Sprint L2: default with fallback (dev only), operation routing ──────

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
MISTRAL_ENV = {"MISTRAL_API_KEY": "sk-test"}


def _l2_config(**env_dev: object) -> dict:
    cfg = base_config()
    cfg["backends"]["mistral_eu"] = dict(MISTRAL)
    cfg["backends"]["mistral_eu_small"] = {
        **MISTRAL,
        "models": {"chat": "${MISTRAL_SMALL_PIN:-mistral-small-2603}"},
    }
    for op in ("classify", "title", "entities"):
        cfg["routing"][op] = {"standard": "hf_eu", "premium": "hf_eu"}
    cfg["env_overrides"]["dev"] = {
        "chat": {"primary": "mistral_eu", "fallback": "dev_mac"},
        "classify": {"primary": "mistral_eu_small", "fallback": "dev_mac"},
        "title": {"primary": "mistral_eu_small", "fallback": "dev_mac"},
        "entities": {"primary": "mistral_eu_small", "fallback": "dev_mac"},
        "asr": "dev_mac_asr",
        **env_dev,
    }
    return cfg


def test_key_present_routes_writing_to_the_large_and_short_calls_to_the_small_model() -> None:
    reg = Registry.load(_l2_config(), env="dev", environ=MISTRAL_ENV)  # type: ignore[arg-type]
    assert reg.resolve(WS, "summarize").name == "mistral_eu"
    assert reg.resolve(WS, "understand").name == "mistral_eu"
    assert reg.resolve(WS, "summarize").model_id == "mistral-large-2512"
    for op in ("classify", "title", "entities"):
        assert reg.resolve(WS, op).name == "mistral_eu_small"
        assert reg.resolve(WS, op).model_id == "mistral-small-2603"
    active = reg.active_override("chat")
    assert active is not None and active.name == "mistral_eu" and active.reason is None
    # Both companies the dev workspace has to acknowledge — computed, not typed.
    assert {p.name for p in reg.processors_for_env()} == {"Mistral AI", "Developer machine"}


def test_key_absent_falls_back_to_the_local_model_with_missing_env(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="models.registry"):
        reg = Registry.load(_l2_config(), env="dev", environ={})  # type: ignore[arg-type]
    assert reg.resolve(WS, "summarize").name == "dev_mac"
    assert reg.resolve(WS, "title").name == "dev_mac"
    active = reg.active_override("chat")
    assert active is not None and active.is_fallback and active.reason == "missing_env"
    assert active.primary == "mistral_eu" and active.fallback == "dev_mac"
    records = [r for r in caplog.records if r.getMessage() == "models.override_fallback"]
    assert records and records[0].reason == "missing_env"  # type: ignore[attr-defined]
    # Log-safe: no URL, no key in the record.
    assert "sk-" not in str(records[0].__dict__) and "http" not in str(records[0].__dict__)


def test_mdx_dev_chat_backend_forces_the_named_backend() -> None:
    reg = Registry.load(
        _l2_config(),
        env="dev",
        environ=MISTRAL_ENV,
        forced={
            "chat": "dev_mac",
            "classify": "dev_mac",
            "title": "dev_mac",
            "entities": "dev_mac",
        },
    )  # type: ignore[arg-type]
    assert reg.resolve(WS, "summarize").name == "dev_mac"
    assert reg.resolve(WS, "classify").name == "dev_mac"
    active = reg.active_override("chat")
    assert active is not None and active.reason == "forced" and active.name == "dev_mac"
    # Forcing the primary itself is not a fallback.
    same = Registry.load(
        _l2_config(), env="dev", environ=MISTRAL_ENV, forced={"chat": "mistral_eu"}
    )  # type: ignore[arg-type]
    assert same.active_override("chat").reason is None  # type: ignore[union-attr]


def test_a_failed_probe_falls_back_in_dev_and_refuses_on_staging() -> None:
    reg = Registry.load(_l2_config(), env="dev", environ=MISTRAL_ENV)  # type: ignore[arg-type]
    assert reg.resolve(WS, "summarize").name == "mistral_eu"
    switched = reg.fall_back("chat")
    assert switched.name == "dev_mac" and switched.reason == "probe_failed"
    assert reg.resolve(WS, "summarize").name == "dev_mac"
    assert reg.fall_back("chat").name == "dev_mac"  # idempotent
    # asr has no fallback configured.
    with pytest.raises(ConfigError) as exc:
        reg.fall_back("asr")
    assert exc.value.code == "fallback_not_configured"

    cfg = _l2_config()
    cfg["env_overrides"]["staging"] = {"chat": {"primary": "mistral_eu", "fallback": "hf_eu"}}
    staging = Registry.load(cfg, env="staging", environ={**STAGING_ENV, **MISTRAL_ENV})  # type: ignore[arg-type]
    with pytest.raises(ConfigError) as exc:
        staging.fall_back("chat")
    assert exc.value.code == "fallback_not_allowed"


def test_on_staging_a_missing_primary_key_refuses_to_boot_as_before() -> None:
    cfg = _l2_config()
    cfg["env_overrides"]["staging"] = {"chat": {"primary": "mistral_eu", "fallback": "hf_eu"}}
    with pytest.raises(ConfigError) as exc:
        Registry.load(cfg, env="staging", environ=STAGING_ENV)  # type: ignore[arg-type]
    assert exc.value.code == "missing_env"


def test_the_bare_name_form_still_parses_and_routes() -> None:
    reg = _registry("dev", {})
    assert reg.resolve(WS, "summarize").name == "dev_mac"
    active = reg.active_override("chat")
    assert active is not None and active.name == "dev_mac" and active.reason is None
    assert reg.override_for("asr") == "dev_mac_asr"


def test_the_repo_config_routes_dev_to_mistral_with_the_key_and_to_the_mac_without() -> None:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[4]
    path = repo / "config" / "models.yaml"
    with_key = Registry.load(path, env="dev", environ=MISTRAL_ENV, validate=False)
    assert with_key.resolve(WS, "summarize").name == "mistral_eu"
    assert with_key.resolve(WS, "classify").name == "mistral_eu_small"
    without = Registry.load(path, env="dev", environ={}, validate=False)
    assert without.resolve(WS, "summarize").name == "dev_mac"
    assert without.resolve(WS, "title").name == "dev_mac"
    assert without.active_override("chat").reason == "missing_env"  # type: ignore[union-attr]
    # test env unchanged: cassettes.
    assert (
        Registry.load(path, env="test", environ={}, validate=False).resolve(WS, "classify").name
        == "recorded"
    )
