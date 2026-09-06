from __future__ import annotations

import pytest

from models import ConfigError, parse_config

from .conftest_helpers import STAGING_ENV, base_config


def test_unknown_key_is_rejected() -> None:
    cfg = base_config()
    cfg["backends"]["dev_mac"]["retries"] = 3
    with pytest.raises(ConfigError) as exc:
        parse_config(cfg, environ={}, source="t")
    assert exc.value.code == "invalid_config"
    assert "retries" in str(exc.value)


def test_unknown_top_level_key_is_rejected() -> None:
    cfg = base_config(fallback={"chat": "dev_mac"})
    with pytest.raises(ConfigError, match="fallback"):
        parse_config(cfg, environ={}, source="t")


def test_missing_env_is_recorded_per_backend_not_fatal_at_parse() -> None:
    loaded = parse_config(base_config(), environ={}, source="t")
    assert loaded.unresolved["hf_eu"] == ["HF_CHAT_ENDPOINT_URL", "HF_CHAT_MODEL_PIN", "HF_TOKEN"]
    assert "dev_mac" not in loaded.unresolved  # every placeholder there has a default


def test_env_and_defaults_interpolate() -> None:
    loaded = parse_config(
        base_config(), environ={"DEV_MAC_CHAT_MODEL": "qwen3:8b", **STAGING_ENV}, source="t"
    )
    assert loaded.unresolved == {}
    assert loaded.config.backends["dev_mac"].models["chat"] == "qwen3:8b"
    assert loaded.config.backends["dev_mac"].base_url == "http://localhost:11434/v1"
    assert loaded.config.backends["hf_eu"].bearer_token() == "hf_secret_token"


def test_empty_env_value_falls_back_to_default() -> None:
    loaded = parse_config(base_config(), environ={"DEV_MAC_CHAT_MODEL": ""}, source="t")
    assert loaded.config.backends["dev_mac"].models["chat"] == "notes-chat"


def test_token_never_appears_in_repr_or_dump() -> None:
    loaded = parse_config(base_config(), environ=STAGING_ENV, source="t")
    backend = loaded.config.backends["hf_eu"]
    assert "hf_secret_token" not in repr(backend)
    assert "hf_secret_token" not in str(backend.model_dump())
    assert "hf_secret_token" not in backend.model_dump_json()


def test_local_processor_may_not_be_enabled_outside_dev_or_test() -> None:
    cfg = base_config()
    cfg["backends"]["dev_mac"]["enabled_in_envs"] = ["dev", "staging"]
    with pytest.raises(ConfigError) as exc:
        parse_config(cfg, environ={}, source="t")
    assert exc.value.code == "backend_not_allowed_in_env"


def test_routing_to_unknown_backend_is_rejected() -> None:
    cfg = base_config()
    cfg["routing"]["understand"]["premium"] = "nope"
    with pytest.raises(ConfigError) as exc:
        parse_config(cfg, environ={}, source="t")
    assert exc.value.code == "unknown_backend"


def test_routing_kind_mismatch_is_rejected() -> None:
    cfg = base_config()
    cfg["routing"]["asr"]["standard"] = "hf_eu"
    with pytest.raises(ConfigError) as exc:
        parse_config(cfg, environ={}, source="t")
    assert exc.value.code == "kind_mismatch"


def test_unknown_operation_is_rejected() -> None:
    cfg = base_config()
    cfg["routing"]["translate"] = {"standard": "hf_eu"}
    with pytest.raises(ConfigError, match="translate"):
        parse_config(cfg, environ={}, source="t")


def test_unknown_env_in_overrides_is_rejected() -> None:
    cfg = base_config()
    cfg["env_overrides"]["production"] = {"chat": "hf_eu"}
    with pytest.raises(ConfigError, match="production"):
        parse_config(cfg, environ={}, source="t")


def test_bad_auth_shape_is_rejected() -> None:
    cfg = base_config()
    cfg["backends"]["dev_mac"]["auth"] = "basic:foo"
    with pytest.raises(ConfigError, match="bearer"):
        parse_config(cfg, environ={}, source="t")


def test_repo_config_file_parses_in_every_env(tmp_path: object) -> None:
    """The committed config/models.yaml must load with no env at all."""
    from pathlib import Path

    from models import load_config

    repo_file = Path(__file__).resolve().parents[4] / "config" / "models.yaml"
    loaded = load_config(repo_file, environ={})
    assert set(loaded.config.backends) >= {
        "dev_mac",
        "dev_mac_asr",
        "hf_eu",
        "hf_eu_asr",
        "hosted_eu",
        "inproc_cpu_asr",
        "recorded",
        "anthropic",
    }
    assert loaded.config.backends["hosted_eu"].enabled is False
