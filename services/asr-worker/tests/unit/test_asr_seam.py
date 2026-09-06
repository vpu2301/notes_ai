"""DEP-S0: asr-worker resolves ``ASR_BACKEND`` through libs/models.

The default keeps the in-process engine (no config file needed beyond the
committed one); an HTTP backend is refused outside its env; a
``ProviderError`` from an HTTP backend is classified, not leaked as
``unhandled``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from asr_worker import main_deps
from asr_worker.config import settings
from asr_worker.inference import TranscriptionCancelledError, WhisperEngine
from models import ConfigError, HTTPASRProvider, InProcASRProvider
from models import TranscriptionCancelledError as SeamCancelled

REPO_CONFIG = Path(__file__).resolve().parents[4] / "config" / "models.yaml"


@pytest.fixture(autouse=True)
def _repo_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "models_config", str(REPO_CONFIG))
    monkeypatch.setattr(settings, "models_env", "dev")


def test_default_backend_wraps_whisper_engine_without_loading() -> None:
    provider = main_deps.build_asr("inproc_cpu_asr")
    assert isinstance(provider, InProcASRProvider)
    assert isinstance(provider.engine, WhisperEngine)
    assert provider.is_loaded is False  # warm_up() loads; build_asr never does
    assert provider.backend == "inproc_cpu_asr"


def test_dev_mac_asr_builds_http_provider_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_MAC_ASR_URL", "http://localhost:8090")
    provider = main_deps.build_asr("dev_mac_asr")
    assert isinstance(provider, HTTPASRProvider)
    assert provider.backend == "dev_mac_asr" and provider.is_loaded is False


def test_dev_mac_asr_is_refused_on_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "models_env", "staging")
    with pytest.raises(ConfigError) as exc:
        main_deps.build_asr("dev_mac_asr")
    assert exc.value.code == "backend_not_allowed_in_env"


def test_chat_backend_is_not_an_asr_backend() -> None:
    with pytest.raises(ConfigError) as exc:
        main_deps.build_asr("dev_mac")
    assert exc.value.code == "kind_mismatch"


def test_unknown_backend_fails_at_startup() -> None:
    with pytest.raises(ConfigError) as exc:
        main_deps.build_asr("gpu_of_our_dreams")
    assert exc.value.code == "unknown_backend"


def test_registry_env_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "models_env", "")
    monkeypatch.setattr(settings, "testing", False)
    for environment, expected in (
        ("development", "dev"),
        ("staging", "staging"),
        ("production", "prod"),
    ):
        monkeypatch.setattr(settings, "environment", environment)
        assert settings.registry_env() == expected
    monkeypatch.setattr(settings, "testing", True)
    assert settings.registry_env() == "test"


def test_worker_cancellation_error_is_the_seams_error() -> None:
    # processor.py catches the lib's base class; the worker's own subclass
    # (raised by WhisperEngine) must still be caught by it.
    assert issubclass(TranscriptionCancelledError, SeamCancelled)
