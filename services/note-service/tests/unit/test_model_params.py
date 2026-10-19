"""Hand-set model parameters (Sprint N0): bounded, closed, capped by the backend."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from note_service.domain import model_params as mp


def test_the_defaults_are_todays_behaviour() -> None:
    p = mp.ModelParams()
    assert p.temperature == 0.0 and p.max_concurrency == 4 and p.facts_per_window == 24
    assert p.context_window_tokens is None and p.max_output_tokens is None
    assert p.retries == "standard" and p.ask_temperature == 0.2 and p.ask_max_tokens == 700


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": 0.8},
        {"temperature": 0.25},
        {"context_window_tokens": 4096},
        {"max_output_tokens": 10_000},
        {"max_concurrency": 0},
        {"facts_per_window": 30},
        {"retries": "always"},
        {"ask_max_tokens": 5000},
        {"top_p": 0.9},
    ],
)
def test_out_of_range_or_unknown_is_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        mp.ModelParams.model_validate(bad)


def test_backend_caps_apply() -> None:
    p = mp.ModelParams(context_window_tokens=65_536, max_concurrency=8)
    capped = mp.effective(p, context_window=32_768, max_concurrency=2)
    assert capped.context_window_tokens == 32_768 and capped.max_concurrency == 2
    # Under the cap, or no cap declared: unchanged.
    assert mp.effective(mp.DEFAULT, context_window=32_768, max_concurrency=4) is mp.DEFAULT
    assert mp.effective(p, context_window=None, max_concurrency=None) is p


def test_the_hash_is_stable_and_moves_with_params_and_style() -> None:
    a = mp.canonical_hash(mp.ModelParams(temperature=0.4), "business")
    assert a == mp.canonical_hash(mp.ModelParams(temperature=0.4), "business")
    assert a != mp.canonical_hash(mp.ModelParams(temperature=0.4), "academic")
    assert a != mp.canonical_hash(mp.ModelParams(temperature=0.3), "business")


def test_an_invalid_stored_object_means_the_defaults() -> None:
    assert mp.from_stored({"temperature": 3.0}) is mp.DEFAULT
    assert mp.from_stored(None) == mp.DEFAULT
    assert not mp.is_valid({"nope": 1}) and mp.is_valid({"temperature": 0.4})


def test_limits_name_the_backend_cap() -> None:
    lim = mp.limits(context_window=32_768, max_concurrency=2)
    assert lim["context_window_tokens"]["cap"] == 32_768
    assert lim["context_window_tokens"]["cap_source"] == "backend"
    assert lim["temperature"] == {"min": 0.0, "max": 0.7, "default": 0.0, "step": 0.1}
    assert "cap" not in mp.limits(context_window=None, max_concurrency=None)["max_concurrency"]


def test_retry_policy() -> None:
    assert mp.retry_budget("off", 90.0) == 0.0
    assert mp.retry_budget("standard", 90.0) == 90.0
    assert mp.retry_budget("thorough", 90.0) == 180.0
    assert mp.retry_budget("thorough", None) is None
