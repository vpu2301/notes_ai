from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from models import (
    ErrorKind,
    OpenAICompatibleChatProvider,
    ProviderError,
    ProviderResult,
    UsageRecord,
    set_usage_sink,
)

from .conftest_helpers import cassette, json_response, mock_client

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "n": {"type": "integer"}},
    "required": ["title", "n"],
}
PROMPT = "Return a JSON object with keys title (string) and n (integer) about a meeting."


async def _noop_sleep(_s: float) -> None:
    return None


def _provider(handler: Any, **kw: Any) -> OpenAICompatibleChatProvider:
    defaults: dict[str, Any] = {
        "backend": "test_backend",
        "base_url": "http://test/v1",
        "model_id": "m",
        "client": mock_client(handler),
        "sleep": _noop_sleep,
    }
    defaults.update(kw)
    return OpenAICompatibleChatProvider(**defaults)


def _strip(result: ProviderResult) -> dict[str, Any]:
    d = (
        result.__dict__.copy()
        if hasattr(result, "__dict__")
        else {k: getattr(result, k) for k in result.__slots__}
    )
    d.pop("latency_ms")
    d.pop("model_id")
    return d


# ── contract: three server shapes → identical ProviderResult ────────────
@pytest.mark.parametrize("name", ["ollama_chat.json", "vllm_chat.json", "tgi_chat.json"])
async def test_recorded_shapes_yield_identical_result(name: str) -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return json_response(200, cassette(name))

    result = await _provider(handler).complete(PROMPT, SCHEMA, max_tokens=60)
    assert _strip(result) == {
        "text": '{"title": "Project Phoenix Kickoff", "n": 1}',
        "json": {"title": "Project Phoenix Kickoff", "n": 1},
        "input_tokens": 29,
        "output_tokens": 16,
        "backend": "test_backend",
        "structured_mode": "json_schema",
        "finish_reason": "stop",
    }
    body = seen[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["temperature"] == 0.0 and body["max_tokens"] == 60 and body["stream"] is False
    assert seen[0]["messages"][-1]["content"] == PROMPT  # schema not in-band in json_schema mode


async def test_json_object_mode_puts_schema_in_band() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return json_response(200, cassette("ollama_chat.json"))

    await _provider(handler, structured_output="json_object").complete(
        PROMPT, SCHEMA, max_tokens=60
    )
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in seen[0]["messages"][-1]["content"]


async def test_guided_json_mode_for_vllm() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return json_response(200, cassette("vllm_chat.json"))

    await _provider(handler, structured_output="guided_json").complete(
        PROMPT, SCHEMA, max_tokens=60
    )
    assert seen[0]["guided_json"] == SCHEMA


async def test_bearer_token_is_sent_and_system_prompt_first() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(200, cassette("tgi_chat.json"))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test/v1",
        headers={"Authorization": "Bearer tok"},
    )
    p = OpenAICompatibleChatProvider(
        backend="b", base_url="http://test/v1", model_id="m", client=client
    )
    await p.complete("hi", None, max_tokens=5, system="be terse")
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert json.loads(seen[0].content)["messages"][0] == {"role": "system", "content": "be terse"}


