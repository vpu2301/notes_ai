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
