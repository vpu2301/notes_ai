"""MDX_DIAR_ENGINE → the diarizer behind the seam, and the pyannote env pin."""

from __future__ import annotations

import os

import pytest

from asr_worker import config
from asr_worker.main_deps import build_diarizer
from diarization import Diarizer, HttpDiarizer, LegacyEcapaDiarizer, PyannoteDiarizer


def test_each_engine_name_builds_its_diarizer() -> None:
    legacy = build_diarizer("legacy")
    v2 = build_diarizer("pyannote")

    assert isinstance(legacy, LegacyEcapaDiarizer)
    assert isinstance(v2, PyannoteDiarizer)
    assert isinstance(legacy, Diarizer) and isinstance(v2, Diarizer)
    # Built, never loaded: a worker without the weights still transcribes.
    assert not legacy.ready and not v2.ready


@pytest.mark.parametrize("name", ["remote", "pyannote-community-1", ""])
def test_an_unknown_engine_fails_at_startup(name: str) -> None:
    with pytest.raises(ValueError, match="MDX_DIAR_ENGINE"):
        build_diarizer(name)


def test_the_http_engine_is_resolved_through_the_backend_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shape B (ADR-0052): URL, token, timeout and the processor on the
    Data page all come from config/models.yaml — never from a new env
    var of this service's own."""
    monkeypatch.setattr(config.settings, "models_env", "dev")
    monkeypatch.setattr(config.settings, "diar_http_backend", "")

    remote = build_diarizer("http")

    assert isinstance(remote, HttpDiarizer) and isinstance(remote, Diarizer)
    # dev has a `diarization` override, so no per-service name is needed.
    assert remote.engine == "http:dev_mac_diar"
    assert remote.remote is True and not remote.ready
    assert remote.engine_version == "pyannote-community-1"


def test_an_unknown_remote_backend_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "models_env", "dev")
    monkeypatch.setattr(config.settings, "diar_http_backend", "nonesuch")

    with pytest.raises(Exception, match="nonesuch"):
        build_diarizer("http")


def test_a_backend_of_the_wrong_kind_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pointing the diarizer at the transcription endpoint must not start."""
    monkeypatch.setattr(config.settings, "models_env", "dev")
    monkeypatch.setattr(config.settings, "diar_http_backend", "dev_mac_asr")

    with pytest.raises(Exception, match="kind"):
        build_diarizer("http")


def test_config_pins_pyannote_offline_with_telemetry_off() -> None:
    """pyannote.audio 4.x ships telemetry on; importing the worker's config
    must already have switched it off, before anything imports pyannote."""
    assert config.PYANNOTE_PROCESS_ENV == {
        "PYANNOTE_METRICS_ENABLED": "false",
        "HF_HUB_OFFLINE": "1",
    }
    for key, value in config.PYANNOTE_PROCESS_ENV.items():
        assert os.environ[key] == value


def test_v2_batch_defaults_follow_the_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "diar_v2_batch", 0)
    monkeypatch.setattr(config.settings, "diar_device", "cpu")
    assert config.settings.diar_v2_batch_size() == 16
    monkeypatch.setattr(config.settings, "diar_device", "cuda:0")
    assert config.settings.diar_v2_batch_size() == 32


def test_v2_pins_must_be_a_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "diar_v2_pins", '{"pytorch_model.bin": "ab"}')
    assert config.settings.diar_v2_pin_map() == {"pytorch_model.bin": "ab"}
    monkeypatch.setattr(config.settings, "diar_v2_pins", '["x"]')
    with pytest.raises(ValueError, match="MDX_DIAR_V2_PINS"):
        config.settings.diar_v2_pin_map()
