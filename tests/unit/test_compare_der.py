"""The nightly DER gate: regressions fail, gaps are not passes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "compare_der", REPO / "scripts" / "eval" / "compare_der.py"
)
assert _spec is not None and _spec.loader is not None
compare_der = importlib.util.module_from_spec(_spec)
sys.modules["compare_der"] = compare_der
_spec.loader.exec_module(compare_der)


def _report(two_speaker_exact: float | None) -> dict[str, Any]:
    buckets = {"4": {"files": 9, "count_exact": 0.5}}
    if two_speaker_exact is not None:
        buckets["2"] = {"files": 4, "count_exact": two_speaker_exact}
    return {"by_n_speakers": buckets}


def test_a_drop_within_five_points_passes() -> None:
    code, _ = compare_der.compare(_report(1.0), _report(0.95), n_speakers=2, max_drop=0.05)
    assert code == 0


def test_a_drop_beyond_five_points_fails() -> None:
    code, line = compare_der.compare(_report(1.0), _report(0.75), n_speakers=2, max_drop=0.05)
    assert code == 1
    assert "1.000 → 0.750" in line


def test_an_improvement_passes() -> None:
    code, _ = compare_der.compare(_report(0.75), _report(1.0), n_speakers=2, max_drop=0.05)
    assert code == 0


def test_a_missing_bucket_is_not_a_pass() -> None:
    code, line = compare_der.compare(_report(1.0), _report(None), n_speakers=2, max_drop=0.05)
    assert code == 2
    assert "current" in line
