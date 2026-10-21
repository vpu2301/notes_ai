"""Hand-set model parameters (Sprint N0, trimmed by P2 to what the writer reads): bounded,
closed, capped by the backend."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from note_service.domain import model_params as mp


def test_the_defaults_are_the_models_own_values() -> None:
    p = mp.ModelParams()
    assert p.temperature == 0.0 and p.max_concurrency == 4 and p.max_output_tokens is None
    assert p.ask_temperature == 0.2 and p.ask_max_tokens == 700
    assert set(mp.ModelParams.model_fields) == {
        "temperature", "max_output_tokens", "max_concurrency", "ask_temperature", "ask_max_tokens"
    }  # fmt: skip


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": 0.8},
        {"temperature": 0.25},
        {"max_output_tokens": 10_000},
        {"max_concurrency": 0},
        {"ask_max_tokens": 5000},
        {"top_p": 0.9},
        {"facts_per_window": 16},
    ],
)
def test_out_of_range_or_unknown_is_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        mp.ModelParams.model_validate(bad)


def test_backend_caps_apply() -> None:
    p = mp.ModelParams(max_concurrency=8)
    assert mp.effective(p, max_concurrency=2).max_concurrency == 2
    # Under the cap, or no cap declared: unchanged.
    assert mp.effective(mp.DEFAULT, max_concurrency=4) is mp.DEFAULT
    assert mp.effective(p, max_concurrency=None) is p


def test_the_hash_is_stable_and_moves_with_the_params() -> None:
    a = mp.canonical_hash(mp.ModelParams(temperature=0.4))
    assert a == mp.canonical_hash(mp.ModelParams(temperature=0.4))
    assert a != mp.canonical_hash(mp.ModelParams(temperature=0.3))


def test_a_stored_object_with_old_fields_is_read_and_an_invalid_one_means_the_defaults() -> None:
    # P2: a row saved under N0 still carries the old path's fields; they are ignored.
    old = {
        "temperature": 0.4,
        "context_window_tokens": 32_768,
        "facts_per_window": 16,
        "retries": "off",
    }
    assert mp.from_stored(old).temperature == 0.4 and mp.is_valid(old)
    assert mp.from_stored({"temperature": 3.0}) is mp.DEFAULT
    assert mp.from_stored(None) == mp.DEFAULT
    assert mp.is_valid({"nope": 1}) and mp.is_valid({"temperature": 0.4})


def test_limits_name_the_backend_cap() -> None:
    lim = mp.limits(max_concurrency=2)
    assert lim["max_concurrency"]["cap"] == 2 and lim["max_concurrency"]["cap_source"] == "backend"
    assert lim["temperature"] == {"min": 0.0, "max": 0.7, "default": 0.0, "step": 0.1}
    assert "cap" not in mp.limits(max_concurrency=None)["max_concurrency"]
    assert set(lim) == {
        "temperature",
        "max_output_tokens",
        "max_concurrency",
        "ask_temperature",
        "ask_max_tokens",
    }
