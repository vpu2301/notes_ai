from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from telemetry.runtime import (
    collect_run_context,
    end_snapshot,
    execution_mode,
    host_label,
    observe_device,
)


def test_context_on_this_machine_is_valid_and_honest() -> None:
    ctx = collect_run_context(uuid4(), uuid4(), app_commit=None, app_build=None,
                              effective_config={"asr_device": "cpu", "secret_key": "x"})  # fmt: skip
    assert ctx.execution_mode in ("native", "container")
    assert ctx.null_reasons["app_commit"] == "unavailable"
    assert "secret_key" not in ctx.effective_config
    for field in ("memory_pressure_end", "process_rss_end", "swap_used_end"):
        assert ctx.null_reasons[field] == "not_measured"
    # Each probe either measured or said why not.
    for field in ("chip_model", "memory_total_bytes", "process_rss_start", "swap_used_start"):
        assert getattr(ctx, field) is not None or field in ctx.null_reasons


def test_end_snapshot_pairs_values_with_reasons() -> None:
    for value, reason in end_snapshot().values():
        assert value is not None or reason in ("not_supported", "unavailable")


def test_host_label_never_carries_a_native_hostname() -> None:
    label = host_label()
    assert label.startswith("native-") if execution_mode() == "native" else label


def test_device_is_observed_only_from_the_backend() -> None:
    ct2_like = SimpleNamespace(model=SimpleNamespace(device="cuda"))
    assert observe_device(ct2_like, "cpu").model_dump() == {
        "value": "cuda",
        "observation": "observed",
    }
    wrapper = SimpleNamespace(device="cuda")  # a wrapper holding the *configured* string
    assert observe_device(wrapper, "cuda").observation == "configured"
    assert observe_device(object(), None) is None