# ── error mapping ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("status", "body", "headers", "cold", "kind"),
    [
        (429, {"error": {"message": "slow down"}}, {"retry-after": "7"}, 0, ErrorKind.RATE_LIMITED),
        (503, {"error": "Model is currently loading"}, {}, 300, ErrorKind.WARMING),
        (503, {"error": "down"}, {}, 0, ErrorKind.UNAVAILABLE),
        (401, {"error": "bad token"}, {}, 0, ErrorKind.AUTH),
        (403, {"error": "forbidden"}, {}, 0, ErrorKind.AUTH),
        (
            400,
            {"error": {"message": "This model's maximum context length is 4096 tokens"}},
            {},
            0,
            ErrorKind.CONTEXT_EXCEEDED,
        ),
        (
            400,
            {"error": {"message": "response_format json_schema is not supported"}},
            {},
            0,
            ErrorKind.SCHEMA_INVALID,
        ),
        (400, {"error": {"message": "something else"}}, {}, 0, ErrorKind.UNKNOWN),
        (404, {"error": "model not found"}, {}, 0, ErrorKind.UNAVAILABLE),
        (500, {"error": "boom"}, {}, 0, ErrorKind.UNAVAILABLE),
        (504, "", {}, 0, ErrorKind.TIMEOUT),
    ],
)
async def test_status_mapping(
    status: int, body: Any, headers: dict[str, str], cold: int, kind: ErrorKind
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            json_response(status, body, headers) if body != "" else httpx.Response(status, text="")
        )

    p = _provider(handler, cold_start_seconds=cold)
    with pytest.raises(ProviderError) as exc:
        await p.complete("x", None, max_tokens=5)
    assert exc.value.kind is kind
    assert exc.value.status == status
    if status == 429:
        assert exc.value.retry_after_s == 7.0
        assert exc.value.retryable is True
        assert calls == 1  # rate_limited is the job policy's retry, not the provider's


async def test_timeouts_and_connect_errors_map_and_retry_thrice() -> None:
    for exc_cls, kind in (
        (httpx.ReadTimeout, ErrorKind.TIMEOUT),
        (httpx.ConnectError, ErrorKind.UNAVAILABLE),
        (httpx.ConnectTimeout, ErrorKind.TIMEOUT),
    ):
        calls = 0

        def handler(_request: httpx.Request, _cls: type[Exception] = exc_cls) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise _cls("x")

        with pytest.raises(ProviderError) as exc:
            await _provider(handler).complete("x", None, max_tokens=5)
        assert exc.value.kind is kind
        assert calls == 3


async def test_warming_retries_until_cold_start_budget_then_succeeds() -> None:
    calls = 0
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return json_response(503, {"error": "scaling"}, {"retry-after": "5"})
        return json_response(200, cassette("tgi_chat.json"))

    p = _provider(handler, cold_start_seconds=300, sleep=sleep)
    result = await p.complete("x", None, max_tokens=5)
    assert result.text.startswith("{")
    assert calls == 3 and slept == [5.0, 5.0]


async def test_warming_without_budget_is_not_retried() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(503, {"error": "scaling"})

    p = _provider(handler, cold_start_seconds=0)
    with pytest.raises(ProviderError) as exc:
        await p.complete("x", None, max_tokens=5)
    assert exc.value.kind is ErrorKind.UNAVAILABLE and calls == 3  # unavailable → bounded retries


async def test_non_retryable_kinds_are_never_retried() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(401, {"error": "no"})

    with pytest.raises(ProviderError):
        await _provider(handler).complete("x", None, max_tokens=5)
    assert calls == 1


async def test_finish_reason_length_is_context_exceeded() -> None:
    body = cassette("ollama_chat.json")
    body["choices"][0]["finish_reason"] = "length"
    body["choices"][0]["message"]["content"] = '{"title": "Project Pho'

    with pytest.raises(ProviderError) as exc:
        await _provider(lambda _r: json_response(200, body)).complete(PROMPT, SCHEMA, max_tokens=5)
    assert exc.value.kind is ErrorKind.CONTEXT_EXCEEDED
    assert exc.value.retryable is False


async def test_invalid_json_and_missing_required_are_schema_invalid() -> None:
    body = cassette("ollama_chat.json")
    body["choices"][0]["message"]["content"] = "Sure! Here you go"
    with pytest.raises(ProviderError) as exc:
        await _provider(lambda _r: json_response(200, body)).complete(PROMPT, SCHEMA, max_tokens=5)
    assert exc.value.kind is ErrorKind.SCHEMA_INVALID

    body["choices"][0]["message"]["content"] = '{"title": "x"}'
    with pytest.raises(ProviderError, match="missing required"):
        await _provider(lambda _r: json_response(200, body)).complete(PROMPT, SCHEMA, max_tokens=5)


