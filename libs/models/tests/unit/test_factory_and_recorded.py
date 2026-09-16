from __future__ import annotations

from pathlib import Path

import pytest

from models import (
    ConfigError,
    ErrorKind,
    HTTPASRProvider,
    InProcASRProvider,
    OpenAICompatibleChatProvider,
    ProviderError,
    ProviderResult,
    RecordedChatProvider,
    Registry,
    build_asr_provider,
    build_chat_provider,
)

from .conftest_helpers import STAGING_ENV, base_config
from .test_asr_inproc import _FakeEngine


def test_factory_builds_by_kind_never_by_name(tmp_path: Path) -> None:
    cfg = base_config()
    cfg["backends"]["recorded"]["cassette_dir"] = str(tmp_path)
    dev = Registry.load(cfg, env="dev", environ={})
    chat = build_chat_provider(dev.backend("dev_mac"))
    assert (
        isinstance(chat, OpenAICompatibleChatProvider)
        and chat.backend == "dev_mac"
        and chat.model_id == "notes-chat"
    )
    asr = build_asr_provider(dev.backend("dev_mac_asr"))
    assert isinstance(asr, HTTPASRProvider)
    test = Registry.load(cfg, env="test", environ={})
    assert isinstance(build_chat_provider(test.backend("recorded")), RecordedChatProvider)
    inproc = build_asr_provider(test.backend("inproc_cpu_asr"), inproc_engine=_FakeEngine())
    assert isinstance(inproc, InProcASRProvider)
    with pytest.raises(ConfigError, match="engine"):
        build_asr_provider(test.backend("inproc_cpu_asr"))
    with pytest.raises(ConfigError) as exc:
        build_chat_provider(test.backend("inproc_cpu_asr"))
    assert exc.value.code == "kind_mismatch"


def test_staging_chat_provider_carries_token_and_cold_start() -> None:
    cfg = base_config()
    cfg["backends"]["hf_eu"]["request_overrides"] = {"reasoning_effort": "none"}
    reg = Registry.load(cfg, env="staging", environ=STAGING_ENV)
    resolved = reg.backend("hf_eu")
    assert resolved.caps.cold_start_seconds == 300 and resolved.caps.structured_output == "probe"
    provider = build_chat_provider(resolved)
    assert isinstance(provider, OpenAICompatibleChatProvider)
    assert provider._client.headers["authorization"] == "Bearer hf_secret_token"
    assert provider.request_overrides == {"reasoning_effort": "none"}


def test_anthropic_backend_is_not_configured() -> None:
    from models.anthropic import AnthropicProvider

    with pytest.raises(ConfigError) as exc:
        AnthropicProvider(model_id="x")
    assert exc.value.code == "provider_not_configured"


async def test_recorded_provider_roundtrip_and_miss(tmp_path: Path) -> None:
    p = RecordedChatProvider(backend="recorded", cassette_dir=tmp_path)
    schema = {"type": "object", "required": ["a"]}
    with pytest.raises(ProviderError) as exc:
        await p.complete("hello", schema, max_tokens=5)
    assert exc.value.kind is ErrorKind.UNAVAILABLE
    p.record(
        "hello",
        schema,
        None,
        ProviderResult(
            text='{"a": 1}',
            json={"a": 1},
            input_tokens=3,
            output_tokens=2,
            latency_ms=1,
            backend="dev_mac",
            model_id="m",
            structured_mode="json_schema",
        ),
    )
    result = await p.complete("hello", schema, max_tokens=5)
    assert result.json == {"a": 1} and result.backend == "recorded" and result.input_tokens == 3
