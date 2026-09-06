"""Shared fixtures: a minimal config dict and an httpx MockTransport factory."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

CASSETTES = Path(__file__).resolve().parents[1] / "cassettes"


def cassette(name: str) -> dict[str, Any]:
    return json.loads((CASSETTES / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def base_config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "version": 1,
        "backends": {
            "dev_mac": {
                "kind": "openai_compat",
                "base_url": "${DEV_MAC_MODEL_URL:-http://localhost:11434/v1}",
                "auth": "none",
                "enabled_in_envs": ["dev"],
                "models": {"chat": "${DEV_MAC_CHAT_MODEL:-notes-chat}"},
                "processor": {"name": "Developer machine", "region": "local"},
            },
            "dev_mac_asr": {
                "kind": "asr_http",
                "base_url": "${DEV_MAC_ASR_URL:-http://localhost:8080}",
                "enabled_in_envs": ["dev"],
                "models": {"asr": "whisper"},
                "processor": {"name": "Developer machine", "region": "local"},
            },
            "hf_eu": {
                "kind": "openai_compat",
                "base_url": "${HF_CHAT_ENDPOINT_URL}",
                "auth": "bearer:${HF_TOKEN}",
                "enabled_in_envs": ["staging", "prod"],
                "models": {"chat": "${HF_CHAT_MODEL_PIN}"},
                "structured_output": "probe",
                "cold_start_seconds": 300,
                "processor": {"name": "Hugging Face Inference Endpoints", "region": "EU"},
            },
            "hf_eu_asr": {
                "kind": "asr_http",
                "base_url": "${HF_ASR_ENDPOINT_URL}",
                "auth": "bearer:${HF_TOKEN}",
                "enabled_in_envs": ["staging", "prod"],
                "models": {"asr": "${HF_ASR_MODEL_PIN}"},
                "processor": {"name": "Hugging Face Inference Endpoints", "region": "EU"},
            },
            "hosted_eu": {
                "kind": "openai_compat",
                "enabled": False,
                "base_url": "${HOSTED_MODEL_URL:-}",
                "auth": "bearer:${HOSTED_MODEL_TOKEN:-}",
                "enabled_in_envs": ["staging", "prod"],
                "models": {"chat": "${HOSTED_CHAT_MODEL_PIN:-}"},
                "structured_output": "guided_json",
                "processor": {"name": "Notes AI (own EU host)", "region": "EU"},
            },
            "anthropic": {
                "kind": "anthropic",
                "enabled": False,
                "models": {"chat": "claude-x"},
                "processor": {"name": "Anthropic", "region": "US/EU"},
            },
            "inproc_cpu_asr": {"kind": "asr_inproc"},
            "recorded": {
                "kind": "recorded",
                "enabled_in_envs": ["test"],
                "cassette_dir": "tests/fixtures/eval/cassettes",
            },
        },
        "routing": {
            "understand": {"standard": "hf_eu", "premium": "hf_eu"},
            "summarize": {"standard": "hf_eu", "premium": "hf_eu"},
            "asr": {"standard": "hf_eu_asr", "premium": "hf_eu_asr"},
        },
        "env_overrides": {
            "dev": {"chat": "dev_mac", "asr": "dev_mac_asr"},
            "test": {"chat": "recorded", "asr": "inproc_cpu_asr"},
        },
    }
    cfg.update(overrides)
    return cfg


STAGING_ENV = {
    "HF_CHAT_ENDPOINT_URL": "https://x.endpoints.huggingface.cloud/v1",
    "HF_TOKEN": "hf_secret_token",
    "HF_CHAT_MODEL_PIN": "Qwen/Qwen3-8B",
    "HF_ASR_ENDPOINT_URL": "https://y.endpoints.huggingface.cloud",
    "HF_ASR_MODEL_PIN": "openai/whisper-large-v3-turbo",
}

Handler = Callable[[httpx.Request], httpx.Response]


def mock_client(handler: Handler, base_url: str = "http://test/v1") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)


def json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {})
