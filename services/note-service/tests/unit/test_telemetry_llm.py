"""Telemetry sprint 3, part A: every HTTP attempt of a model call through the REAL
OpenAI-compatible provider (httpx MockTransport) becomes one llm_call row + span, with tokens
exactly as reported, an accounting note, and nulls with reasons for what was not said."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

import telemetry
from models import ProviderError, set_attempt_sink
from models.openai_compat import OpenAICompatibleChatProvider
from telemetry import runs as t_runs
from telemetry import store as t_store
from telemetry.schema import LlmCall, SpanRecord


class _Recorder(t_store.NullStore):
    def __init__(self) -> None:
        super().__init__()
        self.spans: list[SpanRecord] = []
        self.calls: list[LlmCall] = []

    def span(self, record: SpanRecord) -> None:
        self.spans.append(record)

    def llm_call(self, call: LlmCall) -> None:
        self.calls.append(call)


@pytest.fixture
def recorder() -> Iterator[_Recorder]:
    rec = _Recorder()
    t_runs._settings = t_runs.Settings(enabled=True)
    t_store.configure(rec)
    telemetry.llm.install(set_attempt_sink)
    run = telemetry.RunRef(processing_run_id=uuid4(), tenant_id=uuid4(), recording_id=uuid4())
    token = telemetry.set_run(run)
    yield rec
    telemetry.reset_run(token)
    set_attempt_sink(None)
    t_store.configure(None)


def _ok(usage: dict[str, Any] | None, **extra: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "model": "mistral-large-2512",
        "choices": [
            {"message": {"content": "## Overview\nThe team agreed."}, "finish_reason": "stop"}
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body | extra)


def _provider(
    *responses: httpx.Response, base_url: str = "https://api.mistral.ai/v1"
) -> OpenAICompatibleChatProvider:
    queue = list(responses)

    async def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    async def no_sleep(_s: float) -> None:
        return None

    return OpenAICompatibleChatProvider(
        backend="mistral_eu", base_url=base_url, model_id="mistral-large-latest",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url),
        sleep=no_sleep,
    )  # fmt: skip


async def _write(provider: OpenAICompatibleChatProvider, purpose: str = "note_write") -> Any:
    return await telemetry.llm.call(
        purpose,
        provider,
        lambda: provider.complete("transcript", None, max_tokens=64, system="be brief"),
    )


async def test_provider_usage_is_stored_as_reported_with_its_note(recorder: _Recorder) -> None:
    provider = _provider(_ok({
        "prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500,
        "prompt_tokens_details": {"cached_tokens": 800},
        "completion_tokens_details": {"reasoning_tokens": 120},
    }))  # fmt: skip
    await _write(provider)
    (call,) = recorder.calls
    assert (call.input_tokens, call.output_tokens) == (1200, 300)  # subsets never added again
    assert (call.cached_input_tokens, call.reasoning_tokens) == (800, 120)
    assert call.token_source == "provider" and "subsets never added" in (
        call.token_accounting_note or ""
    )
    assert call.purpose == "note_write" and call.backend == "mistral_eu"
    assert call.model == "mistral-large-2512"  # what answered, not what was asked for
    assert call.execution_mode == "remote" and call.status == "ok"
    assert call.null_reasons["time_to_first_token_seconds"] == "not_applicable"  # non-streaming
    assert call.null_reasons["generation_tokens_per_second"] == "not_supported"
    assert call.prompt_chars == len("be brief") + len("transcript")
    (span,) = [s for s in recorder.spans if s.stage == "llm_call"]
    assert span.span_id == call.span_id and span.attributes["purpose"] == "note_write"


async def test_absent_subset_fields_are_null_with_a_reason(recorder: _Recorder) -> None:
    await _write(_provider(_ok({"prompt_tokens": 10, "completion_tokens": 5})))
    (call,) = recorder.calls
    assert (
        call.cached_input_tokens is None
        and call.null_reasons["cached_input_tokens"] == "unavailable"
    )
    assert call.reasoning_tokens is None and call.null_reasons["reasoning_tokens"] == "unavailable"


async def test_no_usage_object_is_estimated_and_said_so(recorder: _Recorder) -> None:
    await _write(_provider(_ok(None)))
    (call,) = recorder.calls
    assert call.token_source == "estimated" and "characters / 4" in (
        call.token_accounting_note or ""
    )
    assert call.input_tokens == round((len("be brief") + len("transcript")) / 4)


async def test_server_reported_speed_is_used_when_present(recorder: _Recorder) -> None:
    llama = _ok(
        {"prompt_tokens": 50, "completion_tokens": 20}, timings={"predicted_per_second": 41.5}
    )
    await _write(_provider(llama, base_url="http://llama-server:8080/v1"))
    (call,) = recorder.calls
    assert call.generation_tokens_per_second == 41.5 and call.execution_mode == "container"


async def test_retries_leave_one_row_per_attempt(recorder: _Recorder) -> None:
    provider = _provider(
        httpx.Response(429, json={"error": "slow down"}, headers={"Retry-After": "0"}),
        httpx.Response(503, json={"error": "busy"}),
        _ok({"prompt_tokens": 10, "completion_tokens": 5}),
    )
    await _write(provider)
    assert [(c.attempt, c.status) for c in recorder.calls] == [
        (1, "error"),
        (2, "error"),
        (3, "ok"),
    ]
    subtypes = [s.attributes.get("error_subtype") for s in recorder.spans if s.stage == "llm_call"]
    assert subtypes[0] == "rate_limit" and subtypes[2] is None
    assert all(c.error_category == "llm" for c in recorder.calls[:2])


async def test_a_failed_call_still_records_its_attempts(recorder: _Recorder) -> None:
    provider = _provider(httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(ProviderError):
        await _write(provider)
    (call,) = recorder.calls
    assert call.status == "error" and recorder.spans[-1].attributes["error_subtype"] == "auth"


async def test_outside_a_run_nothing_is_stored(recorder: _Recorder) -> None:
    token = telemetry.set_run(None)
    try:
        await _write(_provider(_ok({"prompt_tokens": 1, "completion_tokens": 1})))
    finally:
        telemetry.reset_run(token)
    assert recorder.calls == []


async def test_no_text_reaches_the_rows(recorder: _Recorder) -> None:
    await _write(_provider(_ok({"prompt_tokens": 1, "completion_tokens": 1})))
    blob = recorder.calls[0].model_dump_json() + recorder.spans[-1].model_dump_json()
    assert "transcript" not in blob and "The team agreed" not in blob and "be brief" not in blob


def test_the_worker_defines_everything_before_it_starts() -> None:
    """``python -m note_service.worker`` runs ``main()`` at the ``__main__`` guard; a helper
    defined below it does not exist yet (the Sprint 3 probe hook died on that)."""
    import ast
    from pathlib import Path

    from note_service import worker

    body = ast.parse(Path(worker.__file__).read_text()).body
    assert isinstance(body[-1], ast.If) and "__main__" in ast.unparse(body[-1].test)


async def test_an_armed_dev_fault_goes_through_the_retry_loop(recorder: _Recorder) -> None:
    # Sprint 5 (S3): one injected 503, then the real reply: two attempts, the second ok.
    from models import faults

    faults.arm_chat_failures(1)
    try:
        await _write(_provider(_ok({"prompt_tokens": 10, "completion_tokens": 2})))
    finally:
        faults.arm_chat_failures(0)
    assert [(c.attempt, c.status) for c in recorder.calls] == [(1, "error"), (2, "ok")]
    assert recorder.calls[0].error_category == "llm"