async def test_fenced_json_is_accepted() -> None:
    body = cassette("ollama_chat.json")
    body["choices"][0]["message"]["content"] = '```json\n{"title": "x", "n": 2}\n```'
    result = await _provider(lambda _r: json_response(200, body)).complete(
        PROMPT, SCHEMA, max_tokens=5
    )
    assert result.json == {"title": "x", "n": 2}


async def test_probe_mode_falls_back_to_json_object() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body.get("response_format", {}).get("type") == "json_schema":
            return json_response(
                400, {"error": {"message": "response_format.type json_schema is not supported"}}
            )
        out = cassette("tgi_chat.json")
        out["choices"][0]["message"]["content"] = '{"ok": true}'
        return json_response(200, out)

    p = _provider(handler, structured_output="probe")
    await p.probe()
    assert p.structured_mode == "json_object"
    assert [b["response_format"]["type"] for b in seen] == ["json_schema", "json_object"]


# ── usage + log hygiene ─────────────────────────────────────────────────
async def test_usage_record_emitted_without_content(caplog: pytest.LogCaptureFixture) -> None:
    records: list[UsageRecord] = []
    set_usage_sink(records.append)
    try:
        with caplog.at_level(logging.DEBUG):
            await _provider(lambda _r: json_response(200, cassette("ollama_chat.json"))).complete(
                "SECRET_PROMPT_CONTENT", SCHEMA, max_tokens=60, workspace_id="ws-1"
            )
    finally:
        set_usage_sink(None)
    assert len(records) == 1
    rec = records[0]
    assert (
        rec.backend,
        rec.model_id,
        rec.ok,
        rec.input_tokens,
        rec.output_tokens,
        rec.workspace_id,
    ) == ("test_backend", "m", True, 29, 16, "ws-1")
    dumped = json.dumps(
        rec.__dict__ if hasattr(rec, "__dict__") else {k: getattr(rec, k) for k in rec.__slots__}
    )
    assert "SECRET_PROMPT_CONTENT" not in dumped and "Phoenix" not in dumped
    log_blob = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "SECRET_PROMPT_CONTENT" not in log_blob and "Phoenix" not in log_blob


async def test_failed_call_emits_usage_with_error_kind() -> None:
    records: list[UsageRecord] = []
    set_usage_sink(records.append)
    try:
        with pytest.raises(ProviderError):
            await _provider(lambda _r: json_response(401, {"error": "x"})).complete(
                "x", None, max_tokens=5
            )
    finally:
        set_usage_sink(None)
    assert records[0].ok is False and records[0].error_kind == "auth" and records[0].attempts == 1


async def test_error_message_never_echoes_prompt(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as exc:
        await _provider(handler).complete("VERY_PRIVATE", None, max_tokens=5)
    assert "VERY_PRIVATE" not in str(exc.value)
    assert "VERY_PRIVATE" not in "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)


async def test_request_overrides_are_merged_into_every_body() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return json_response(200, cassette("ollama_chat.json"))

    p = _provider(handler, request_overrides={"reasoning_effort": "none"})
    await p.complete("x", None, max_tokens=5)
    await p.complete(PROMPT, SCHEMA, max_tokens=5)
    assert all(b["reasoning_effort"] == "none" for b in seen)
    assert seen[1]["response_format"]["type"] == "json_schema"


async def test_provider_error_never_contains_the_bearer_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "hf_supersecret_token_value_1234"

    def handler(_request: httpx.Request) -> httpx.Response:
        # Some gateways echo the Authorization header into the error body.
        return json_response(
            429, {"error": {"message": f"quota exceeded for Bearer {token} on endpoint"}}
        )

    p = OpenAICompatibleChatProvider(
        backend="hf_eu",
        base_url="http://test/v1",
        model_id="m",
        auth_token=token,
        client=mock_client(handler),
        sleep=_noop_sleep,
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as exc:
        await p.complete("x", None, max_tokens=5)
    assert (
        token not in str(exc.value)
        and token not in exc.value.message
        and token not in repr(exc.value)
    )
    assert "***" in exc.value.message
    assert token not in "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
