"""DEP-S1-01: endpoint spec schema + plan diff (offline; no HF token)."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "hf_endpoints", REPO / "scripts" / "models" / "hf_endpoints.py"
)
assert _spec and _spec.loader
hf = importlib.util.module_from_spec(_spec)
sys.modules["hf_endpoints"] = hf
_spec.loader.exec_module(hf)


def _chat_spec() -> dict[str, Any]:
    return {
        "name": "notes-chat-{env}",
        "task": "text-generation",
        "type": "protected",
        "model": {
            "repository": "google/gemma-3-4b-it",
            "revision": "0" * 40,
            "framework": "pytorch",
            "image": {
                "tgi": {
                    "max_input_tokens": 24576,
                    "max_total_tokens": 32768,
                    "max_batch_prefill_tokens": 32768,
                }
            },
        },
        "provider": {"vendor": "aws", "region": "eu-west-1"},
        "compute": {
            "accelerator": "gpu",
            "instance_type": "nvidia-l4",
            "instance_size": "x1",
            "scaling": {"min_replica": 0, "max_replica": 2, "scale_to_zero_timeout": 15},
        },
    }


def test_committed_specs_validate_and_are_pinned() -> None:
    specs = hf.load_specs("staging")
    assert {s["name"] for s in specs} == {"notes-chat-staging", "notes-asr-staging"}
    for s in specs:
        assert hf._COMMIT.match(s["model"]["revision"]), (
            f"{s['_file']} is not pinned to an immutable commit"
        )
        assert s["provider"]["region"].startswith("eu-")
        assert s["type"] == "protected"
        assert s["compute"]["scaling"]["min_replica"] == 0


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda s: s.__setitem__("type", "public"), "protected"),
        (lambda s: s["provider"].__setitem__("region", "us-east-1"), "EU region"),
        (lambda s: s["model"].__setitem__("revision", "main"), "immutable commit"),
        (lambda s: s["compute"]["scaling"].__setitem__("min_replica", 1), "min_replica"),
        (lambda s: s["compute"]["scaling"].__setitem__("max_replica", 5), "max_replica"),
        (lambda s: s.__setitem__("retries", 3), "unknown top-level"),
        (lambda s: s.pop("compute"), "missing"),
    ],
)
def test_spec_rules(mutate: Any, match: str) -> None:
    spec = _chat_spec()
    mutate(spec)
    with pytest.raises(hf.SpecError, match=match):
        hf.validate_spec(spec, "chat.yaml")


def test_api_body_shape() -> None:
    body = hf.to_api_body(hf.load_specs("staging")[1])  # chat.yaml sorts after asr.yaml
    assert body["name"] == "notes-chat-staging"
    assert body["compute"]["scaling"] == {
        "minReplica": 0,
        "maxReplica": 2,
        "scaleToZeroTimeout": 15,
    }
    assert body["model"]["task"] == "text-generation"
    assert body["model"]["image"]["tgi"]["maxTotalTokens"] == 32768
    asr = hf.to_api_body(hf.load_specs("staging")[0])
    assert asr["model"]["image"]["custom"]["env"]["WHISPER__MODEL"].startswith("deepdml/")


def test_plan_diff_reports_only_drifted_keys() -> None:
    body = hf.to_api_body(_chat_spec())
    live = copy.deepcopy(body)
    live["status"] = {"state": "scaledToZero"}
    assert hf.diff(body, live) == []
    live["compute"]["scaling"]["maxReplica"] = 1
    live["model"]["revision"] = "1" * 40
    lines = hf.diff(body, live)
    assert len(lines) == 2
    assert any("compute.scaling.maxReplica: live=1 spec=2" in line for line in lines)
    assert any("model.revision" in line for line in lines)


def test_client_refuses_to_start_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_NAMESPACE", raising=False)
    with pytest.raises(SystemExit, match="HF_TOKEN"):
        hf.Client()
