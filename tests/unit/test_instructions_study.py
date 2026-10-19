"""N5: the note instructions study runs end to end on the scripted writer and canned
compiler, and its report carries numbers, ids and dial names only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *_strings(v)]]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_the_scripted_study_holds_every_code_dial_and_reports_numbers_only(tmp_path: Path) -> None:
    run = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "eval" / "instructions_study.py"),
         "--scripted", "--meetings", "2", "--out", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    [path] = list(tmp_path.glob("instructions-study-*.json"))
    report = json.loads(path.read_text("utf-8"))
    assert report["code_dials"] and all(v["ok"] == v["of"] for v in report["code_dials"].values())
    assert all(r["dials_matched"] == r["dials_expected"] for r in report["compile"]["rows"])
    assert len(report["red_team"]) == 40 and all(r["compiler_ok"] for r in report["red_team"])
    assert max(len(s) for s in _strings(report)) <= 80
    assert path.with_suffix(".md").read_text("utf-8").startswith("# Note instructions study")
